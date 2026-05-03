"""Exception Inbox service surface.

The Inbox is a workflow queue: invoices flagged for human attention.
Items are auto-created when an invoice hits a "needs attention"
condition (validation failure, structuring skipped, low-confidence
extraction, LHDN rejection) and auto-resolved when the condition
clears (e.g. user fixes the validation issue and re-validates).

This module is the single entry point for everything inbox-related.
The pipeline contexts (validation, extraction) call ``ensure_open`` /
``resolve_for_reason`` from their hooks; the API layer calls
``list_open_for_organization`` / ``resolve_by_user``. Cross-context
imports of submission.models stay forbidden — call these helpers.

Why this lives in submission.inbox rather than submission.services:
the services module is already large enough that adding the inbox
surface inline would push it past the "one screen at a glance"
threshold. New module per cohesive function set.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import record_event

from .models import ExceptionInboxItem, Invoice

logger = logging.getLogger(__name__)


# --- Auto-management hooks (called by pipeline) -----------------------------


def ensure_open(
    *,
    invoice: Invoice,
    reason: str,
    priority: str = ExceptionInboxItem.Priority.NORMAL,
    detail: dict[str, Any] | None = None,
) -> ExceptionInboxItem:
    """Open or reopen an inbox item for ``(invoice, reason)``.

    Idempotent: a matching open row is updated in place (priority +
    detail refresh); a matching resolved row is reopened (status flips
    back to OPEN, resolved_* fields cleared); a missing row is created.
    Emits exactly one audit event per state transition — never on a
    redundant ensure call against an already-open row with no changes.
    """
    detail = detail or {}
    item, was_created = ExceptionInboxItem.objects.get_or_create(
        organization_id=invoice.organization_id,
        invoice=invoice,
        reason=reason,
        defaults={
            "priority": priority,
            "status": ExceptionInboxItem.Status.OPEN,
            "detail": detail,
        },
    )

    if was_created:
        _audit(invoice, item, "inbox.item_opened", payload={"reason": reason, "priority": priority})
        return item

    # Re-flap path: the row exists, possibly resolved.
    state_changed = False
    if item.status != ExceptionInboxItem.Status.OPEN:
        item.status = ExceptionInboxItem.Status.OPEN
        item.resolved_at = None
        item.resolved_by_user_id = None
        item.resolution_note = ""
        state_changed = True

    if item.priority != priority:
        item.priority = priority
        state_changed = True

    if detail and item.detail != detail:
        item.detail = detail
        state_changed = True

    if state_changed:
        item.save()
        _audit(
            invoice,
            item,
            "inbox.item_reopened",
            payload={"reason": reason, "priority": priority},
        )

    return item


def resolve_for_reason(
    *,
    invoice: Invoice,
    reason: str,
    note: str = "auto-resolved",
    actor_user_id: UUID | str | None = None,
) -> int:
    """Close every open inbox item on this invoice for the given reason.

    Returns the number of rows resolved. Used by the auto-resolve path:
    when validation re-runs and the prior errors are gone, the
    ``validation_failure`` row gets cleared.
    """
    qs = ExceptionInboxItem.objects.filter(
        organization_id=invoice.organization_id,
        invoice=invoice,
        reason=reason,
        status=ExceptionInboxItem.Status.OPEN,
    )
    items = list(qs)
    if not items:
        return 0

    now = timezone.now()
    for item in items:
        item.status = ExceptionInboxItem.Status.RESOLVED
        item.resolved_at = now
        item.resolved_by_user_id = actor_user_id
        item.resolution_note = note[:255]
        item.save()
        _audit(
            invoice,
            item,
            "inbox.item_resolved",
            payload={"reason": reason, "automatic": actor_user_id is None},
        )
    return len(items)


# --- Read + manual-action surface ------------------------------------------


def list_open_for_organization(
    *,
    organization_id: UUID | str,
    reason: str | None = None,
    limit: int = 100,
) -> list[ExceptionInboxItem]:
    """Open items for the org, newest first. Reason filter optional.

    The frontend Inbox table reads from this. Limit is a soft default
    (clamped at the view layer); inbox cardinality should stay small
    in normal operation, big numbers are themselves a signal.
    """
    qs = ExceptionInboxItem.objects.filter(
        organization_id=organization_id,
        status=ExceptionInboxItem.Status.OPEN,
    ).select_related("invoice")
    if reason:
        qs = qs.filter(reason=reason)
    return list(qs.order_by("-created_at")[:limit])


def count_open_for_organization(*, organization_id: UUID | str) -> int:
    return ExceptionInboxItem.objects.filter(
        organization_id=organization_id,
        status=ExceptionInboxItem.Status.OPEN,
    ).count()


@transaction.atomic
def resolve_by_user(
    *,
    organization_id: UUID | str,
    item_id: UUID | str,
    actor_user_id: UUID | str,
    note: str = "",
) -> ExceptionInboxItem:
    """User clicks "Mark resolved". Manual close, audited with the actor."""
    item = ExceptionInboxItem.objects.select_related("invoice").get(
        organization_id=organization_id, id=item_id
    )
    if item.status == ExceptionInboxItem.Status.RESOLVED:
        # Idempotent: already resolved, no-op.
        return item

    item.status = ExceptionInboxItem.Status.RESOLVED
    item.resolved_at = timezone.now()
    item.resolved_by_user_id = actor_user_id
    item.resolution_note = (note or "manually resolved")[:255]
    item.save()

    _audit(
        item.invoice,
        item,
        "inbox.item_resolved",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        payload={"reason": item.reason, "automatic": False},
    )
    return item


# --- internal --------------------------------------------------------------


def _audit(
    invoice: Invoice,
    item: ExceptionInboxItem,
    action_type: str,
    *,
    actor_type: str = AuditEvent.ActorType.SERVICE,
    actor_id: str = "submission.inbox",
    payload: dict[str, Any] | None = None,
) -> None:
    record_event(
        action_type=action_type,
        actor_type=actor_type,
        actor_id=actor_id,
        organization_id=str(invoice.organization_id),
        affected_entity_type="ExceptionInboxItem",
        affected_entity_id=str(item.id),
        payload={"invoice_id": str(invoice.id), **(payload or {})},
    )


# --- Slice 101: batch validation summary ---------------------------------------


def batch_summary(*, organization_id: UUID | str) -> dict[str, int | dict[str, int]]:
    """Per-org snapshot for the inbox batch summary panel.

    PRD Domain 4 ("batch validation summary"): "When a batch of
    invoices is uploaded, the dashboard surfaces a summary: how many
    passed pre-flight, how many need attention, what the most common
    errors are. The user fixes errors in a single review pass rather
    than per-invoice."

    Cheap aggregation — three queries against existing rows, no new
    table. Reads:
      - ``inbox_open_total``         currently open inbox items
      - ``inbox_open_by_reason``     {reason → count}
      - ``invoices_validated_today`` invoices that hit ``ready_for_review``
                                      with no blocking issues today
      - ``invoices_needing_review``   invoices in READY_FOR_REVIEW
                                      with at least one error severity
    """
    from datetime import timedelta

    from django.db.models import Count
    from django.utils import timezone as _tz

    from apps.submission.models import Invoice
    from apps.validation.models import ValidationIssue

    today_start = _tz.now() - timedelta(hours=24)

    inbox_total = ExceptionInboxItem.objects.filter(
        organization_id=organization_id,
        status=ExceptionInboxItem.Status.OPEN,
    ).count()

    by_reason = dict(
        ExceptionInboxItem.objects.filter(
            organization_id=organization_id,
            status=ExceptionInboxItem.Status.OPEN,
        )
        .values_list("reason")
        .annotate(c=Count("id"))
    )

    # Validated in the last 24h = invoices that landed ready_for_review
    # recently AND have no validation errors. Rough proxy for "passed
    # pre-flight" since LHDN-validated submissions also imply passed.
    invoice_ids_with_errors = set(
        ValidationIssue.objects.filter(
            organization_id=organization_id,
            severity="error",
        )
        .values_list("invoice_id", flat=True)
        .distinct()
    )

    recent_invoices = list(
        Invoice.objects.filter(
            organization_id=organization_id,
            updated_at__gte=today_start,
        ).values_list("id", "status")
    )
    passed_today = sum(
        1
        for (inv_id, st) in recent_invoices
        if st in {"ready_for_review", "validated"} and inv_id not in invoice_ids_with_errors
    )

    needs_review = Invoice.objects.filter(
        organization_id=organization_id,
        status="ready_for_review",
        id__in=list(invoice_ids_with_errors),
    ).count()

    # Top-3 most common validation error codes — useful for the
    # "fix all of these in one pass" framing.
    top_codes = list(
        ValidationIssue.objects.filter(
            organization_id=organization_id,
            severity__in=["error", "warning"],
        )
        .values_list("code")
        .annotate(c=Count("id"))
        .order_by("-c")[:3]
    )

    return {
        "inbox_open_total": int(inbox_total),
        "inbox_open_by_reason": {str(r): int(c) for r, c in by_reason.items()},
        "passed_today": int(passed_today),
        "needs_review": int(needs_review),
        "top_error_codes": [
            {"code": str(code), "count": int(count)} for code, count in top_codes
        ],
    }
