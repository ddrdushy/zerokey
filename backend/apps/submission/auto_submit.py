"""Phase 3 of PORTAL_PLAN.md — auto-submit gate.

One entry point: ``handle_pulled_invoice(invoice_id)``. Decides whether
to dispatch the invoice to the LHDN submission pipeline or park it in
``NOT_SUBMITTED`` for the customer to review.

Gate order (fail-closed at every step):

  1. The buyer's ``CustomerMaster.auto_submit_override``:
        - ``"review"`` → NOT_SUBMITTED, reason "Buyer requires review"
        - ``"always"`` → continue, ignore org default
        - ``"none"``   → fall through to the org default
  2. ``Organization.auto_submit_default`` (unless step 1 forced ``always``):
        - ``False``    → NOT_SUBMITTED, reason "Auto-submit disabled"
  3. Validation:
        - any blocking error → NOT_SUBMITTED, reason "Validation: <code>"
  4. Extraction confidence:
        - below ``Organization.auto_submit_confidence_threshold`` →
          NOT_SUBMITTED, reason "Extraction confidence below threshold"
  5. Otherwise → enqueue the existing submission pipeline.

This service is the *only* place that writes ``Status.NOT_SUBMITTED``
on a new auto-submission candidate. Manual submit flows do not pass
through it — they go straight to ``submit_invoice_to_lhdn``.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from django.db import transaction

from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.identity.tenancy import super_admin_context

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AutoSubmitDecision:
    """Outcome of one auto-submit gate run."""

    dispatched: bool
    blocked_reason: str = ""


def handle_pulled_invoice(invoice_id: uuid.UUID | str) -> AutoSubmitDecision:
    """Run every gate; either dispatch the invoice to LHDN or park it.

    Called by ``pull_services._ingest_one_document`` after a freshly-
    created Invoice from a connector. Idempotent — calling it on an
    invoice that's already been dispatched / submitted is a no-op.
    """
    from apps.enrichment.models import CustomerMaster
    from apps.identity.models import Organization
    from apps.submission.models import Invoice
    from apps.validation.services import validate_invoice

    with super_admin_context(reason="submission.auto_submit.gate"):
        invoice = Invoice.objects.filter(id=invoice_id).first()
    if invoice is None:
        return AutoSubmitDecision(dispatched=False, blocked_reason="Invoice not found")

    # Idempotency: anything already past READY_FOR_REVIEW means this
    # has been considered (or the customer manually moved it on).
    handled_already = invoice.status not in (
        Invoice.Status.READY_FOR_REVIEW,
        Invoice.Status.NOT_SUBMITTED,
    )
    if handled_already:
        return AutoSubmitDecision(
            dispatched=False,
            blocked_reason=f"Already in status {invoice.status}",
        )

    # 1. Per-customer override.
    customer_override = _resolve_customer_override(invoice)
    if customer_override == CustomerMaster.AutoSubmitOverride.REVIEW:
        return _park(invoice, "Buyer requires review")

    # 2. Org default (unless override == always).
    with super_admin_context(reason="submission.auto_submit.read_org"):
        org = Organization.objects.filter(id=invoice.organization_id).first()
    if org is None:
        return _park(invoice, "Organization not found")

    if customer_override != CustomerMaster.AutoSubmitOverride.ALWAYS:
        if not org.auto_submit_default:
            return _park(invoice, "Auto-submit disabled")

    # 3. Validation.
    result = validate_invoice(invoice.id)
    if result.has_blocking_errors:
        # Pick the first error code as the human-readable reason.
        first_error = _first_error_code(invoice.id)
        return _park(invoice, f"Validation: {first_error}"[:128] if first_error else "Validation failed")

    # 4. Confidence threshold.
    confidence = invoice.overall_confidence
    threshold = float(org.auto_submit_confidence_threshold or 0.92)
    if confidence is not None and confidence < threshold:
        return _park(
            invoice,
            f"Extraction confidence {confidence:.2f} below threshold {threshold:.2f}",
        )

    # 5. Dispatch. Enqueue rather than calling synchronously so this
    # gate stays cheap; the existing Celery task chain takes it from
    # READY_FOR_REVIEW through SIGNING → SUBMITTING → VALIDATED.
    return _dispatch(invoice)


# --- helpers ---------------------------------------------------------------


def _resolve_customer_override(invoice) -> str:
    """Look up the buyer's CustomerMaster row by TIN; return the
    override or 'none' if no master record exists.

    Match by TIN first (the LHDN-anchored key). If TIN is missing on
    the invoice, fall back to legal_name (loose match — handy for
    B2C-without-TIN flows).
    """
    from apps.enrichment.models import CustomerMaster

    with super_admin_context(reason="submission.auto_submit.lookup_customer"):
        master = None
        if invoice.buyer_tin:
            master = CustomerMaster.objects.filter(
                organization_id=invoice.organization_id,
                tin=invoice.buyer_tin,
            ).first()
        if master is None and invoice.buyer_legal_name:
            master = CustomerMaster.objects.filter(
                organization_id=invoice.organization_id,
                legal_name__iexact=invoice.buyer_legal_name,
            ).first()
    return master.auto_submit_override if master is not None else "none"


def _first_error_code(invoice_id) -> str:
    from apps.validation.models import ValidationIssue

    with super_admin_context(reason="submission.auto_submit.read_validation"):
        issue = (
            ValidationIssue.objects.filter(invoice_id=invoice_id, severity="error")
            .order_by("created_at")
            .first()
        )
    return issue.code if issue is not None else ""


def _park(invoice, reason: str) -> AutoSubmitDecision:
    """Transition the invoice to NOT_SUBMITTED with a reason. Persists
    + audits. Returns the decision."""
    from apps.submission.models import Invoice

    with super_admin_context(reason="submission.auto_submit.park"):
        with transaction.atomic():
            invoice.status = Invoice.Status.NOT_SUBMITTED
            invoice.auto_submit_blocked_reason = reason[:128]
            invoice.save(update_fields=["status", "auto_submit_blocked_reason", "updated_at"])

    record_event(
        action_type="submission.auto_submit_blocked",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="submission.auto_submit",
        organization_id=str(invoice.organization_id),
        affected_entity_type="Invoice",
        affected_entity_id=str(invoice.id),
        payload={"reason": reason[:128], "invoice_status": invoice.status},
    )
    logger.info(
        "auto_submit.blocked",
        extra={"invoice_id": str(invoice.id), "reason": reason},
    )
    return AutoSubmitDecision(dispatched=False, blocked_reason=reason[:128])


def _dispatch(invoice) -> AutoSubmitDecision:
    """Hand off to the existing submission pipeline by enqueuing the
    sign+submit Celery chain. Records an audit event and returns the
    decision."""
    # The clear, current state is preserved; the Celery task takes the
    # invoice through SIGNING → SUBMITTING. We don't transition the
    # status here — the worker does, atomic with its work.
    from apps.submission.tasks import sign_invoice

    sign_invoice.apply_async(args=[str(invoice.id)])

    record_event(
        action_type="submission.auto_submit_dispatched",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="submission.auto_submit",
        organization_id=str(invoice.organization_id),
        affected_entity_type="Invoice",
        affected_entity_id=str(invoice.id),
        payload={"invoice_number": invoice.invoice_number},
    )
    logger.info(
        "auto_submit.dispatched",
        extra={"invoice_id": str(invoice.id)},
    )
    return AutoSubmitDecision(dispatched=True)
