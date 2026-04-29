"""Issue Credit Notes / Debit Notes / Refund Notes against a
LHDN-validated invoice (Slice 61).

LHDN MyInvois requires that any amendment to an issued invoice
goes through the corresponding amendment document type — we cannot
re-edit a Valid invoice. The four amendment types are:

  - **Credit Note (02)** — reduces the value of an issued invoice.
    Common case: refund, return, discount applied after issue.
  - **Debit Note (03)** — adds value to an issued invoice. Common
    case: late penalty, additional charge.
  - **Refund Note (04)** — confirms a refund payment back to the
    buyer. Used after the credit-note step in some workflows.

Each carries:
  - InvoiceTypeCode = 02 / 03 / 04 (Slice 60 mapping)
  - BillingReference pointing back at the original invoice's
    LHDN UUID + internal ID (enforced by Slice 60's
    TYPES_REQUIRING_BILLING_REFERENCE check at JSON build time)
  - Adjustment reason (human-readable, surfaced on the LHDN
    portal)

The new amendment Invoice row is created in
``Status.READY_FOR_REVIEW``: the user can edit line items / amounts
in the standard review screen + then click Submit to LHDN to
clear it. From LHDN's perspective the amendment is a fresh
document (new UUID); the BillingReference link is what makes
it visible as an amendment on the original.

Today the implementation supports CN; DN + RN follow the same
shape and are easy to add when needed.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import record_event

from .models import Invoice, LineItem


class AmendmentError(Exception):
    """Raised when an amendment can't be created."""


# Per-amendment-type config. Each entry maps the public function
# to its target invoice_type, number suffix, audit action_type,
# and noun for error messages.
_AMENDMENT_CONFIGS: dict[str, dict[str, str]] = {
    "credit_note": {
        "type": "credit_note",
        "suffix": "CN",
        "noun": "credit note",
        "audit": "submission.amendment.credit_note_created",
        "lines_field": "lines_credited",
    },
    "debit_note": {
        "type": "debit_note",
        "suffix": "DN",
        "noun": "debit note",
        "audit": "submission.amendment.debit_note_created",
        "lines_field": "lines_charged",
    },
    "refund_note": {
        "type": "refund_note",
        "suffix": "RN",
        "noun": "refund note",
        "audit": "submission.amendment.refund_note_created",
        "lines_field": "lines_refunded",
    },
}


@transaction.atomic
def _create_amendment(
    *,
    config: dict[str, str],
    source_invoice_id: uuid.UUID | str,
    reason: str,
    actor_user_id: uuid.UUID | str,
    line_adjustments: list[dict[str, Any]] | None = None,
) -> Invoice:
    """Shared core for creating any LHDN amendment document.

    ``config`` selects the invoice type, number suffix, audit
    action, and noun used in error messages. The structural shape
    is identical across CN / DN / RN — only the type code +
    legal interpretation differ. LHDN's BillingReference contract
    is the same for all three.

    ``source_invoice_id`` must point at an Invoice in
    ``Status.VALIDATED`` with a populated ``lhdn_uuid``. LHDN
    refuses amendments against unsubmitted documents — the
    BillingReference needs a real LHDN-issued UUID to link to.

    ``line_adjustments`` is optional. When omitted, the amendment
    copies every line item from the source 1:1 (full
    credit/charge/refund). When provided, it's a list of
    ``{"line_number", "quantity", "amount"}`` dicts — one per
    line being amended. Lines not listed are excluded.

    ``reason`` is required + lands in ``adjustment_reason``,
    which the JSON generator emits as the document-level
    ``Note``. Surfaced in MyInvois's portal so the buyer can
    see why the amendment was issued.
    """
    noun = config["noun"]
    if not reason or not reason.strip():
        raise AmendmentError(f"A reason is required for a {noun}.")

    source = Invoice.objects.filter(id=source_invoice_id).first()
    if source is None:
        raise AmendmentError(f"Source invoice {source_invoice_id} not found.")

    if source.status != Invoice.Status.VALIDATED:
        raise AmendmentError(
            f"Source invoice must be Validated by LHDN before a {noun} "
            f"can be issued (current status: {source.status})."
        )
    if not source.lhdn_uuid:
        raise AmendmentError(
            f"Source invoice has no LHDN UUID — {noun}s require "
            f"the original invoice's LHDN-issued UUID."
        )

    # Number pattern <orig>-CN-NN / -DN-NN / -RN-NN. Sequence is
    # scoped per (source UUID, target type) so multiple amendments
    # of the same kind coexist with their own counter.
    target_type = config["type"]
    sibling_count = Invoice.objects.filter(
        organization_id=source.organization_id,
        original_invoice_uuid=source.lhdn_uuid,
        invoice_type=target_type,
    ).count()
    new_number = f"{source.invoice_number}-{config['suffix']}-{sibling_count + 1:02d}"

    # Build the new Invoice row by copying the source's header
    # fields. Fresh UUID + ingestion_job_id (amendments aren't
    # tied to an ingested PDF).
    new_inv = Invoice.objects.create(
        organization_id=source.organization_id,
        ingestion_job_id=uuid.uuid4(),
        invoice_number=new_number,
        issue_date=timezone.now().date(),
        due_date=source.due_date,
        currency_code=source.currency_code,
        invoice_type=target_type,
        original_invoice_uuid=source.lhdn_uuid,
        original_invoice_internal_id=source.invoice_number,
        adjustment_reason=reason.strip(),
        supplier_legal_name=source.supplier_legal_name,
        supplier_tin=source.supplier_tin,
        supplier_registration_number=source.supplier_registration_number,
        supplier_msic_code=source.supplier_msic_code,
        supplier_address=source.supplier_address,
        supplier_phone=source.supplier_phone,
        supplier_sst_number=source.supplier_sst_number,
        supplier_id_type=source.supplier_id_type,
        supplier_id_value=source.supplier_id_value,
        buyer_legal_name=source.buyer_legal_name,
        buyer_tin=source.buyer_tin,
        buyer_registration_number=source.buyer_registration_number,
        buyer_msic_code=source.buyer_msic_code,
        buyer_address=source.buyer_address,
        buyer_phone=source.buyer_phone,
        buyer_sst_number=source.buyer_sst_number,
        buyer_country_code=source.buyer_country_code,
        buyer_id_type=source.buyer_id_type,
        buyer_id_value=source.buyer_id_value,
        subtotal=source.subtotal,
        total_tax=source.total_tax,
        grand_total=source.grand_total,
        status=Invoice.Status.READY_FOR_REVIEW,
    )

    # Copy / adjust line items.
    source_lines = list(source.line_items.all().order_by("line_number"))
    adjustments_by_line = (
        {a["line_number"]: a for a in (line_adjustments or [])} if line_adjustments else None
    )

    new_subtotal = Decimal("0.00")
    new_tax = Decimal("0.00")
    new_total = Decimal("0.00")

    for line in source_lines:
        adj = adjustments_by_line.get(line.line_number) if adjustments_by_line is not None else None
        if adjustments_by_line is not None and adj is None:
            continue

        qty = line.quantity or Decimal("1")
        unit_price = line.unit_price_excl_tax or Decimal("0")
        line_subtotal = line.line_subtotal_excl_tax or Decimal("0")
        line_tax = line.tax_amount or Decimal("0")
        line_total = line.line_total_incl_tax or Decimal("0")

        if adj is not None:
            if "quantity" in adj and adj["quantity"] is not None:
                qty = Decimal(str(adj["quantity"]))
            if "amount" in adj and adj["amount"] is not None:
                line_subtotal = Decimal(str(adj["amount"]))
                rate = (line.tax_rate or Decimal("0")) / Decimal("100")
                line_tax = (line_subtotal * rate).quantize(Decimal("0.01"))
                line_total = line_subtotal + line_tax

        LineItem.objects.create(
            organization_id=source.organization_id,
            invoice=new_inv,
            line_number=line.line_number,
            description=line.description,
            unit_of_measurement=line.unit_of_measurement,
            quantity=qty,
            unit_price_excl_tax=unit_price,
            line_subtotal_excl_tax=line_subtotal,
            tax_type_code=line.tax_type_code,
            tax_rate=line.tax_rate,
            tax_amount=line_tax,
            line_total_incl_tax=line_total,
            classification_code=line.classification_code,
        )
        new_subtotal += line_subtotal
        new_tax += line_tax
        new_total += line_total

    if adjustments_by_line is not None:
        new_inv.subtotal = new_subtotal
        new_inv.total_tax = new_tax
        new_inv.grand_total = new_total
        new_inv.save(update_fields=["subtotal", "total_tax", "grand_total", "updated_at"])

    record_event(
        action_type=config["audit"],
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(source.organization_id),
        affected_entity_type="Invoice",
        affected_entity_id=str(new_inv.id),
        payload={
            "source_invoice_id": str(source.id),
            "source_lhdn_uuid": source.lhdn_uuid,
            f"{noun.replace(' ', '_')}_number": new_inv.invoice_number,
            "reason": reason.strip()[:255],
            config["lines_field"]: len(source_lines)
            if adjustments_by_line is None
            else len([a for a in (line_adjustments or [])]),
        },
    )

    return new_inv


def create_credit_note(
    *,
    source_invoice_id: uuid.UUID | str,
    reason: str,
    actor_user_id: uuid.UUID | str,
    line_adjustments: list[dict[str, Any]] | None = None,
) -> Invoice:
    """Issue a Credit Note (LHDN type 02) against a Validated invoice.

    Reduces the value of the original. Common case: customer
    returned goods, refund issued, post-issue discount applied.
    """
    return _create_amendment(
        config=_AMENDMENT_CONFIGS["credit_note"],
        source_invoice_id=source_invoice_id,
        reason=reason,
        actor_user_id=actor_user_id,
        line_adjustments=line_adjustments,
    )


def create_debit_note(
    *,
    source_invoice_id: uuid.UUID | str,
    reason: str,
    actor_user_id: uuid.UUID | str,
    line_adjustments: list[dict[str, Any]] | None = None,
) -> Invoice:
    """Issue a Debit Note (LHDN type 03) against a Validated invoice.

    Adds value to the original. Common case: late-payment penalty,
    additional charge billed after issue, freight surcharge.
    """
    return _create_amendment(
        config=_AMENDMENT_CONFIGS["debit_note"],
        source_invoice_id=source_invoice_id,
        reason=reason,
        actor_user_id=actor_user_id,
        line_adjustments=line_adjustments,
    )


def create_refund_note(
    *,
    source_invoice_id: uuid.UUID | str,
    reason: str,
    actor_user_id: uuid.UUID | str,
    line_adjustments: list[dict[str, Any]] | None = None,
) -> Invoice:
    """Issue a Refund Note (LHDN type 04) against a Validated invoice.

    Confirms that a refund payment has been issued back to the
    buyer. Distinct from Credit Note: a CN reduces an outstanding
    receivable, an RN documents an actual money refund. Some
    workflows pair them (CN first, RN after the payment goes out).
    """
    return _create_amendment(
        config=_AMENDMENT_CONFIGS["refund_note"],
        source_invoice_id=source_invoice_id,
        reason=reason,
        actor_user_id=actor_user_id,
        line_adjustments=line_adjustments,
    )
