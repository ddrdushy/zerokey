"""Submission context — Invoice / LineItem creation and lifecycle.

The extraction context calls ``create_invoice_from_extraction`` once raw text
has been pulled from the document. We then call the FieldStructure adapter to
turn that text into LHDN-shape fields. Subsequent slices add validation,
signing, and the actual MyInvois submission.

The LHDN field schema we hand to the adapter is intentionally a *flat* string
list, not a JSON schema. Adapters return ``{field: value}`` plus per-field
confidence; this module owns the mapping from those strings onto
Invoice/LineItem columns.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import record_event

from .models import Invoice, LineItem

logger = logging.getLogger(__name__)


INVOICE_HEADER_FIELDS = [
    "invoice_number",
    "issue_date",
    "due_date",
    "currency_code",
    "payment_terms_code",
    "payment_reference",
    "supplier_legal_name",
    "supplier_tin",
    "supplier_registration_number",
    "supplier_msic_code",
    "supplier_address",
    "supplier_phone",
    "supplier_sst_number",
    "buyer_legal_name",
    "buyer_tin",
    "buyer_registration_number",
    "buyer_msic_code",
    "buyer_address",
    "buyer_phone",
    "buyer_sst_number",
    "buyer_country_code",
    "subtotal",
    "total_tax",
    "grand_total",
    "discount_amount",
    "discount_reason_code",
]

LINE_ITEMS_KEY = "line_items"
MAX_LINE_ITEMS = 30


@dataclass(frozen=True)
class StructuringResult:
    invoice: Invoice
    line_count: int
    overall_confidence: float
    engine: str


class StructuringError(Exception):
    """Raised when structuring fails for a non-recoverable reason."""


@transaction.atomic
def create_invoice_from_extraction(
    *,
    organization_id: UUID,
    ingestion_job_id: UUID,
    extracted_text: str,
) -> Invoice:
    """Create the Invoice row in ``extracting`` state. Idempotent on job_id."""
    existing = Invoice.objects.filter(ingestion_job_id=ingestion_job_id).first()
    if existing is not None:
        return existing

    invoice = Invoice.objects.create(
        organization_id=organization_id,
        ingestion_job_id=ingestion_job_id,
        status=Invoice.Status.EXTRACTING,
        raw_extracted_text=extracted_text,
    )
    record_event(
        action_type="invoice.created",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="extraction.pipeline",
        organization_id=str(organization_id),
        affected_entity_type="Invoice",
        affected_entity_id=str(invoice.id),
        payload={"ingestion_job_id": str(ingestion_job_id)},
    )
    return invoice


def structure_invoice(invoice_id: UUID | str) -> StructuringResult:
    """Run FieldStructure on the invoice's raw text and populate fields.

    On adapter unavailability (no API key) we mark the invoice
    ``ready_for_review`` with empty structured fields rather than failing —
    the user can hand-edit. The audit log records that auto-structuring
    was skipped so it is visible in ops dashboards.
    """
    # Lazy import to avoid extraction → submission cycle at module load.
    from apps.extraction.capabilities import EngineUnavailable
    from apps.extraction.models import Engine, EngineCall
    from apps.extraction.registry import get_adapter
    from apps.extraction.router import NoRouteFound, pick_engine

    invoice = Invoice.objects.get(id=invoice_id)

    try:
        decision = pick_engine(
            capability=Engine.Capability.FIELD_STRUCTURE,
            mime_type="text/plain",
        )
    except NoRouteFound as exc:
        return _finalize_without_structuring(invoice, reason=str(exc))

    target_schema = [*INVOICE_HEADER_FIELDS, LINE_ITEMS_KEY]
    started_at = timezone.now()
    started_perf = time.perf_counter()

    try:
        adapter = get_adapter(decision.engine.name)
        result = adapter.structure_fields(
            text=invoice.raw_extracted_text, target_schema=target_schema
        )
    except EngineUnavailable as exc:
        EngineCall.objects.create(
            engine=decision.engine,
            request_id=invoice.id,
            organization_id=invoice.organization_id,
            started_at=started_at,
            duration_ms=int((time.perf_counter() - started_perf) * 1000),
            outcome=EngineCall.Outcome.UNAVAILABLE,
            error_class=type(exc).__name__,
            cost_micros=0,
            confidence=None,
            diagnostics={"detail": str(exc)},
        )
        return _finalize_without_structuring(invoice, reason=str(exc))
    except Exception as exc:
        EngineCall.objects.create(
            engine=decision.engine,
            request_id=invoice.id,
            organization_id=invoice.organization_id,
            started_at=started_at,
            duration_ms=int((time.perf_counter() - started_perf) * 1000),
            outcome=EngineCall.Outcome.FAILURE,
            error_class=type(exc).__name__,
            cost_micros=0,
            confidence=None,
            diagnostics={"detail": str(exc)[:500]},
        )
        return _finalize_without_structuring(invoice, reason=f"{type(exc).__name__}: {exc}")

    EngineCall.objects.create(
        engine=decision.engine,
        request_id=invoice.id,
        organization_id=invoice.organization_id,
        started_at=started_at,
        duration_ms=int((time.perf_counter() - started_perf) * 1000),
        outcome=EngineCall.Outcome.SUCCESS,
        error_class="",
        cost_micros=result.cost_micros,
        confidence=result.overall_confidence,
        diagnostics=result.diagnostics,
    )

    return apply_structured_fields(
        invoice=invoice,
        engine_name=decision.engine.name,
        fields=result.fields,
        per_field_confidence=result.per_field_confidence,
        overall_confidence=result.overall_confidence,
    )


@transaction.atomic
def apply_structured_fields(
    *,
    invoice: Invoice,
    engine_name: str,
    fields: dict[str, str],
    per_field_confidence: dict[str, float],
    overall_confidence: float,
) -> StructuringResult:
    """Populate an Invoice from a StructuredExtractResult-shaped payload.

    Used both by ``structure_invoice`` (FieldStructure path: text → fields)
    and by the extraction context's vision-escalation path (vision adapter
    returns fields directly, skipping FieldStructure). The two paths
    converge here so the resulting Invoice + LineItem rows look identical
    regardless of which engine produced them.
    """
    for header in INVOICE_HEADER_FIELDS:
        value = fields.get(header, "")
        if not value:
            continue
        _set_invoice_field(invoice, header, value)

    invoice.structuring_engine = engine_name
    invoice.overall_confidence = overall_confidence
    invoice.per_field_confidence = {
        k: per_field_confidence.get(k, 0.0) for k in INVOICE_HEADER_FIELDS
    }
    invoice.status = Invoice.Status.READY_FOR_REVIEW
    invoice.save()

    line_count = _materialise_line_items(invoice, fields.get(LINE_ITEMS_KEY, ""))

    record_event(
        action_type="invoice.structured",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="extraction.pipeline",
        organization_id=str(invoice.organization_id),
        affected_entity_type="Invoice",
        affected_entity_id=str(invoice.id),
        payload={
            "engine": engine_name,
            "overall_confidence": str(overall_confidence),
            "line_items": line_count,
        },
    )

    # Run pre-flight validation now that the Invoice + LineItems are
    # populated. Cross-context import of services (not models) is allowed.
    # Inline rather than queued: the rule set is regex/arithmetic and runs
    # in milliseconds, and the review UI needs the issue list on the same
    # page-load that shows the structured fields.
    from apps.validation.services import validate_invoice

    validate_invoice(invoice.id)

    return StructuringResult(
        invoice=invoice,
        line_count=line_count,
        overall_confidence=overall_confidence,
        engine=engine_name,
    )


def _set_invoice_field(invoice: Invoice, field: str, value: str) -> None:
    if field in {"issue_date", "due_date"}:
        setattr(invoice, field, _parse_date(value))
    elif field in {"subtotal", "total_tax", "grand_total", "discount_amount"}:
        setattr(invoice, field, _parse_decimal(value))
    else:
        max_len = invoice._meta.get_field(field).max_length or 8192
        setattr(invoice, field, str(value)[:max_len])


def _parse_date(value: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_decimal(value: str) -> Decimal | None:
    cleaned = value.replace(",", "").replace("RM", "").replace("MYR", "").replace(" ", "").strip()
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _materialise_line_items(invoice: Invoice, raw: Any) -> int:
    """Parse a JSON array of line items from the structured payload."""
    if not raw:
        return 0
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return 0
    if not isinstance(parsed, list):
        return 0

    LineItem.objects.filter(invoice=invoice).delete()

    count = 0
    for index, raw_line in enumerate(parsed[:MAX_LINE_ITEMS], start=1):
        if not isinstance(raw_line, dict):
            continue
        LineItem.objects.create(
            organization_id=invoice.organization_id,
            invoice=invoice,
            line_number=index,
            description=str(raw_line.get("description", ""))[:8000],
            unit_of_measurement=str(raw_line.get("unit_of_measurement", ""))[:16],
            quantity=_parse_decimal(str(raw_line.get("quantity", ""))),
            unit_price_excl_tax=_parse_decimal(str(raw_line.get("unit_price_excl_tax", ""))),
            line_subtotal_excl_tax=_parse_decimal(str(raw_line.get("line_subtotal_excl_tax", ""))),
            tax_type_code=str(raw_line.get("tax_type_code", ""))[:16],
            tax_rate=_parse_decimal(str(raw_line.get("tax_rate", ""))),
            tax_amount=_parse_decimal(str(raw_line.get("tax_amount", ""))),
            line_total_incl_tax=_parse_decimal(str(raw_line.get("line_total_incl_tax", ""))),
            classification_code=str(raw_line.get("classification_code", ""))[:16],
        )
        count += 1
    return count


@transaction.atomic
def _finalize_without_structuring(invoice: Invoice, *, reason: str) -> StructuringResult:
    invoice.status = Invoice.Status.READY_FOR_REVIEW
    invoice.error_message = f"Auto-structuring skipped: {reason}"[:8000]
    invoice.save(update_fields=["status", "error_message", "updated_at"])
    record_event(
        action_type="invoice.structuring_skipped",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="extraction.pipeline",
        organization_id=str(invoice.organization_id),
        affected_entity_type="Invoice",
        affected_entity_id=str(invoice.id),
        payload={"reason": reason[:255]},
    )
    # Even with no structured fields the user still benefits from running
    # validation — the required-fields rule will flag the empty header so
    # the UI is honest about what's missing.
    from apps.validation.services import validate_invoice

    validate_invoice(invoice.id)

    return StructuringResult(invoice=invoice, line_count=0, overall_confidence=0.0, engine="")


def get_invoice_for_job(*, organization_id: UUID, ingestion_job_id: UUID) -> Invoice | None:
    return Invoice.objects.filter(
        organization_id=organization_id, ingestion_job_id=ingestion_job_id
    ).first()


def get_invoice(*, organization_id: UUID, invoice_id: UUID) -> Invoice | None:
    return (
        Invoice.objects.filter(organization_id=organization_id, id=invoice_id)
        .prefetch_related("line_items")
        .first()
    )
