"""Two-step approval workflow (Slice 87).

What this module owns
---------------------

- ``invoice_requires_approval(invoice)`` — pure predicate that
  reads the org's ``approval_policy`` (and threshold, when
  applicable) and returns whether the given invoice is subject to
  approval.
- ``request_approval(invoice_id, actor_user_id, reason)`` — moves
  the invoice into ``AWAITING_APPROVAL``, creates a pending
  ``ApprovalRequest`` row, audits the request.
- ``approve(approval_id, actor_user_id, note)`` — gates on the
  Approver/Owner/Admin role, marks the row approved, advances the
  invoice back to ``READY_FOR_REVIEW`` so the submit gesture can
  fire.
- ``reject(approval_id, actor_user_id, reason)`` — gates on the
  same roles, marks the row rejected, sets the invoice back to
  ``READY_FOR_REVIEW`` (re-requesting after a rejection creates a
  *new* row; the old one is immutable history).

Policy
------

We deliberately keep the policy simple in v1: ``none`` (default,
single-step), ``always`` (every invoice needs approval), or
``threshold`` (requires approval when ``grand_total >= threshold``).
Multi-step approval chains (Scale-tier + per-buyer / per-category
chains) are deferred — they share this row's structure and can
land later as a chain id + step number, without a schema break.

The submit endpoint must call ``invoice_requires_approval`` and
refuse to send to LHDN when an approval is needed but not on
file. That gate is the source of truth for the submission state
machine — we don't rely on the UI to do the right thing.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.identity.models import Organization, OrganizationMembership

from .models import ApprovalRequest, Invoice


class ApprovalError(Exception):
    """Raised when the approval gate refuses an action."""


# Roles that can decide an approval. Submitter is intentionally
# excluded — the whole point of two-step approval is that the
# submitter doesn't approve their own work.
APPROVER_ROLES: frozenset[str] = frozenset({"owner", "admin", "approver"})


def invoice_requires_approval(invoice: Invoice) -> bool:
    """True iff this invoice must pass through approval before submission."""
    org = Organization.objects.filter(id=invoice.organization_id).first()
    if org is None:
        return False
    policy = org.approval_policy or Organization.ApprovalPolicy.NONE
    if policy == Organization.ApprovalPolicy.NONE:
        return False
    if policy == Organization.ApprovalPolicy.ALWAYS:
        return True
    if policy == Organization.ApprovalPolicy.THRESHOLD:
        threshold = org.approval_threshold_amount
        if threshold is None:
            # Misconfiguration: threshold policy without a threshold.
            # Fail closed — better to demand approval than to silently
            # bypass the gate.
            return True
        amount = invoice.grand_total or Decimal("0")
        return amount >= threshold
    # Unknown policy value (future enum addition seen by an older
    # binary): fail closed.
    return True


def has_pending_approval(invoice: Invoice) -> bool:
    """Is there an outstanding approval request on this invoice?"""
    return ApprovalRequest.objects.filter(
        invoice=invoice, status=ApprovalRequest.Status.PENDING
    ).exists()


def has_active_approval(invoice: Invoice) -> bool:
    """Has the invoice been approved + the approval still applies?

    An approval is *active* until any field of the invoice changes
    in a way that would invalidate it. Re-validating after an edit
    re-opens the approval requirement — Slice 87 leaves that
    invalidation policy to a follow-up; for v1 the approval rides
    until the invoice is submitted or cancelled.
    """
    return ApprovalRequest.objects.filter(
        invoice=invoice, status=ApprovalRequest.Status.APPROVED
    ).exists()


def _can_decide(user_id: uuid.UUID | str, organization_id: uuid.UUID | str) -> bool:
    """True iff the user can approve / reject for this org."""
    return OrganizationMembership.objects.filter(
        user_id=user_id,
        organization_id=organization_id,
        is_active=True,
        role__name__in=APPROVER_ROLES,
    ).exists()


@transaction.atomic
def request_approval(
    *,
    invoice_id: uuid.UUID | str,
    actor_user_id: uuid.UUID | str,
    reason: str = "",
) -> ApprovalRequest:
    """Move an invoice into AWAITING_APPROVAL + create a pending request.

    Idempotent: calling it again while a pending request already
    exists returns that row (re-emitting an audit event is fine
    — operators sometimes click twice).
    """
    invoice = Invoice.objects.select_for_update().get(id=invoice_id)
    if invoice.status in {
        Invoice.Status.SUBMITTING,
        Invoice.Status.VALIDATED,
        Invoice.Status.CANCELLED,
    }:
        raise ApprovalError(f"Cannot request approval — invoice is in {invoice.status}.")

    existing = (
        ApprovalRequest.objects.filter(invoice=invoice, status=ApprovalRequest.Status.PENDING)
        .order_by("-requested_at")
        .first()
    )
    if existing is not None:
        return existing

    req = ApprovalRequest.objects.create(
        organization_id=invoice.organization_id,
        invoice=invoice,
        status=ApprovalRequest.Status.PENDING,
        requested_by_user_id=str(actor_user_id),
        requested_reason=(reason or "")[:2000],
    )

    if invoice.status != Invoice.Status.AWAITING_APPROVAL:
        invoice.status = Invoice.Status.AWAITING_APPROVAL
        invoice.save(update_fields=["status", "updated_at"])

    record_event(
        action_type="invoice.approval.requested",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(invoice.organization_id),
        affected_entity_type="Invoice",
        affected_entity_id=str(invoice.id),
        payload={
            "approval_id": str(req.id),
            "reason": (reason or "")[:255],
        },
    )
    return req


@transaction.atomic
def approve(
    *,
    approval_id: uuid.UUID | str,
    actor_user_id: uuid.UUID | str,
    note: str = "",
) -> ApprovalRequest:
    """Mark a pending approval as approved + unblock the invoice."""
    req = ApprovalRequest.objects.select_for_update().get(id=approval_id)
    if req.status != ApprovalRequest.Status.PENDING:
        raise ApprovalError(f"Approval is already in state {req.status}; cannot approve.")
    if not _can_decide(actor_user_id, req.organization_id):
        raise ApprovalError("You don't have permission to approve invoices.")
    if str(actor_user_id) == str(req.requested_by_user_id):
        # Two-step approval is meaningless if the requester can
        # also approve. Backend-enforced — the UI mirrors but the
        # gate lives here.
        raise ApprovalError("You can't approve your own request.")

    req.status = ApprovalRequest.Status.APPROVED
    req.decided_by_user_id = str(actor_user_id)
    req.decided_at = timezone.now()
    req.decision_note = (note or "")[:2000]
    req.save(
        update_fields=[
            "status",
            "decided_by_user_id",
            "decided_at",
            "decision_note",
            "updated_at",
        ]
    )

    invoice = req.invoice
    if invoice.status == Invoice.Status.AWAITING_APPROVAL:
        invoice.status = Invoice.Status.READY_FOR_REVIEW
        invoice.save(update_fields=["status", "updated_at"])

    record_event(
        action_type="invoice.approval.approved",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(invoice.organization_id),
        affected_entity_type="Invoice",
        affected_entity_id=str(invoice.id),
        payload={
            "approval_id": str(req.id),
            "requested_by": str(req.requested_by_user_id),
            "note_present": bool(note),
        },
    )
    return req


@transaction.atomic
def reject(
    *,
    approval_id: uuid.UUID | str,
    actor_user_id: uuid.UUID | str,
    reason: str = "",
) -> ApprovalRequest:
    """Mark a pending approval as rejected + send the invoice back."""
    req = ApprovalRequest.objects.select_for_update().get(id=approval_id)
    if req.status != ApprovalRequest.Status.PENDING:
        raise ApprovalError(f"Approval is already in state {req.status}; cannot reject.")
    if not _can_decide(actor_user_id, req.organization_id):
        raise ApprovalError("You don't have permission to reject invoices.")
    if str(actor_user_id) == str(req.requested_by_user_id):
        raise ApprovalError("You can't reject your own request.")

    req.status = ApprovalRequest.Status.REJECTED
    req.decided_by_user_id = str(actor_user_id)
    req.decided_at = timezone.now()
    req.decision_note = (reason or "")[:2000]
    req.save(
        update_fields=[
            "status",
            "decided_by_user_id",
            "decided_at",
            "decision_note",
            "updated_at",
        ]
    )

    invoice = req.invoice
    if invoice.status == Invoice.Status.AWAITING_APPROVAL:
        invoice.status = Invoice.Status.READY_FOR_REVIEW
        invoice.save(update_fields=["status", "updated_at"])

    record_event(
        action_type="invoice.approval.rejected",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(invoice.organization_id),
        affected_entity_type="Invoice",
        affected_entity_id=str(invoice.id),
        payload={
            "approval_id": str(req.id),
            "requested_by": str(req.requested_by_user_id),
            "reason": (reason or "")[:255],
        },
    )
    return req
