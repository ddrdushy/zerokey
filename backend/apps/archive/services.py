"""Archive services — append-only retention surface.

Cross-context callers go through these functions; they never import
the model directly. Designed for two main consumers:

  - submission/services on consolidated B2C invoice submit (one
    archive row per transaction, parent_invoice_id linking the rolled-
    up Invoice).
  - submission/services on Invoice state transitions (snapshot the
    Invoice as JSON for retention).

Append-only — no UPDATE / DELETE here. The retention sweeper marks
``deletion_pending=True`` separately; actual purge is a future
operations slice.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import record_event

from .models import ArchivedDocument

# Retention defaults per document type. LHDN requires 7 years on
# invoice records; ingestion sources we keep 1 year unless the
# customer customises (future).
_RETENTION_YEARS_BY_TYPE: dict[str, int] = {
    ArchivedDocument.DocumentType.B2C_TRANSACTION: 7,
    ArchivedDocument.DocumentType.INVOICE_SNAPSHOT: 7,
    ArchivedDocument.DocumentType.INGESTION_SOURCE: 1,
}


def archive_b2c_transaction(
    *,
    organization_id: uuid.UUID | str,
    parent_invoice_id: uuid.UUID | str,
    payload: dict[str, Any],
    archived_by_user_id: uuid.UUID | str | None = None,
) -> ArchivedDocument:
    """Archive one B2C transaction line behind a consolidated invoice.

    Called by ``submission`` when a customer issues a consolidated
    monthly B2C invoice — for each underlying transaction (typically
    one per receipt the customer never issued individual e-invoices
    for) we drop a row here so the audit trail can reconstruct the
    detail behind LHDN's summary line.
    """
    return _archive(
        organization_id=organization_id,
        document_type=ArchivedDocument.DocumentType.B2C_TRANSACTION,
        related_entity_type="Invoice",
        related_entity_id=str(parent_invoice_id),
        parent_invoice_id=parent_invoice_id,
        payload=payload,
        archived_by_user_id=archived_by_user_id,
    )


def archive_invoice_snapshot(
    *,
    organization_id: uuid.UUID | str,
    invoice_id: uuid.UUID | str,
    payload: dict[str, Any],
    archived_by_user_id: uuid.UUID | str | None = None,
) -> ArchivedDocument:
    """Snapshot a customer Invoice at a noteworthy state transition.

    Called by ``submission`` when an invoice flips to ``submitted``
    (or ``accepted`` once LHDN is wired). The full LHDN-shape JSON
    plus the customer's metadata at the moment of submission.
    """
    return _archive(
        organization_id=organization_id,
        document_type=ArchivedDocument.DocumentType.INVOICE_SNAPSHOT,
        related_entity_type="Invoice",
        related_entity_id=str(invoice_id),
        parent_invoice_id=None,
        payload=payload,
        archived_by_user_id=archived_by_user_id,
    )


def archive_ingestion_source(
    *,
    organization_id: uuid.UUID | str,
    ingestion_job_id: uuid.UUID | str,
    s3_object_key: str,
    file_mime_type: str,
    file_size: int,
    archived_by_user_id: uuid.UUID | str | None = None,
) -> ArchivedDocument:
    """Move an IngestionJob's source PDF into long-term archive.

    Used when a job ages out of the active ingestion window. The S3
    pointer + mime + size land in this row; the future sweeper can
    decide whether to keep the actual S3 object based on
    ``retain_until`` + ``deletion_pending``.
    """
    return _archive(
        organization_id=organization_id,
        document_type=ArchivedDocument.DocumentType.INGESTION_SOURCE,
        related_entity_type="IngestionJob",
        related_entity_id=str(ingestion_job_id),
        parent_invoice_id=None,
        payload={},
        s3_object_key=s3_object_key,
        file_mime_type=file_mime_type,
        file_size=file_size,
        archived_by_user_id=archived_by_user_id,
    )


def _archive(
    *,
    organization_id: uuid.UUID | str,
    document_type: str,
    related_entity_type: str,
    related_entity_id: str,
    parent_invoice_id: uuid.UUID | str | None,
    payload: dict[str, Any],
    s3_object_key: str = "",
    file_mime_type: str = "",
    file_size: int | None = None,
    archived_by_user_id: uuid.UUID | str | None = None,
) -> ArchivedDocument:
    years = _RETENTION_YEARS_BY_TYPE.get(document_type, 7)
    retain_until = timezone.now() + timedelta(days=365 * years)

    row = ArchivedDocument.objects.create(
        organization_id=organization_id,
        document_type=document_type,
        related_entity_type=related_entity_type[:64],
        related_entity_id=related_entity_id[:128],
        parent_invoice_id=parent_invoice_id,
        payload=payload or {},
        s3_object_key=s3_object_key[:512],
        file_mime_type=file_mime_type[:128],
        file_size=file_size,
        retain_until=retain_until,
        archived_by_user_id=archived_by_user_id,
    )

    record_event(
        action_type="archive.document_archived",
        actor_type=AuditEvent.ActorType.SERVICE
        if archived_by_user_id is None
        else AuditEvent.ActorType.USER,
        actor_id=str(archived_by_user_id) if archived_by_user_id else "archive.service",
        organization_id=str(organization_id),
        affected_entity_type="ArchivedDocument",
        affected_entity_id=str(row.id),
        payload={
            "document_type": document_type,
            "related_entity_type": related_entity_type,
            "related_entity_id": related_entity_id,
            "retention_years": years,
        },
    )
    return row


def list_for_invoice(
    *, organization_id: uuid.UUID | str, parent_invoice_id: uuid.UUID | str
) -> list[dict[str, Any]]:
    """Every archived row keyed to a consolidated invoice's UUID.

    Used by the customer-side audit / B2C-detail surface to prove the
    summary line was backed by N transactions. Tenant-scoped.
    """
    qs = ArchivedDocument.objects.filter(
        organization_id=organization_id,
        parent_invoice_id=parent_invoice_id,
    ).order_by("-archived_at")
    return [_to_dict(r) for r in qs]


def list_for_org(
    *,
    organization_id: uuid.UUID | str,
    document_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    qs = ArchivedDocument.objects.filter(organization_id=organization_id)
    if document_type:
        qs = qs.filter(document_type=document_type)
    return [_to_dict(r) for r in qs.order_by("-archived_at")[:limit]]


def _to_dict(row: ArchivedDocument) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "document_type": row.document_type,
        "related_entity_type": row.related_entity_type,
        "related_entity_id": row.related_entity_id,
        "parent_invoice_id": str(row.parent_invoice_id) if row.parent_invoice_id else None,
        "payload": row.payload,
        "s3_object_key": row.s3_object_key,
        "file_mime_type": row.file_mime_type,
        "file_size": int(row.file_size) if row.file_size is not None else None,
        "retain_until": row.retain_until.isoformat() if row.retain_until else None,
        "deletion_pending": bool(row.deletion_pending),
        "archived_at": row.archived_at.isoformat() if row.archived_at else None,
    }


# --- Slice 101: retention sweep (per-plan retention enforcement) ----------------


def sweep_expired_archives() -> dict[str, int]:
    """Mark ArchivedDocuments past ``retain_until`` as deletion_pending.

    PRD Domain 9 ("historical archive") + COMPLIANCE.md require a real
    retention enforcer — until this slice the ``retain_until`` column
    was set on insert but nothing read it back. This sweeper flips
    ``deletion_pending=True`` on rows past their date so a downstream
    destructive sweep + admin sign-off can purge.

    Idempotent: rows already flagged are skipped. Returns
    ``{flagged: int}`` so the audit chain shows what each run touched.
    """
    from .models import ArchivedDocument

    now = timezone.now()
    qs = ArchivedDocument.objects.filter(
        retain_until__lte=now,
        deletion_pending=False,
    )
    flagged_ids = list(qs.values_list("id", flat=True)[:1000])  # safety cap per run
    if not flagged_ids:
        return {"flagged": 0}

    updated = ArchivedDocument.objects.filter(id__in=flagged_ids).update(
        deletion_pending=True
    )

    record_event(
        action_type="archive.retention_sweep",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="archive.retention",
        organization_id=None,
        affected_entity_type="ArchivedDocument",
        affected_entity_id="",
        payload={"flagged": int(updated), "ids": [str(i) for i in flagged_ids]},
    )
    return {"flagged": int(updated)}
