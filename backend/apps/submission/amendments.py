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


@transaction.atomic
def create_credit_note(
    *,
    source_invoice_id: uuid.UUID | str,
    reason: str,
    actor_user_id: uuid.UUID | str,
    line_adjustments: list[dict[str, Any]] | None = None,
) -> Invoice:
    """Create a Credit Note that references a LHDN-validated invoice.

    ``source_invoice_id`` must point at an Invoice in
    ``Status.VALIDATED`` with a populated ``lhdn_uuid``. LHDN
    refuses CN/DN/RN against unsubmitted documents — the
    BillingReference must point at a real LHDN-issued UUID.

    ``line_adjustments`` is optional. When omitted, the new CN
    copies every line item from the source 1:1 (full credit).
    When provided, it's a list of ``{"line_number", "quantity",
    "amount"}`` dicts — one per line being credited. Lines not
    listed are excluded from the CN.

    ``reason`` is required + lands in ``adjustment_reason``,
    which the JSON generator emits as the document-level
    ``Note``. Surfaced in MyInvois's portal so the buyer can
    see why the credit was issued.
    """
    if not reason or not reason.strip():
        raise AmendmentError("A reason is required for a credit note.")

    source = Invoice.objects.filter(id=source_invoice_id).first()
    if source is None:
        raise AmendmentError(
            f"Source invoice {source_invoice_id} not found."
        )

    if source.status != Invoice.Status.VALIDATED:
        raise AmendmentError(
            f"Source invoice must be Validated by LHDN before a credit "
            f"note can be issued (current status: {source.status})."
        )
    if not source.lhdn_uuid:
        raise AmendmentError(
            "Source invoice has no LHDN UUID — credit notes require "
            "the original invoice's LHDN-issued UUID."
        )

    # Mint a stable invoice number for the CN. Pattern: <orig>-CN-<seq>.
    # The seq lets multiple CNs against the same invoice coexist.
    sibling_count = Invoice.objects.filter(
        organization_id=source.organization_id,
        original_invoice_uuid=source.lhdn_uuid,
        invoice_type=Invoice.InvoiceType.CREDIT_NOTE,
    ).count()
    cn_number = f"{source.invoice_number}-CN-{sibling_count + 1:02d}"

    # Build the new Invoice row by copying the source's header
    # fields. The new row gets a fresh UUID + a fresh
    # ingestion_job_id (CNs aren't tied to an ingested PDF).
    cn = Invoice.objects.create(
        organization_id=source.organization_id,
        ingestion_job_id=uuid.uuid4(),
        invoice_number=cn_number,
        issue_date=timezone.now().date(),
        due_date=source.due_date,
        currency_code=source.currency_code,
        # Amendment-specific.
        invoice_type=Invoice.InvoiceType.CREDIT_NOTE,
        original_invoice_uuid=source.lhdn_uuid,
        original_invoice_internal_id=source.invoice_number,
        adjustment_reason=reason.strip(),
        # Parties — same as source. Buyer-issued credit notes flip
        # supplier/buyer; that's a future Slice 62 (self-billed CN).
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
        # Totals — start as a copy of the source. The user can then
        # adjust them in the review screen if it's a partial credit.
        subtotal=source.subtotal,
        total_tax=source.total_tax,
        grand_total=source.grand_total,
        status=Invoice.Status.READY_FOR_REVIEW,
    )

    # Copy line items (full credit by default) OR apply adjustments.
    source_lines = list(source.line_items.all().order_by("line_number"))
    adjustments_by_line = (
        {a["line_number"]: a for a in (line_adjustments or [])}
        if line_adjustments
        else None
    )

    new_subtotal = Decimal("0.00")
    new_tax = Decimal("0.00")
    new_total = Decimal("0.00")

    for line in source_lines:
        adj = (
            adjustments_by_line.get(line.line_number)
            if adjustments_by_line is not None
            else None
        )
        if adjustments_by_line is not None and adj is None:
            # Line not in the adjustments list → not credited. Skip.
            continue

        # Default values: copy the source line as-is.
        qty = line.quantity or Decimal("1")
        unit_price = line.unit_price_excl_tax or Decimal("0")
        line_subtotal = line.line_subtotal_excl_tax or Decimal("0")
        line_tax = line.tax_amount or Decimal("0")
        line_total = line.line_total_incl_tax or Decimal("0")

        # Apply caller-supplied adjustments if any.
        if adj is not None:
            if "quantity" in adj and adj["quantity"] is not None:
                qty = Decimal(str(adj["quantity"]))
            if "amount" in adj and adj["amount"] is not None:
                # Caller specifies the credit amount directly. Recompute
                # tax + total proportionally to the source's tax rate.
                line_subtotal = Decimal(str(adj["amount"]))
                rate = (line.tax_rate or Decimal("0")) / Decimal("100")
                line_tax = (line_subtotal * rate).quantize(Decimal("0.01"))
                line_total = line_subtotal + line_tax

        LineItem.objects.create(
            organization_id=source.organization_id,
            invoice=cn,
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

    # If adjustments were supplied, recompute totals to match the
    # actual line sum (so the review-page total matches the lines).
    if adjustments_by_line is not None:
        cn.subtotal = new_subtotal
        cn.total_tax = new_tax
        cn.grand_total = new_total
        cn.save(update_fields=["subtotal", "total_tax", "grand_total", "updated_at"])

    record_event(
        action_type="submission.amendment.credit_note_created",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(source.organization_id),
        affected_entity_type="Invoice",
        affected_entity_id=str(cn.id),
        payload={
            "source_invoice_id": str(source.id),
            "source_lhdn_uuid": source.lhdn_uuid,
            "credit_note_number": cn.invoice_number,
            "reason": reason.strip()[:255],
            "lines_credited": len(source_lines)
            if adjustments_by_line is None
            else len([a for a in (line_adjustments or [])]),
        },
    )

    return cn
