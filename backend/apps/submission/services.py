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

from .models import ExceptionInboxItem, Invoice, LineItem

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
        return finalize_invoice_without_structuring(invoice=invoice, reason=str(exc))

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
        return finalize_invoice_without_structuring(invoice=invoice, reason=str(exc))
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
        return finalize_invoice_without_structuring(invoice=invoice, reason=f"{type(exc).__name__}: {exc}")

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

    # Enrich first (auto-fill blanks from CustomerMaster + ItemMaster), THEN
    # validate. Order matters: validation sees the post-enrichment field
    # set, so a master-filled buyer_address doesn't trip the
    # "buyer_address is required" warning the user would otherwise see.
    # Cross-context imports of services (not models) are allowed.
    from apps.enrichment.services import enrich_invoice
    from apps.validation.services import validate_invoice

    enrich_invoice(invoice.id)
    validation_result = validate_invoice(invoice.id)
    _sync_validation_inbox(invoice, validation_result)

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
def finalize_invoice_without_structuring(
    *, invoice: Invoice, reason: str
) -> StructuringResult:
    """Mark an Invoice ready-for-review without structured fields, then validate.

    Used when structuring can't run — adapter unavailable, no API key, or
    upstream extraction returned no text and no vision was applied. The
    user still gets a row to review, with validation issues surfacing
    every required-field gap so the UI is honest about what's missing.

    Public so the extraction context can call it directly when its
    pipeline reaches a state where the FieldStructure task should not
    be queued. Keep the cross-context import on services-only.
    """
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
    # Even with no structured fields the user benefits from a master pass
    # (in case the LLM left something extractable but the master has it
    # from a previous invoice) followed by validation, so the UI is
    # honest about what's missing after auto-fill.
    from apps.enrichment.services import enrich_invoice
    from apps.validation.services import validate_invoice

    enrich_invoice(invoice.id)
    validation_result = validate_invoice(invoice.id)
    _sync_validation_inbox(invoice, validation_result)
    # Structuring was skipped — the user should know. Open an inbox item
    # against this invoice for the "structuring_skipped" reason. The
    # detail carries the reason string so support can see why without
    # leaking PII.
    from .inbox import ensure_open

    ensure_open(
        invoice=invoice,
        reason=ExceptionInboxItem.Reason.STRUCTURING_SKIPPED,
        detail={"reason": reason[:255]},
    )

    return StructuringResult(invoice=invoice, line_count=0, overall_confidence=0.0, engine="")


# --- User corrections / update ----------------------------------------------------


# Header fields the user can correct from the review UI. Anything not in this
# set is ignored by ``update_invoice`` so an attacker can't flip the
# submission lifecycle (lhdn_uuid, status, etc.) via the PATCH endpoint.
EDITABLE_HEADER_FIELDS: frozenset[str] = frozenset(
    {
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
    }
)

# Buyer fields whose corrections propagate to the matched CustomerMaster.
# Map: invoice attribute -> master attribute. A user correction here is
# stronger evidence than the LLM's previous extraction OR the master's
# previous value, so the master learns from it. Same field set as
# enrichment._BUYER_FIELD_MAP but lives here to keep cross-context
# coupling to services-only.
_BUYER_TO_MASTER: tuple[tuple[str, str], ...] = (
    ("buyer_legal_name", "legal_name"),
    ("buyer_tin", "tin"),
    ("buyer_registration_number", "registration_number"),
    ("buyer_msic_code", "msic_code"),
    ("buyer_address", "address"),
    ("buyer_phone", "phone"),
    ("buyer_sst_number", "sst_number"),
    ("buyer_country_code", "country_code"),
)

# Line-item fields the user can correct. Same allowlist contract as the
# header set: anything outside is rejected. ``line_number`` is the
# stable identifier within an invoice; we never let the user renumber
# (that would invalidate the ItemMaster matching key alongside the
# invoice's audit history).
EDITABLE_LINE_FIELDS: frozenset[str] = frozenset(
    {
        "description",
        "unit_of_measurement",
        "quantity",
        "unit_price_excl_tax",
        "line_subtotal_excl_tax",
        "tax_type_code",
        "tax_rate",
        "tax_amount",
        "line_total_incl_tax",
        "classification_code",
        "discount_amount",
        "discount_reason_code",
    }
)

# Line-item fields whose corrections propagate to the matched ItemMaster.
# Map: LineItem attribute -> ItemMaster attribute. Same logic as the
# buyer-master map: user corrections are the strongest evidence, so the
# master learns from them. Quantity / price / tax_amount are NOT in this
# map — they're per-invoice values, not per-item patterns.
_LINE_TO_ITEM_MASTER: tuple[tuple[str, str], ...] = (
    ("classification_code", "default_classification_code"),
    ("tax_type_code", "default_tax_type_code"),
    ("unit_of_measurement", "default_unit_of_measurement"),
    ("unit_price_excl_tax", "default_unit_price_excl_tax"),
)


class InvoiceUpdateError(Exception):
    """Raised when an update can't be applied (unknown field, parse error)."""


@dataclass(frozen=True)
class InvoiceUpdateResult:
    invoice: Invoice
    changed_fields: list[str]
    changed_line_items: list[dict[str, Any]]


# The PATCH payload accepts header fields + an optional ``line_items``
# array. Each entry in the array MUST include ``line_number`` (the stable
# identifier within the invoice) and any subset of EDITABLE_LINE_FIELDS.
# We don't expose the database id of the LineItem to the front-end —
# line_number is unique within an invoice and is the natural addressing
# key in the UI.
_LINE_ITEMS_KEY = "line_items"


@transaction.atomic
def update_invoice(
    *,
    organization_id: UUID,
    invoice_id: UUID,
    updates: dict[str, Any],
    actor_user_id: UUID | str,
) -> InvoiceUpdateResult:
    """Apply user corrections to an Invoice (header + line items), re-enrich + re-validate.

    Tenant-scoped: the invoice must belong to ``organization_id`` or this
    raises ``Invoice.DoesNotExist``. Unknown / non-editable keys raise
    ``InvoiceUpdateError`` rather than being silently ignored — surface
    the contract violation so the front-end fixes the request.

    Side effects (in order):
      1. Apply edits to the invoice header.
      2. Apply edits to addressed line items (keyed by line_number).
      3. ``per_field_confidence`` for each changed header field flips to
         1.0; ``LineItem.per_field_confidence`` likewise for changed
         per-line cells.
      4. One ``invoice.updated`` audit event records changed header
         fields AND a per-line summary (line_number + changed field
         names, no values).
      5. Master propagation: changed buyer_* fields update the matched
         CustomerMaster; changed line-item code fields update the
         matched ItemMaster's defaults. The masters learn from
         corrections.
      6. Re-run ``enrich_invoice`` and ``validate_invoice`` so the
         response carries fresh issues for the corrected invoice.
    """
    line_items_payload = updates.pop(_LINE_ITEMS_KEY, None)

    unknown = set(updates.keys()) - EDITABLE_HEADER_FIELDS
    if unknown:
        raise InvoiceUpdateError(
            f"Cannot edit non-editable fields: {sorted(unknown)}. "
            f"Editable: {sorted(EDITABLE_HEADER_FIELDS)} (plus line_items)"
        )

    invoice = Invoice.objects.get(organization_id=organization_id, id=invoice_id)

    changed_header: list[str] = []
    for field_name, raw_value in updates.items():
        coerced = _coerce_field(invoice, field_name, raw_value)
        previous = getattr(invoice, field_name)
        if previous == coerced:
            continue
        setattr(invoice, field_name, coerced)
        changed_header.append(field_name)

    changed_lines = _apply_line_item_updates(invoice, line_items_payload)

    if not changed_header and not changed_lines:
        return InvoiceUpdateResult(
            invoice=invoice, changed_fields=[], changed_line_items=[]
        )

    if changed_header:
        confidence = dict(invoice.per_field_confidence or {})
        for field_name in changed_header:
            confidence[field_name] = 1.0
        invoice.per_field_confidence = confidence
        invoice.save()

    record_event(
        action_type="invoice.updated",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(invoice.organization_id),
        affected_entity_type="Invoice",
        affected_entity_id=str(invoice.id),
        payload={
            "changed_fields": sorted(changed_header),
            "changed_line_items": changed_lines,
        },
    )

    _propagate_corrections_to_master(invoice, changed_header)
    _propagate_line_corrections_to_item_master(invoice, changed_lines)

    # Re-enrich (master-fill any newly blanked fields, learn aliases),
    # then re-validate so the issue set reflects the corrected invoice.
    from apps.enrichment.services import enrich_invoice
    from apps.validation.services import validate_invoice

    enrich_invoice(invoice.id)
    validation_result = validate_invoice(invoice.id)
    _sync_validation_inbox(invoice, validation_result, actor_user_id=actor_user_id)

    invoice.refresh_from_db()
    return InvoiceUpdateResult(
        invoice=invoice,
        changed_fields=sorted(changed_header),
        changed_line_items=changed_lines,
    )


def _coerce_field(invoice: Invoice, field_name: str, raw_value: Any) -> Any:
    """Convert the JSON-shaped input to the model field's Python type."""
    # Decimals.
    if field_name in {"subtotal", "total_tax", "grand_total", "discount_amount"}:
        if raw_value in (None, ""):
            return None
        parsed = _parse_decimal(str(raw_value))
        if parsed is None:
            raise InvoiceUpdateError(
                f"{field_name!r} must be a decimal value (got {raw_value!r})."
            )
        return parsed
    # Dates.
    if field_name in {"issue_date", "due_date"}:
        if raw_value in (None, ""):
            return None
        parsed = _parse_date(str(raw_value))
        if parsed is None:
            raise InvoiceUpdateError(
                f"{field_name!r} must be ISO 8601 (YYYY-MM-DD) or DD/MM/YYYY (got {raw_value!r})."
            )
        return parsed
    # Strings — clip to the column's max_length per the model so a
    # too-long input fails in the API rather than silently truncating.
    if raw_value is None:
        return ""
    value = str(raw_value)
    field = invoice._meta.get_field(field_name)
    max_length = getattr(field, "max_length", None)
    if max_length is not None and len(value) > max_length:
        raise InvoiceUpdateError(
            f"{field_name!r} exceeds max length of {max_length} characters."
        )
    return value


def _propagate_corrections_to_master(invoice: Invoice, changed: list[str]) -> None:
    """Push user corrections of buyer fields into the matched CustomerMaster.

    The master learns from corrections — that's the point of the master.
    We don't create a master here; if this invoice has no matched master
    yet, ``enrich_invoice`` (called next) creates one and will pick up
    the corrected values. This function only runs if a master already
    exists for the buyer.

    Key handling: if the user corrected ``buyer_tin``, the new TIN may
    point to a different master. We do NOT migrate the old master's
    fields — that's a different operation. The next ``enrich_invoice``
    pass will pick the right master and create one if needed.
    """
    # Lazy import — cross-context service-only.
    from apps.enrichment.models import CustomerMaster

    buyer_changes = {
        invoice_field: master_field
        for invoice_field, master_field in _BUYER_TO_MASTER
        if invoice_field in changed
    }
    if not buyer_changes:
        return

    # Find the master by the (post-correction) TIN first; failing that, by
    # the (post-correction) legal name. Both handle the case where the user
    # just corrected one of those.
    master = None
    if invoice.buyer_tin:
        master = (
            CustomerMaster.objects.filter(
                organization_id=invoice.organization_id, tin=invoice.buyer_tin
            )
            .first()
        )
    if master is None and invoice.buyer_legal_name:
        master = (
            CustomerMaster.objects.filter(
                organization_id=invoice.organization_id,
                legal_name__iexact=invoice.buyer_legal_name,
            )
            .first()
        )
    if master is None:
        return  # The next enrich pass creates one.

    # If the user just renamed the buyer, file the old master name as an alias
    # before overwriting. That preserves history without polluting the
    # canonical name.
    if (
        "buyer_legal_name" in buyer_changes
        and invoice.buyer_legal_name != master.legal_name
        and master.legal_name not in master.aliases
    ):
        master.aliases = [*master.aliases, master.legal_name]

    for invoice_field, master_field in buyer_changes.items():
        new_value = getattr(invoice, invoice_field) or ""
        # User corrections OVERWRITE master values. This is the point of
        # the correction feedback loop: the LLM can be wrong, the LLM-fed
        # master can be wrong, the user is the source of truth.
        setattr(master, master_field, new_value)
    master.save()


def _apply_line_item_updates(
    invoice: Invoice, payload: Any
) -> list[dict[str, Any]]:
    """Apply user edits to LineItems addressed by ``line_number``.

    Returns a list of ``{line_number, changed_fields}`` records describing
    what changed — the audit-payload shape (no values, only field names).

    Validation rules:
      - ``payload`` must be a list of dicts (or absent / None).
      - Each dict must include an integer ``line_number``.
      - Every other key must be in ``EDITABLE_LINE_FIELDS``.
      - ``line_number`` must address an existing line on this invoice;
        unknown line numbers raise (creating new lines from a PATCH is
        out of scope until we have a real "add line" UI).
    """
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise InvoiceUpdateError(
            "'line_items' must be an array of {line_number, ...} objects."
        )

    by_number: dict[int, LineItem] = {
        line.line_number: line for line in invoice.line_items.all()
    }
    changed_summaries: list[dict[str, Any]] = []

    for entry in payload:
        if not isinstance(entry, dict):
            raise InvoiceUpdateError(
                "Each line_items entry must be an object with a line_number."
            )
        line_number = entry.get("line_number")
        if not isinstance(line_number, int):
            raise InvoiceUpdateError(
                f"line_items entry missing integer line_number: {entry!r}"
            )
        if line_number not in by_number:
            raise InvoiceUpdateError(
                f"line_items[{line_number}] does not exist on this invoice."
            )

        unknown_keys = set(entry.keys()) - {"line_number"} - EDITABLE_LINE_FIELDS
        if unknown_keys:
            raise InvoiceUpdateError(
                f"Cannot edit non-editable line fields: {sorted(unknown_keys)}. "
                f"Editable: {sorted(EDITABLE_LINE_FIELDS)}"
            )

        line = by_number[line_number]
        changed_for_line: list[str] = []
        for field_name, raw_value in entry.items():
            if field_name == "line_number":
                continue
            coerced = _coerce_line_field(line, field_name, raw_value)
            previous = getattr(line, field_name)
            if previous == coerced:
                continue
            setattr(line, field_name, coerced)
            changed_for_line.append(field_name)

        if not changed_for_line:
            continue

        # User-confirmed cells get the highest confidence band, same
        # convention as the header path.
        confidence = dict(line.per_field_confidence or {})
        for field_name in changed_for_line:
            confidence[field_name] = 1.0
        line.per_field_confidence = confidence
        line.save()

        changed_summaries.append(
            {
                "line_number": line_number,
                "changed_fields": sorted(changed_for_line),
            }
        )

    return changed_summaries


def _coerce_line_field(line: LineItem, field_name: str, raw_value: Any) -> Any:
    """Convert JSON input to the LineItem's Python type."""
    decimal_fields = {
        "quantity",
        "unit_price_excl_tax",
        "line_subtotal_excl_tax",
        "tax_rate",
        "tax_amount",
        "line_total_incl_tax",
        "discount_amount",
    }
    if field_name in decimal_fields:
        if raw_value in (None, ""):
            return None
        parsed = _parse_decimal(str(raw_value))
        if parsed is None:
            raise InvoiceUpdateError(
                f"line_items[*].{field_name!r} must be a decimal value (got {raw_value!r})."
            )
        return parsed

    # String-shaped fields: clip to max_length per the model so an
    # over-long input fails in the API rather than silently truncating.
    if raw_value is None:
        return ""
    value = str(raw_value)
    field = line._meta.get_field(field_name)
    max_length = getattr(field, "max_length", None)
    if max_length is not None and len(value) > max_length:
        raise InvoiceUpdateError(
            f"line_items[*].{field_name!r} exceeds max length of {max_length} characters."
        )
    return value


def _propagate_line_corrections_to_item_master(
    invoice: Invoice, changed_lines: list[dict[str, Any]]
) -> None:
    """Push user corrections on a line item into its matched ItemMaster.

    Same rule as the buyer-master path: user corrections OVERWRITE master
    defaults. Quantity / per-line tax amounts / etc. don't propagate —
    only the pattern-stable fields (classification / tax type / UOM /
    advisory unit price). The match key is the line description; if the
    description itself was edited we use the NEW description (the user
    has effectively renamed the item, and the next ``enrich_invoice``
    pass picks the right master and learns the alias).
    """
    if not changed_lines:
        return

    from apps.enrichment.models import ItemMaster

    by_number: dict[int, LineItem] = {
        line.line_number: line for line in invoice.line_items.all()
    }

    for summary in changed_lines:
        changed_fields = set(summary["changed_fields"])
        # Only run the master update when something pattern-stable
        # changed. Quantity-only edits don't need a master write.
        line_to_master = {
            line_field: master_field
            for line_field, master_field in _LINE_TO_ITEM_MASTER
            if line_field in changed_fields
        }
        if not line_to_master and "description" not in changed_fields:
            continue

        line = by_number.get(summary["line_number"])
        if line is None or not (line.description or "").strip():
            continue

        master = (
            ItemMaster.objects.filter(
                organization_id=invoice.organization_id,
                canonical_name__iexact=line.description.strip(),
            )
            .first()
        )
        if master is None:
            # No existing master for this description — the next
            # enrich_invoice pass will create one with the corrected
            # values, so there's nothing to do here.
            continue

        for line_field, master_field in line_to_master.items():
            new_value = getattr(line, line_field)
            # Don't overwrite a populated default with None / empty —
            # "user cleared the cell" is treated the same as "user left
            # it blank", and we already have a non-None default we know
            # works for this item.
            if new_value in (None, ""):
                continue
            setattr(master, master_field, new_value)
        master.save()


def _sync_validation_inbox(
    invoice: Invoice,
    validation_result: Any,
    *,
    actor_user_id: UUID | str | None = None,
) -> None:
    """Open / resolve the validation_failure inbox item per the result.

    Called from every code path that runs validation: the auto-pipeline
    after structuring, the no-structuring fallback, and the post-edit
    re-validate. The inbox row stays at most one per
    (invoice, validation_failure) reason — `ensure_open` handles the
    open-or-reopen logic; `resolve_for_reason` clears the row when the
    invoice goes clean.

    Detail payload carries codes only (no message text — codes are the
    audit-safe handle, same convention as the audit chain).
    """
    from .inbox import ensure_open, resolve_for_reason

    if validation_result.has_blocking_errors:
        ensure_open(
            invoice=invoice,
            reason=ExceptionInboxItem.Reason.VALIDATION_FAILURE,
            priority=ExceptionInboxItem.Priority.NORMAL,
            detail={
                "errors": validation_result.error_count,
                "warnings": validation_result.warning_count,
            },
        )
    else:
        resolve_for_reason(
            invoice=invoice,
            reason=ExceptionInboxItem.Reason.VALIDATION_FAILURE,
            note=(
                "auto-resolved on user re-validate"
                if actor_user_id
                else "auto-resolved on pipeline re-validate"
            ),
            actor_user_id=actor_user_id,
        )


def list_invoices_for_organization(
    *,
    organization_id: UUID,
    status: str | None = None,
    search: str | None = None,
    limit: int = 50,
    before_created_at: datetime | None = None,
) -> list[Invoice]:
    """All-invoices list for the active org's main Invoices route.

    Filters:
      - ``status``: exact match against ``Invoice.Status`` choices.
      - ``search``: case-insensitive substring against
        ``invoice_number`` OR ``buyer_legal_name`` OR ``buyer_tin``.
        The user's mental model on this surface is "find an invoice"
        and they don't always remember which field they're looking for.
      - ``before_created_at``: cursor pagination — each page is
        strictly older than the cursor.

    Newest-first by ``created_at`` (matches the customer's mental
    model: "what did I just upload?"). Bounded by ``limit`` (caller
    clamps).
    """
    qs = Invoice.objects.filter(organization_id=organization_id)
    if status:
        qs = qs.filter(status=status)
    if search:
        from django.db.models import Q

        target = search.strip()
        qs = qs.filter(
            Q(invoice_number__icontains=target)
            | Q(buyer_legal_name__icontains=target)
            | Q(buyer_tin__icontains=target)
        )
    if before_created_at is not None:
        qs = qs.filter(created_at__lt=before_created_at)
    return list(qs.order_by("-created_at")[:limit])


def count_invoices_for_organization(*, organization_id: UUID) -> int:
    """Total invoice count for the org. Renders as the list-page header context."""
    return Invoice.objects.filter(organization_id=organization_id).count()


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
