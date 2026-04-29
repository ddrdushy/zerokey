"""CSV exports for submission data + audit log (Slice 88).

Two surfaces:

  1. ``stream_invoices_csv(*, organization_id, since, until, status)``
     — yields the customer's submission stream as CSV rows.
     Bookkeepers use this for monthly reconciliation against
     their accounting system.

  2. ``stream_audit_csv(*, organization_id, since, until,
     action_type, actor_id)`` — yields the audit log as CSV rows
     with the chain hashes hex-encoded so a downstream verifier
     can re-run integrity checks on the export.

Both functions are generators so the response can stream — a
year of an active customer's audit log is too large to buffer
in memory. The view layer wraps them in a
``StreamingHttpResponse``.

The exports are themselves audit-logged (
``submission.export.invoices``, ``audit.export.events``) per
PRODUCT_REQUIREMENTS.md Domain 9 ("Export operations are
themselves audit-logged").
"""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Iterator
from datetime import datetime

from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import record_event

from .models import Invoice

# Field set for the invoice export. Keep this list explicit (not
# auto-derived from the model) so adding a model field doesn't
# silently change the export contract.
INVOICE_EXPORT_COLUMNS: list[str] = [
    "invoice_id",
    "invoice_number",
    "issue_date",
    "due_date",
    "status",
    "currency_code",
    "subtotal",
    "total_tax",
    "grand_total",
    "supplier_legal_name",
    "supplier_tin",
    "buyer_legal_name",
    "buyer_tin",
    "buyer_address",
    "lhdn_uuid",
    "submission_uid",
    "validation_timestamp",
    "cancellation_timestamp",
    "created_at",
    "updated_at",
]


AUDIT_EXPORT_COLUMNS: list[str] = [
    "sequence",
    "timestamp",
    "action_type",
    "actor_type",
    "actor_id",
    "affected_entity_type",
    "affected_entity_id",
    "payload_json",
    # Hex-encoded so the export is text-only + the verifier can
    # re-derive the chain by comparing these against its own
    # recomputed hashes.
    "content_hash_hex",
    "chain_hash_hex",
]


def _csv_row(values: list) -> str:
    """Render a single CSV row, returning the encoded bytes as text."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(values)
    return buf.getvalue()


def stream_invoices_csv(
    *,
    organization_id: uuid.UUID | str,
    since: datetime | None = None,
    until: datetime | None = None,
    status: str | None = None,
    actor_user_id: uuid.UUID | str | None = None,
) -> Iterator[str]:
    """Yield CSV rows for the customer's submission stream.

    Filters are intersected (AND): if both ``since`` and ``status``
    are set, only invoices in the date window with that status
    appear. Order is most-recent first.
    """
    yield _csv_row(INVOICE_EXPORT_COLUMNS)

    qs = Invoice.objects.filter(organization_id=organization_id).order_by("-created_at")
    if since is not None:
        qs = qs.filter(created_at__gte=since)
    if until is not None:
        qs = qs.filter(created_at__lte=until)
    if status:
        qs = qs.filter(status=status)

    count = 0
    for invoice in qs.iterator(chunk_size=500):
        row = []
        for column in INVOICE_EXPORT_COLUMNS:
            value = getattr(invoice, column, "")
            if column == "invoice_id":
                value = str(invoice.id)
            elif isinstance(value, datetime):
                value = value.isoformat()
            elif value is None:
                value = ""
            row.append(str(value))
        yield _csv_row(row)
        count += 1

    record_event(
        action_type="submission.export.invoices",
        actor_type=AuditEvent.ActorType.USER if actor_user_id else AuditEvent.ActorType.SERVICE,
        actor_id=str(actor_user_id) if actor_user_id else "submission.export",
        organization_id=str(organization_id),
        affected_entity_type="Invoice",
        affected_entity_id="",
        payload={
            "row_count": count,
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
            "status_filter": status or None,
        },
    )


def stream_audit_csv(
    *,
    organization_id: uuid.UUID | str,
    since: datetime | None = None,
    until: datetime | None = None,
    action_type: str | None = None,
    actor_id: str | None = None,
    requested_by_user_id: uuid.UUID | str | None = None,
) -> Iterator[str]:
    """Yield CSV rows for the customer's audit chain.

    Hash columns are hex-encoded so the file stays text-only and
    a downstream verifier can compare against its recomputed
    digests.
    """
    import json

    yield _csv_row(AUDIT_EXPORT_COLUMNS)

    qs = AuditEvent.objects.filter(organization_id=organization_id).order_by("sequence")
    if since is not None:
        qs = qs.filter(timestamp__gte=since)
    if until is not None:
        qs = qs.filter(timestamp__lte=until)
    if action_type:
        qs = qs.filter(action_type=action_type)
    if actor_id:
        qs = qs.filter(actor_id=actor_id)

    count = 0
    for event in qs.iterator(chunk_size=500):
        row = [
            event.sequence,
            event.timestamp.isoformat(),
            event.action_type,
            event.actor_type,
            event.actor_id,
            event.affected_entity_type,
            event.affected_entity_id,
            json.dumps(event.payload, separators=(",", ":")),
            event.content_hash.hex() if event.content_hash else "",
            event.chain_hash.hex() if event.chain_hash else "",
        ]
        yield _csv_row(row)
        count += 1

    record_event(
        action_type="audit.export.events",
        actor_type=AuditEvent.ActorType.USER
        if requested_by_user_id
        else AuditEvent.ActorType.SERVICE,
        actor_id=str(requested_by_user_id) if requested_by_user_id else "audit.export",
        organization_id=str(organization_id),
        affected_entity_type="AuditEvent",
        affected_entity_id="",
        payload={
            "row_count": count,
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
            "action_type_filter": action_type or None,
            "actor_filter": actor_id or None,
        },
    )


def parse_iso_or_400(raw: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp; return ``None`` if input is empty.

    Raises ``ValueError`` on malformed input — the caller turns
    that into a 400.
    """
    if raw is None or raw == "":
        return None
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        # Treat naive timestamps as UTC for filter purposes; the
        # accountant likely typed a local-tz string but the export
        # is bounded by UTC stored timestamps anyway.
        parsed = parsed.replace(tzinfo=timezone.get_current_timezone())
    return parsed
