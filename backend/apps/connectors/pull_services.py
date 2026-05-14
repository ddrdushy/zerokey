"""Phase 2 of PORTAL_PLAN.md — document pull orchestration.

Reads from each ``IntegrationConfig``, walks its adapter's
``fetch_documents()`` stream starting after the cursor, materialises
each yielded ``ConnectorDocument`` as an ``IngestionJob`` + ``Invoice``,
then advances the cursor. One transaction per document — if document
#37 fails to ingest, documents #1–36 stay committed and #37 surfaces
on the pull-result row for the operator to inspect.

This is the connector-side counterpart of the upload / email /
WhatsApp paths. Same downstream pipeline (``IngestionJob`` →
``Invoice``); auto-submit and validation gates land in Phase 3 on
top of what this produces.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.identity.tenancy import super_admin_context, tenant_context

from .adapters import get_adapter_class
from .documents import ConnectorDocument
from .models import ConnectorPullCursor, IntegrationConfig

logger = logging.getLogger(__name__)


# Map the ConnectorPullCursor.DocumentType + ConnectorDocument.document_type
# strings to the Invoice.InvoiceType code.
_DOCUMENT_TYPE_TO_INVOICE_TYPE = {
    "invoice": "standard",
    "credit_note": "credit_note",
    "debit_note": "debit_note",
}


class PullError(Exception):
    """Raised when a pull cannot proceed at all (connector unreachable,
    missing credentials, adapter not registered). A per-document
    failure does NOT raise — it is recorded in the result instead."""


@dataclass(frozen=True)
class PullResult:
    """One pull's outcome. Returned to the API caller and recorded
    on the cursor row."""

    document_type: str
    ingested_count: int
    skipped_count: int
    failed_count: int
    new_cursor: str
    error: str = ""


def pull_documents_for_connector(
    *,
    integration_config_id: uuid.UUID | str,
    document_type: str,
    csv_bytes: bytes | None = None,
) -> PullResult:
    """Pull every new document of ``document_type`` from a connector.

    Today the adapters we ship are CSV-driven, so the caller passes
    ``csv_bytes``. When ODBC / API adapters land, those construct
    themselves from ``IntegrationConfig.credentials`` and the
    ``csv_bytes`` parameter becomes optional. The contract on this
    function stays stable across that swap.
    """
    if document_type not in {
        ConnectorPullCursor.DocumentType.INVOICE,
        ConnectorPullCursor.DocumentType.CREDIT_NOTE,
        ConnectorPullCursor.DocumentType.DEBIT_NOTE,
    }:
        raise PullError(f"invalid document_type: {document_type!r}")

    with super_admin_context(reason="connectors.pull.load_config"):
        config = (
            IntegrationConfig.objects.filter(id=integration_config_id).first()
        )
    if config is None:
        raise PullError(f"IntegrationConfig {integration_config_id} not found.")

    AdapterClass = get_adapter_class(config.connector_type)
    if csv_bytes is None:
        raise PullError(
            f"Connector {config.connector_type} requires a CSV upload for this pull. "
            "Direct-connect adapters land later; today this is the upload path."
        )
    adapter = AdapterClass(csv_bytes=csv_bytes, target="documents")

    # Read (or initialise) the cursor for this connector + doc type.
    with super_admin_context(reason="connectors.pull.read_cursor"):
        cursor, _ = ConnectorPullCursor.objects.get_or_create(
            integration_config=config,
            document_type=document_type,
            defaults={"organization_id": config.organization_id},
        )

    ingested_count = 0
    skipped_count = 0
    failed_count = 0
    highest_ref_seen = cursor.last_external_ref or ""

    try:
        adapter.authenticate()
    except Exception as exc:  # noqa: BLE001 — surface upstream auth errors uniformly
        return _record_pull_outcome(
            cursor=cursor,
            organization_id=config.organization_id,
            document_type=document_type,
            ingested_count=0,
            skipped_count=0,
            failed_count=0,
            new_cursor=cursor.last_external_ref,
            error=f"authenticate: {type(exc).__name__}: {exc}",
            status="failed",
        )

    docs_iter = adapter.fetch_documents(
        document_type=document_type,
        after_external_ref=cursor.last_external_ref,
    )

    for doc in docs_iter:
        if doc.external_ref <= cursor.last_external_ref:
            # Adapter contract says "yield strictly after the cursor",
            # but defensive de-dup costs nothing.
            skipped_count += 1
            continue
        try:
            with tenant_context(config.organization_id):
                _ingest_one_document(
                    organization_id=config.organization_id,
                    config=config,
                    document=doc,
                )
            ingested_count += 1
            if doc.external_ref > highest_ref_seen:
                highest_ref_seen = doc.external_ref
        except Exception as exc:  # noqa: BLE001 — per-document failure is non-fatal
            logger.error(
                "connectors.pull.document_failed",
                extra={
                    "integration_config_id": str(config.id),
                    "external_ref": doc.external_ref,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            failed_count += 1

    return _record_pull_outcome(
        cursor=cursor,
        organization_id=config.organization_id,
        document_type=document_type,
        ingested_count=ingested_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        new_cursor=highest_ref_seen,
        error="",
        status="ok" if failed_count == 0 else "partial",
    )


def _ingest_one_document(
    *,
    organization_id: uuid.UUID | str,
    config: IntegrationConfig,
    document: ConnectorDocument,
) -> None:
    """Materialise one ConnectorDocument into IngestionJob + Invoice.

    Inside a transaction so a half-written invoice can't leak. The
    raw connector payload is preserved on the IngestionJob row so
    operators can re-process if the mapping needs adjustment later.
    """
    from apps.ingestion.models import IngestionJob
    from apps.submission.models import Invoice

    job_id = uuid.uuid4()
    invoice_type = _DOCUMENT_TYPE_TO_INVOICE_TYPE.get(document.document_type, "standard")
    now_iso = timezone.now().isoformat()

    raw_text = json.dumps({k: str(v) for k, v in document.raw_payload.items()}, indent=2)

    with transaction.atomic():
        job = IngestionJob.objects.create(
            id=job_id,
            organization_id=organization_id,
            source_channel=IngestionJob.SourceChannel.DATABASE_CONNECTOR,
            source_identifier=f"{config.connector_type}:{document.document_type}:{document.external_ref}",
            original_filename=(
                f"{config.connector_type}-{document.document_type}-{document.external_ref}.json"
            ),
            file_size=len(raw_text.encode("utf-8")),
            file_mime_type="application/json",
            s3_object_key="",  # connector-pulled, no file blob — payload lives on the job row
            status=IngestionJob.Status.READY_FOR_REVIEW,
            state_transitions=[
                {"status": IngestionJob.Status.RECEIVED.value, "at": now_iso},
                {"status": IngestionJob.Status.READY_FOR_REVIEW.value, "at": now_iso},
            ],
            extracted_text=raw_text,
            extraction_engine=f"connector:{config.connector_type}",
            extraction_confidence=1.0,
        )

        Invoice.objects.create(
            organization_id=organization_id,
            ingestion_job_id=job.id,
            invoice_type=invoice_type,
            status=Invoice.Status.READY_FOR_REVIEW,
            invoice_number=document.invoice_number,
            issue_date=document.issue_date,
            due_date=document.due_date,
            currency_code=document.currency_code,
            payment_terms_code=document.payment_terms_code,
            payment_reference=document.payment_reference,
            supplier_legal_name=document.supplier_legal_name,
            supplier_tin=document.supplier_tin,
            supplier_registration_number=document.supplier_registration_number,
            buyer_legal_name=document.buyer_legal_name,
            buyer_tin=document.buyer_tin,
            buyer_registration_number=document.buyer_registration_number,
            buyer_address=document.buyer_address,
            buyer_country_code=document.buyer_country_code,
            subtotal=document.subtotal,
            total_tax=document.total_tax,
            grand_total=document.grand_total,
            overall_confidence=1.0,
        )

    record_event(
        action_type="connectors.document.ingested",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="connectors.pull",
        organization_id=str(organization_id),
        affected_entity_type="IngestionJob",
        affected_entity_id=str(job_id),
        payload={
            "connector_type": config.connector_type,
            "document_type": document.document_type,
            "external_ref": document.external_ref,
            "invoice_number": document.invoice_number,
        },
    )


def _record_pull_outcome(
    *,
    cursor: ConnectorPullCursor,
    organization_id: uuid.UUID | str,
    document_type: str,
    ingested_count: int,
    skipped_count: int,
    failed_count: int,
    new_cursor: str,
    error: str,
    status: str,
) -> PullResult:
    """Update the cursor row + emit a top-level pull audit event."""
    with super_admin_context(reason="connectors.pull.record"):
        cursor.refresh_from_db()
        cursor.last_pulled_at = timezone.now()
        cursor.last_pull_status = status
        cursor.last_pull_count = ingested_count
        cursor.last_pull_error = error[:1000]
        if new_cursor:
            cursor.last_external_ref = new_cursor
        cursor.save(
            update_fields=[
                "last_pulled_at",
                "last_pull_status",
                "last_pull_count",
                "last_pull_error",
                "last_external_ref",
                "updated_at",
            ]
        )

    record_event(
        action_type="connectors.pull.completed",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="connectors.pull",
        organization_id=str(organization_id),
        affected_entity_type="IntegrationConfig",
        affected_entity_id=str(cursor.integration_config_id),
        payload={
            "document_type": document_type,
            "ingested_count": ingested_count,
            "skipped_count": skipped_count,
            "failed_count": failed_count,
            "status": status,
            "error": error[:255] if error else "",
        },
    )

    return PullResult(
        document_type=document_type,
        ingested_count=ingested_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        new_cursor=new_cursor,
        error=error,
    )
