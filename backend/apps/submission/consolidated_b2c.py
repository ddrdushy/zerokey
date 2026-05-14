"""Phase 5 of PORTAL_PLAN.md — consolidated B2C submission builder.

LHDN's "consolidated invoice" lets a supplier roll up a month of low-
value B2C transactions into a single MyInvois document instead of
submitting one per consumer receipt. The aggregate document is a
standard invoice (type code 01) addressed to "General Public" with
the placeholder TIN ``EI00000000010``. Only B2C invoices (anything
already using the placeholder TIN, or anything with no buyer TIN at
all) are eligible.

This module owns the "build the parent invoice + link the
constituents" half. The signing + submission half reuses the existing
``sign_invoice`` / ``submit_invoice_to_lhdn`` pipeline — the parent
is just another Invoice row.

What ``build_consolidated_b2c`` does, in order:

  1. Resolve every eligible constituent for the org + calendar month:
       - issue_date in the month
       - direction = OUTBOUND
       - buyer_tin in {"", "EI00000000010"} (B2C heuristic)
       - status in {NOT_SUBMITTED, READY_FOR_REVIEW} (not already in
         flight, not already individually submitted)
       - not already part of another consolidation
  2. Refuse with a clear error if there's nothing eligible.
  3. Create the parent Invoice row:
       - invoice_number = ``CONS-B2C-<org-prefix>-<YYYY-MM>``
       - buyer set to General Public + placeholder TIN
       - subtotal / total_tax / grand_total = sum of constituents
       - one line item per constituent (description records the
         constituent's invoice number)
       - status = READY_FOR_REVIEW so the existing submit pipeline
         picks it up; auto-submit gate runs on the parent like any
         other invoice
  4. Flip each constituent to status CONSOLIDATED, set
     consolidated_in_invoice_id to the parent's id.
  5. Audit event ``submission.consolidated_b2c.built`` records the
     parent invoice + constituent count + total.

Out of scope for v1 (deferred to v2):
  - The dedicated LHDN consolidated-invoice JSON shape. Today the
    parent invoice goes through the normal JSON builder; LHDN's
    sandbox accepts it as a regular invoice. Refining this to use
    LHDN's specific consolidated-invoice fields (the receipt-period
    range, the "consolidation_indicator" flag) lands when we wire
    the live LHDN production submission.
  - Auto-trigger by Celery beat on the 1st of the next month.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Q

from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.identity.tenancy import super_admin_context, tenant_context

logger = logging.getLogger(__name__)

GENERAL_PUBLIC_TIN = "EI00000000010"
GENERAL_PUBLIC_NAME = "General Public"


class ConsolidationError(Exception):
    """Raised when a consolidation request can't proceed."""


@dataclass(frozen=True)
class ConsolidationResult:
    parent_invoice_id: str
    constituent_count: int
    grand_total: Decimal
    month_label: str


@dataclass(frozen=True)
class ConsolidationPreview:
    """What ``preview_consolidated_b2c`` returns — what would happen if
    the caller invoked ``build_consolidated_b2c`` right now."""

    year: int
    month: int
    month_label: str
    eligible_count: int
    eligible_total: Decimal
    has_existing_parent: bool
    existing_parent_invoice_number: str = ""


def preview_consolidated_b2c(
    *,
    organization_id: uuid.UUID | str,
    year: int,
    month: int,
) -> ConsolidationPreview:
    """Read-only sibling of ``build_consolidated_b2c``.

    Counts eligible B2C invoices for the (org, year, month) tuple and
    reports whether a parent already exists. The portal calls this
    before the customer commits to Build so the affordance can show
    "12 invoices · RM 4,820 — Build" rather than "click and hope".
    """
    from apps.submission.models import Invoice

    if not (1 <= month <= 12):
        raise ConsolidationError(f"Invalid month {month}; expected 1-12")
    month_start = date(year, month, 1)
    month_end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    month_label = month_start.strftime("%B %Y")

    with tenant_context(organization_id):
        with super_admin_context(reason="submission.consolidated_b2c.preview"):
            existing = (
                Invoice.objects.filter(
                    organization_id=organization_id,
                    issue_date__gte=month_start,
                    issue_date__lt=month_end,
                    buyer_tin=GENERAL_PUBLIC_TIN,
                    direction=Invoice.Direction.OUTBOUND,
                    invoice_number__startswith="CONS-B2C-",
                )
                .exclude(status=Invoice.Status.CANCELLED)
                .first()
            )

            eligible_qs = (
                Invoice.objects.filter(
                    organization_id=organization_id,
                    direction=Invoice.Direction.OUTBOUND,
                    issue_date__gte=month_start,
                    issue_date__lt=month_end,
                    consolidated_in_invoice_id__isnull=True,
                    status__in=[
                        Invoice.Status.NOT_SUBMITTED,
                        Invoice.Status.READY_FOR_REVIEW,
                    ],
                )
                .filter(Q(buyer_tin="") | Q(buyer_tin=GENERAL_PUBLIC_TIN))
            )
            eligible_count = eligible_qs.count()
            total = Decimal("0")
            for inv in eligible_qs.only("grand_total"):
                total += inv.grand_total or Decimal("0")

    return ConsolidationPreview(
        year=year,
        month=month,
        month_label=month_label,
        eligible_count=eligible_count,
        eligible_total=total,
        has_existing_parent=existing is not None,
        existing_parent_invoice_number=existing.invoice_number if existing else "",
    )


def build_consolidated_b2c(
    *,
    organization_id: uuid.UUID | str,
    year: int,
    month: int,
    actor_user_id: uuid.UUID | str | None = None,
) -> ConsolidationResult:
    """Build the parent consolidated invoice and link the constituents.

    Does NOT call LHDN — the parent invoice is left at READY_FOR_REVIEW
    so the existing submission pipeline (manual or auto-submit) takes
    it from there. Idempotent against the same (org, year, month):
    re-running raises ConsolidationError if a parent already exists.
    """
    from apps.submission.models import Invoice, InvoiceLineItem

    if not (1 <= month <= 12):
        raise ConsolidationError(f"Invalid month {month}; expected 1-12")
    month_start = date(year, month, 1)
    month_end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    month_label = month_start.strftime("%B %Y")

    with tenant_context(organization_id):
        with super_admin_context(reason="submission.consolidated_b2c.build"):
            # Refuse if a parent already exists for this period.
            existing_parent = (
                Invoice.objects.filter(
                    organization_id=organization_id,
                    issue_date__gte=month_start,
                    issue_date__lt=month_end,
                    buyer_tin=GENERAL_PUBLIC_TIN,
                    direction=Invoice.Direction.OUTBOUND,
                    invoice_number__startswith="CONS-B2C-",
                )
                .exclude(status=Invoice.Status.CANCELLED)
                .first()
            )
            if existing_parent is not None:
                raise ConsolidationError(
                    f"A consolidated B2C parent already exists for {month_label} "
                    f"(invoice {existing_parent.invoice_number}). Cancel that one first "
                    "if you need to rebuild."
                )

            # Resolve constituents.
            constituents = list(
                Invoice.objects.filter(
                    organization_id=organization_id,
                    direction=Invoice.Direction.OUTBOUND,
                    issue_date__gte=month_start,
                    issue_date__lt=month_end,
                    consolidated_in_invoice_id__isnull=True,
                    status__in=[
                        Invoice.Status.NOT_SUBMITTED,
                        Invoice.Status.READY_FOR_REVIEW,
                    ],
                )
                .filter(Q(buyer_tin="") | Q(buyer_tin=GENERAL_PUBLIC_TIN))
                .order_by("issue_date", "invoice_number")
            )

            if not constituents:
                raise ConsolidationError(
                    f"No eligible B2C invoices for {month_label}. "
                    "Consolidation needs at least one outbound invoice with no buyer TIN "
                    "(or the LHDN B2C placeholder) that isn't already submitted or rolled in."
                )

            # Sum the totals.
            subtotal = Decimal("0")
            total_tax = Decimal("0")
            grand_total = Decimal("0")
            currency_code = constituents[0].currency_code or "MYR"
            supplier_legal_name = ""
            supplier_tin = ""
            supplier_registration_number = ""
            for inv in constituents:
                subtotal += inv.subtotal or Decimal("0")
                total_tax += inv.total_tax or Decimal("0")
                grand_total += inv.grand_total or Decimal("0")
                if not supplier_legal_name and inv.supplier_legal_name:
                    supplier_legal_name = inv.supplier_legal_name
                if not supplier_tin and inv.supplier_tin:
                    supplier_tin = inv.supplier_tin
                if not supplier_registration_number and inv.supplier_registration_number:
                    supplier_registration_number = inv.supplier_registration_number

            # The parent needs an ingestion_job_id (unique constraint). The
            # parent isn't a real "ingested" doc so we mint a UUID and link
            # back via the constituent's job_id is undesirable — we mint a
            # fresh one. The ingestion table doesn't have a real row for
            # this synthesised parent; that's fine since the IngestionJob
            # uniqueness is just to prevent dupes, not a hard FK.
            parent_id = uuid.uuid4()
            org_prefix = str(organization_id)[:8]
            invoice_number = f"CONS-B2C-{org_prefix}-{year:04d}-{month:02d}"

            with transaction.atomic():
                parent = Invoice.objects.create(
                    id=parent_id,
                    organization_id=organization_id,
                    ingestion_job_id=uuid.uuid4(),
                    direction=Invoice.Direction.OUTBOUND,
                    invoice_type=Invoice.InvoiceType.STANDARD,
                    status=Invoice.Status.READY_FOR_REVIEW,
                    invoice_number=invoice_number,
                    issue_date=month_end - (month_end - month_start),  # = month_start
                    currency_code=currency_code,
                    supplier_legal_name=supplier_legal_name,
                    supplier_tin=supplier_tin,
                    supplier_registration_number=supplier_registration_number,
                    buyer_legal_name=GENERAL_PUBLIC_NAME,
                    buyer_tin=GENERAL_PUBLIC_TIN,
                    buyer_country_code="MY",
                    subtotal=subtotal,
                    total_tax=total_tax,
                    grand_total=grand_total,
                    overall_confidence=1.0,
                )

                # One line item per constituent — line description records
                # the constituent's invoice number for audit. We don't
                # explode each constituent's own line items (the
                # consolidation reports the constituent invoice, not the
                # SKU-level detail behind it).
                for idx, inv in enumerate(constituents):
                    InvoiceLineItem.objects.create(
                        invoice=parent,
                        line_number=idx + 1,
                        description=f"B2C consolidation row: {inv.invoice_number or inv.id}",
                        quantity=Decimal("1"),
                        unit_price=inv.grand_total or Decimal("0"),
                        line_total=inv.grand_total or Decimal("0"),
                        tax_amount=inv.total_tax or Decimal("0"),
                    )

                # Flip constituents to CONSOLIDATED, link them to the parent.
                Invoice.objects.filter(id__in=[c.id for c in constituents]).update(
                    status=Invoice.Status.CONSOLIDATED,
                    consolidated_in_invoice_id=parent.id,
                )

            record_event(
                action_type="submission.consolidated_b2c.built",
                actor_type=AuditEvent.ActorType.USER
                if actor_user_id is not None
                else AuditEvent.ActorType.SERVICE,
                actor_id=str(actor_user_id) if actor_user_id else "submission.consolidated_b2c",
                organization_id=str(organization_id),
                affected_entity_type="Invoice",
                affected_entity_id=str(parent.id),
                payload={
                    "year": year,
                    "month": month,
                    "constituent_count": len(constituents),
                    "grand_total": str(grand_total),
                    "currency_code": currency_code,
                },
            )

            logger.info(
                "consolidated_b2c.built",
                extra={
                    "organization_id": str(organization_id),
                    "parent_invoice_id": str(parent.id),
                    "constituent_count": len(constituents),
                },
            )

            return ConsolidationResult(
                parent_invoice_id=str(parent.id),
                constituent_count=len(constituents),
                grand_total=grand_total,
                month_label=month_label,
            )
