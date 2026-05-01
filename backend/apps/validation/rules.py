"""Pre-flight LHDN validation rules.

Per LHDN_INTEGRATION.md ZeroKey enforces LHDN's field-level rules locally
before submission so we catch issues before LHDN does. Each rule is a
small function that takes an ``Invoice`` (with line items prefetched)
and returns a list of ``Issue`` records. The dispatcher in
``services.validate_invoice`` runs every rule and persists the results
as ``ValidationIssue`` rows.

What this slice does NOT cover:
  - Live LHDN TIN verification API (separate slice; needs LHDN client).
  - MSIC / classification / UOM catalog matching (need cached LHDN
    catalogs; format-only checks today).
  - Foreign-supplier / self-billed / consolidated B2C special-case rules
    (Phase 3 follow-up; the plumbing here will host them when they land).

Adding a rule:
  1. Write a function ``rule_<name>(invoice) -> list[Issue]``.
  2. Add it to the ``RULES`` list at the bottom of the file.
  3. Add unit tests in ``tests/test_rules.py``.

The rule is responsible for its own field-path strings and message
copy. Severity should match LHDN's posture: blocking-at-submission is
``ERROR``, advisory is ``WARNING``, awareness-only is ``INFO``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from apps.submission.models import Invoice, LineItem

# --- Rule output ---------------------------------------------------------------


@dataclass(frozen=True)
class Issue:
    """One finding from one rule. Persisted as a ``ValidationIssue`` row."""

    code: str
    severity: str  # "error" | "warning" | "info"
    field_path: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"


# --- Constants drawn from LHDN_INTEGRATION.md ----------------------------------

# Currencies LHDN explicitly supports for Malaysian e-invoicing. The full ISO
# 4217 catalog is wider; this is the practical Phase 2/3 allowlist. Anything
# else is a warning, not an error, because some Custom-tier customers need
# exotic currencies.
SUPPORTED_CURRENCIES = frozenset(
    {"MYR", "USD", "SGD", "EUR", "GBP", "JPY", "CNY", "HKD", "AUD", "IDR", "THB", "VND", "KRW"}
)

# Currencies that store zero decimal places. The rest default to two.
ZERO_DECIMAL_CURRENCIES = frozenset({"JPY", "KRW", "VND", "IDR"})

# RM 10,000 threshold — LHDN's hard rule on standalone vs consolidated B2C.
# See LHDN_INTEGRATION.md "The transaction-over-RM-10,000 rule".
RM10K_THRESHOLD = Decimal("10000.00")

# Tolerance per LHDN_INTEGRATION.md "tax and totals block" — 1 cent per line
# and 1 ringgit per invoice. Differences within tolerance get distributed to
# the largest line item; differences outside tolerance are surfaced for the
# user.
LINE_ITEM_TOLERANCE = Decimal("0.01")
INVOICE_TOTAL_TOLERANCE = Decimal("1.00")

# TIN format (loose; LHDN spec varies and the live API is the authoritative check).
# Individual taxpayer TIN: 2-letter prefix (IG/SG/OG/etc.) + 11 digits = 13 chars.
# Corporate TIN: starts with C + 10 or 11 digits.
# We accept anything matching either pattern; obvious garbage (too short,
# special chars) trips the rule.
INDIVIDUAL_TIN = re.compile(r"^[A-Z]{2}\d{11}$")
CORPORATE_TIN = re.compile(r"^C\d{10,11}$")

# 5-digit MSIC code. Catalog match is a follow-up (slice that adds the
# cached LHDN catalogs).
MSIC_PATTERN = re.compile(r"^\d{5}$")

# 2-letter ISO country code.
COUNTRY_CODE_PATTERN = re.compile(r"^[A-Z]{2}$")


# --- Helpers -------------------------------------------------------------------


def _is_blank(value: Any) -> bool:
    return value is None or value == "" or (isinstance(value, str) and not value.strip())


def _line_items(invoice: Invoice) -> list[LineItem]:
    # ``select_related`` / prefetched at the call site; falling back to a
    # fresh query is fine but the dispatcher will normally have prefetched.
    return list(invoice.line_items.all())


# --- Required-fields rules -----------------------------------------------------

REQUIRED_HEADER_FIELDS: tuple[tuple[str, str], ...] = (
    ("invoice_number", "Invoice number is required for LHDN submission."),
    ("issue_date", "Issue date is required for LHDN submission."),
    ("currency_code", "Currency code is required."),
    (
        "supplier_legal_name",
        "Supplier legal name is required (the entity issuing this invoice).",
    ),
    ("supplier_tin", "Supplier TIN is required for LHDN submission."),
    ("buyer_legal_name", "Buyer legal name is required."),
    # Buyer TIN is required for B2B; B2C uses a placeholder. We treat
    # missing as a warning to avoid false errors on consumer invoices.
)


def rule_required_header_fields(invoice: Invoice) -> list[Issue]:
    issues: list[Issue] = []
    for field_name, message in REQUIRED_HEADER_FIELDS:
        if _is_blank(getattr(invoice, field_name, None)):
            issues.append(
                Issue(
                    code=f"required.{field_name}",
                    severity=SEVERITY_ERROR,
                    field_path=field_name,
                    message=message,
                )
            )
    return issues


def rule_at_least_one_line_item(invoice: Invoice) -> list[Issue]:
    if not _line_items(invoice):
        return [
            Issue(
                code="required.line_items",
                severity=SEVERITY_ERROR,
                field_path="line_items",
                message="An invoice needs at least one line item.",
            )
        ]
    return []


def rule_buyer_tin_present(invoice: Invoice) -> list[Issue]:
    """B2B invoices need a buyer TIN; B2C uses an LHDN placeholder.

    We can't know B2B vs B2C without more context, so missing buyer TIN
    is a warning rather than an error — the user reviews and either
    fills it in or confirms the consumer scenario.
    """
    if _is_blank(invoice.buyer_tin):
        return [
            Issue(
                code="buyer.tin.missing",
                severity=SEVERITY_WARNING,
                field_path="buyer_tin",
                message=(
                    "Buyer TIN is missing. Required for B2B; consumer invoices use "
                    "an LHDN placeholder which we apply automatically."
                ),
            )
        ]
    return []


# --- TIN format ----------------------------------------------------------------


def _validate_tin(tin: str) -> bool:
    return bool(INDIVIDUAL_TIN.match(tin) or CORPORATE_TIN.match(tin))


def rule_supplier_tin_format(invoice: Invoice) -> list[Issue]:
    if _is_blank(invoice.supplier_tin):
        return []  # Required-fields rule already flagged this.
    if not _validate_tin(invoice.supplier_tin):
        return [
            Issue(
                code="supplier.tin.format",
                severity=SEVERITY_ERROR,
                field_path="supplier_tin",
                message=(
                    "Supplier TIN format is invalid. Expected a corporate TIN like "
                    "C20880050010 or an individual TIN like IG12345678901."
                ),
                detail={"value": invoice.supplier_tin},
            )
        ]
    return []


def rule_buyer_tin_format(invoice: Invoice) -> list[Issue]:
    if _is_blank(invoice.buyer_tin):
        return []
    if not _validate_tin(invoice.buyer_tin):
        return [
            Issue(
                code="buyer.tin.format",
                severity=SEVERITY_ERROR,
                field_path="buyer_tin",
                message=(
                    "Buyer TIN format is invalid. Expected a corporate TIN like "
                    "C20880050010 or an individual TIN like IG12345678901."
                ),
                detail={"value": invoice.buyer_tin},
            )
        ]
    return []


# --- Currency / MSIC / country -------------------------------------------------


def rule_currency_code(invoice: Invoice) -> list[Issue]:
    if _is_blank(invoice.currency_code):
        return []
    code = invoice.currency_code.upper()
    if len(code) != 3 or not code.isalpha():
        return [
            Issue(
                code="currency.format",
                severity=SEVERITY_ERROR,
                field_path="currency_code",
                message="Currency code must be a 3-letter ISO 4217 code (e.g. MYR, USD).",
                detail={"value": invoice.currency_code},
            )
        ]
    if code not in SUPPORTED_CURRENCIES:
        return [
            Issue(
                code="currency.unsupported",
                severity=SEVERITY_WARNING,
                field_path="currency_code",
                message=(
                    f"Currency {code} is uncommon for Malaysian e-invoicing. "
                    "Submission will work; we'll request the BNM exchange rate at "
                    "issue date."
                ),
                detail={"value": code},
            )
        ]
    return []


def rule_currency_decimal_precision(invoice: Invoice) -> list[Issue]:
    code = (invoice.currency_code or "MYR").upper()
    expected_decimals = 0 if code in ZERO_DECIMAL_CURRENCIES else 2

    issues: list[Issue] = []
    for field_name in ("subtotal", "total_tax", "grand_total", "discount_amount"):
        value: Decimal | None = getattr(invoice, field_name, None)
        if value is None:
            continue
        actual_decimals = -value.as_tuple().exponent if value.as_tuple().exponent < 0 else 0
        if actual_decimals > expected_decimals:
            issues.append(
                Issue(
                    code="currency.precision",
                    severity=SEVERITY_ERROR,
                    field_path=f"totals.{field_name}",
                    message=(
                        f"{field_name} has more decimal places than {code} allows "
                        f"(expected at most {expected_decimals})."
                    ),
                    detail={
                        "currency": code,
                        "field": field_name,
                        "value": str(value),
                        "expected_decimals": expected_decimals,
                    },
                )
            )
    return issues


def _check_msic(value: str, field_path: str, label: str) -> list[Issue]:
    """Two-tier check: format ERROR first, then catalog WARNING.

    Format failures block submission (can't be a valid MSIC code in any
    iteration of the LHDN catalog). Catalog misses are WARNINGS today
    because our seed catalog ships a representative subset only — once
    the monthly LHDN refresh wires in, the catalog becomes authoritative
    and unknown codes promote to ERROR. Promoting too early would
    create false rejections during the seed-only window.
    """
    # Lazy import to avoid validation -> administration cycle at module load.
    from apps.administration.services import is_valid_msic

    if _is_blank(value):
        return []
    if not MSIC_PATTERN.match(value):
        return [
            Issue(
                code=f"{field_path}.format",
                severity=SEVERITY_ERROR,
                field_path=field_path,
                message=(
                    f"{label} MSIC code must be 5 digits (the LHDN industry classification format)."
                ),
                detail={"value": value},
            )
        ]
    if not is_valid_msic(value):
        return [
            Issue(
                code=f"{field_path}.unknown",
                severity=SEVERITY_WARNING,
                field_path=field_path,
                message=(
                    f"{label} MSIC code {value!r} is not in our cached LHDN "
                    "catalog. Submission may still succeed; verify against the "
                    "current LHDN list if unsure."
                ),
                detail={"value": value},
            )
        ]
    return []


def rule_msic_format(invoice: Invoice) -> list[Issue]:
    return [
        *_check_msic(invoice.supplier_msic_code, "supplier_msic_code", "Supplier"),
        *_check_msic(invoice.buyer_msic_code, "buyer_msic_code", "Buyer"),
    ]


def rule_buyer_country_code(invoice: Invoice) -> list[Issue]:
    """Two-tier: format ERROR; catalog WARNING for now.

    LHDN accepts the full ISO 3166-1 alpha-2 set; our seed only has the
    common trade partners. Catalog miss stays a WARNING until the
    refresh task pulls the full LHDN-published list.
    """
    from apps.administration.services import is_valid_country

    if _is_blank(invoice.buyer_country_code):
        return []
    code = invoice.buyer_country_code.upper()
    if not COUNTRY_CODE_PATTERN.match(code):
        return [
            Issue(
                code="buyer.country.format",
                severity=SEVERITY_ERROR,
                field_path="buyer_country_code",
                message="Buyer country code must be a 2-letter ISO 3166-1 alpha-2 code (e.g. MY, SG).",
                detail={"value": invoice.buyer_country_code},
            )
        ]
    if not is_valid_country(code):
        return [
            Issue(
                code="buyer.country.unknown",
                severity=SEVERITY_WARNING,
                field_path="buyer_country_code",
                message=(
                    f"Buyer country code {code!r} is not in our cached ISO catalog. "
                    "Submission may still succeed; verify the code is current."
                ),
                detail={"value": code},
            )
        ]
    return []


# --- Line-item catalog rules ---------------------------------------------------


def rule_line_item_catalogs(invoice: Invoice) -> list[Issue]:
    """Match per-line ``classification_code`` / ``tax_type_code`` /
    ``unit_of_measurement`` against the cached LHDN catalogs.

    All three are WARNING-severity catalog misses (same rationale as the
    MSIC + country rules above: seed is incomplete during the pre-LHDN-
    integration window). Format checks are minimal — the catalogs
    themselves are the format authority.
    """
    from apps.administration.services import (
        is_valid_classification,
        is_valid_tax_type,
        is_valid_uom,
    )

    issues: list[Issue] = []
    for line in _line_items(invoice):
        if line.classification_code and not is_valid_classification(line.classification_code):
            issues.append(
                Issue(
                    code="line.classification.unknown",
                    severity=SEVERITY_WARNING,
                    field_path=f"line_items[{line.line_number}].classification_code",
                    message=(
                        f"Line {line.line_number}: classification code "
                        f"{line.classification_code!r} is not in our cached "
                        "LHDN catalog."
                    ),
                    detail={"value": line.classification_code},
                )
            )
        if line.tax_type_code and not is_valid_tax_type(line.tax_type_code):
            issues.append(
                Issue(
                    code="line.tax_type.unknown",
                    severity=SEVERITY_WARNING,
                    field_path=f"line_items[{line.line_number}].tax_type_code",
                    message=(
                        f"Line {line.line_number}: tax type code "
                        f"{line.tax_type_code!r} is not in the LHDN published list."
                    ),
                    detail={"value": line.tax_type_code},
                )
            )
        if line.unit_of_measurement and not is_valid_uom(line.unit_of_measurement):
            issues.append(
                Issue(
                    code="line.uom.unknown",
                    severity=SEVERITY_WARNING,
                    field_path=f"line_items[{line.line_number}].unit_of_measurement",
                    message=(
                        f"Line {line.line_number}: unit of measurement "
                        f"{line.unit_of_measurement!r} is not in the UN/CEFACT "
                        "subset LHDN accepts."
                    ),
                    detail={"value": line.unit_of_measurement},
                )
            )
    return issues


# --- Dates ---------------------------------------------------------------------


def rule_invoice_dates(invoice: Invoice) -> list[Issue]:
    issues: list[Issue] = []
    today = date.today()

    if invoice.issue_date is not None and invoice.issue_date > today + timedelta(days=1):
        # 1-day grace handles timezone slop between user clock and server.
        issues.append(
            Issue(
                code="dates.issue_in_future",
                severity=SEVERITY_ERROR,
                field_path="issue_date",
                message=(
                    "Issue date is in the future. LHDN expects the invoice issue "
                    "date to match the actual date of issue."
                ),
                detail={"value": invoice.issue_date.isoformat()},
            )
        )

    if (
        invoice.issue_date is not None
        and invoice.due_date is not None
        and invoice.due_date < invoice.issue_date
    ):
        issues.append(
            Issue(
                code="dates.due_before_issue",
                severity=SEVERITY_ERROR,
                field_path="due_date",
                message="Due date is earlier than the issue date.",
                detail={
                    "issue_date": invoice.issue_date.isoformat(),
                    "due_date": invoice.due_date.isoformat(),
                },
            )
        )

    if invoice.due_date is not None and invoice.due_date < today:
        issues.append(
            Issue(
                code="dates.due_in_past",
                severity=SEVERITY_WARNING,
                field_path="due_date",
                message="Due date is in the past — confirm payment terms are correct.",
                detail={"value": invoice.due_date.isoformat()},
            )
        )

    return issues


# --- Sum reconciliation --------------------------------------------------------


def _line_subtotal_sum(items: list[LineItem]) -> Decimal:
    total = Decimal("0.00")
    for line in items:
        if line.line_subtotal_excl_tax is not None:
            total += line.line_subtotal_excl_tax
    return total


def _line_tax_sum(items: list[LineItem]) -> Decimal:
    total = Decimal("0.00")
    for line in items:
        if line.tax_amount is not None:
            total += line.tax_amount
    return total


def rule_line_item_arithmetic(invoice: Invoice) -> list[Issue]:
    """Each line: quantity * unit_price ≈ subtotal; subtotal + tax ≈ line total."""
    issues: list[Issue] = []
    for line in _line_items(invoice):
        if (
            line.quantity is not None
            and line.unit_price_excl_tax is not None
            and line.line_subtotal_excl_tax is not None
        ):
            expected = (line.quantity * line.unit_price_excl_tax).quantize(Decimal("0.01"))
            actual = line.line_subtotal_excl_tax
            if abs(expected - actual) > LINE_ITEM_TOLERANCE:
                issues.append(
                    Issue(
                        code="line.subtotal.mismatch",
                        severity=SEVERITY_ERROR,
                        field_path=f"line_items[{line.line_number}].line_subtotal_excl_tax",
                        message=(
                            f"Line {line.line_number}: quantity × unit price does not "
                            f"match the line subtotal."
                        ),
                        detail={
                            "expected": str(expected),
                            "actual": str(actual),
                            "difference": str(expected - actual),
                        },
                    )
                )

        if (
            line.line_subtotal_excl_tax is not None
            and line.tax_amount is not None
            and line.line_total_incl_tax is not None
        ):
            expected_total = (line.line_subtotal_excl_tax + line.tax_amount).quantize(
                Decimal("0.01")
            )
            actual_total = line.line_total_incl_tax
            if abs(expected_total - actual_total) > LINE_ITEM_TOLERANCE:
                issues.append(
                    Issue(
                        code="line.total.mismatch",
                        severity=SEVERITY_ERROR,
                        field_path=f"line_items[{line.line_number}].line_total_incl_tax",
                        message=(
                            f"Line {line.line_number}: subtotal + tax does not match "
                            f"the line total."
                        ),
                        detail={
                            "expected": str(expected_total),
                            "actual": str(actual_total),
                            "difference": str(expected_total - actual_total),
                        },
                    )
                )

    return issues


def rule_invoice_total_arithmetic(invoice: Invoice) -> list[Issue]:
    """Invoice level: line subtotals -> invoice subtotal; subtotal + tax - discount -> grand total.

    Tolerance is one ringgit per invoice (LHDN spec). Differences within
    tolerance auto-correct elsewhere; differences outside tolerance trip
    this rule for human review.
    """
    issues: list[Issue] = []
    items = _line_items(invoice)

    if invoice.subtotal is not None and items:
        expected_subtotal = _line_subtotal_sum(items)
        if abs(expected_subtotal - invoice.subtotal) > INVOICE_TOTAL_TOLERANCE:
            issues.append(
                Issue(
                    code="totals.subtotal.mismatch",
                    severity=SEVERITY_ERROR,
                    field_path="totals.subtotal",
                    message=("Invoice subtotal does not match the sum of line item subtotals."),
                    detail={
                        "expected": str(expected_subtotal),
                        "actual": str(invoice.subtotal),
                        "difference": str(expected_subtotal - invoice.subtotal),
                    },
                )
            )

    if invoice.total_tax is not None and items:
        expected_tax = _line_tax_sum(items)
        if abs(expected_tax - invoice.total_tax) > INVOICE_TOTAL_TOLERANCE:
            issues.append(
                Issue(
                    code="totals.tax.mismatch",
                    severity=SEVERITY_ERROR,
                    field_path="totals.total_tax",
                    message=("Total tax does not match the sum of per-line tax amounts."),
                    detail={
                        "expected": str(expected_tax),
                        "actual": str(invoice.total_tax),
                        "difference": str(expected_tax - invoice.total_tax),
                    },
                )
            )

    if (
        invoice.subtotal is not None
        and invoice.total_tax is not None
        and invoice.grand_total is not None
    ):
        discount = invoice.discount_amount or Decimal("0.00")
        expected_grand = invoice.subtotal + invoice.total_tax - discount
        if abs(expected_grand - invoice.grand_total) > INVOICE_TOTAL_TOLERANCE:
            issues.append(
                Issue(
                    code="totals.grand_total.mismatch",
                    severity=SEVERITY_ERROR,
                    field_path="totals.grand_total",
                    message=("Grand total does not equal subtotal + tax − invoice-level discount."),
                    detail={
                        "expected": str(expected_grand),
                        "actual": str(invoice.grand_total),
                        "difference": str(expected_grand - invoice.grand_total),
                    },
                )
            )

    return issues


# --- RM 10K threshold ----------------------------------------------------------


def rule_rm10k_threshold(invoice: Invoice) -> list[Issue]:
    """Flag transactions that exceed LHDN's standalone-required threshold.

    Per LHDN_INTEGRATION.md the RM 10K rule is enforced from day one with no
    relaxation. Crossing the threshold doesn't fail validation by itself;
    it changes the consolidation eligibility of the transaction. We surface
    it as INFO so the consolidation flow can refuse to bundle it later.
    """
    issues: list[Issue] = []
    code = (invoice.currency_code or "MYR").upper()
    if code != "MYR":
        return issues  # Threshold is in MYR; foreign-currency invoices use the
        # MYR equivalent for the rule, which lands when BNM rates wire in.

    if invoice.grand_total is not None and invoice.grand_total >= RM10K_THRESHOLD:
        issues.append(
            Issue(
                code="rm10k.invoice_threshold",
                severity=SEVERITY_INFO,
                field_path="totals.grand_total",
                message=(
                    "This invoice exceeds RM 10,000. LHDN requires standalone "
                    "submission with full buyer identification — it cannot be "
                    "rolled into a consolidated B2C invoice."
                ),
                detail={"grand_total": str(invoice.grand_total)},
            )
        )

    for line in _line_items(invoice):
        if line.line_total_incl_tax is None:
            continue
        if line.line_total_incl_tax >= RM10K_THRESHOLD:
            issues.append(
                Issue(
                    code="rm10k.line_threshold",
                    severity=SEVERITY_INFO,
                    field_path=f"line_items[{line.line_number}].line_total_incl_tax",
                    message=(
                        f"Line {line.line_number} exceeds RM 10,000. The invoice as "
                        "a whole must be submitted standalone."
                    ),
                    detail={"line_total": str(line.line_total_incl_tax)},
                )
            )

    return issues


# --- SST consistency -----------------------------------------------------------


def rule_sst_consistency(invoice: Invoice) -> list[Issue]:
    """If supplier has an SST number, line items shouldn't all be tax-exempt.

    Loose check: registered suppliers occasionally issue exempt invoices
    (international sales, exempt goods), so this is a warning. A future
    slice tightens this when the LHDN tax_type_code catalog is wired in.
    """
    if _is_blank(invoice.supplier_sst_number):
        return []
    items = _line_items(invoice)
    if not items:
        return []
    if all((line.tax_amount is None or line.tax_amount == Decimal("0.00")) for line in items):
        return [
            Issue(
                code="sst.no_tax_on_registered_supplier",
                severity=SEVERITY_WARNING,
                field_path="line_items",
                message=(
                    "Supplier has an SST registration number but no line item "
                    "carries tax. Confirm whether this is an exempt sale or a "
                    "missing tax amount."
                ),
            )
        ]
    return []


# --- Self-billed detection (Slice 96 — P1) ------------------------------------


_SELF_BILLED_TYPES = frozenset(
    {
        Invoice.InvoiceType.SELF_BILLED_INVOICE,
        Invoice.InvoiceType.SELF_BILLED_CREDIT_NOTE,
        Invoice.InvoiceType.SELF_BILLED_DEBIT_NOTE,
        Invoice.InvoiceType.SELF_BILLED_REFUND_NOTE,
        # Legacy alias (pre-Slice-60 data may still use this).
        "self_billed",
    }
)


def rule_self_billed_detection(invoice: Invoice) -> list[Issue]:
    """Flag invoices that look like they should be self-billed.

    LHDN's self-billed types (11–14) apply when the BUYER is the one
    creating the invoice (typically Malaysian SME paying a foreign
    supplier who can't issue an LHDN-compliant invoice). The two
    signals: ``supplier_tin`` is blank AND ``buyer_country_code`` is
    "MY" (or empty — defaults to MY) AND the invoice type is not
    already one of the self-billed variants.

    Severity: WARNING. We never silently flip the type — that would
    change the LHDN doc-type code that gets submitted, which has
    real legal meaning. Surface the suggestion; let the user
    confirm with one click.

    The ``detail`` payload tells the frontend which type to flip to:
    if the current type is ``standard`` → ``self_billed_invoice``,
    ``credit_note`` → ``self_billed_credit_note``, etc.
    """
    if _is_blank(invoice.supplier_tin) is False:
        return []  # supplier has a TIN, normal invoice
    if invoice.invoice_type in _SELF_BILLED_TYPES:
        return []  # already self-billed; nothing to flag
    # Buyer must be Malaysian for self-billed to apply (it's a Malaysian
    # tax filing concept). Empty country code defaults to MY by convention.
    buyer_country = (invoice.buyer_country_code or "MY").upper()
    if buyer_country != "MY":
        return []

    # Map standard types to their self-billed counterparts.
    self_billed_map = {
        Invoice.InvoiceType.STANDARD: Invoice.InvoiceType.SELF_BILLED_INVOICE,
        Invoice.InvoiceType.CREDIT_NOTE: Invoice.InvoiceType.SELF_BILLED_CREDIT_NOTE,
        Invoice.InvoiceType.DEBIT_NOTE: Invoice.InvoiceType.SELF_BILLED_DEBIT_NOTE,
        Invoice.InvoiceType.REFUND_NOTE: Invoice.InvoiceType.SELF_BILLED_REFUND_NOTE,
    }
    suggested = self_billed_map.get(invoice.invoice_type)

    return [
        Issue(
            code="invoice_type.self_billed_suggested",
            severity=SEVERITY_WARNING,
            field_path="invoice_type",
            message=(
                "The supplier has no Malaysian TIN — this looks like a self-billed "
                "invoice (a Malaysian buyer paying a foreign or unregistered "
                "supplier). Confirm the invoice type before submitting."
            ),
            detail={
                "current_type": str(invoice.invoice_type),
                "suggested_type": str(suggested) if suggested else "",
            },
        )
    ]


# --- Invoice number uniqueness within supplier namespace -----------------------


def rule_invoice_number_uniqueness(invoice: Invoice) -> list[Issue]:
    """LHDN requires unique invoice numbers within the supplier sequence.

    We check within the issuing organization's namespace — the same
    customer can't reuse an invoice number on two different invoices.
    Implemented by querying for prior Invoices with matching number and
    a different id; we exclude the current row so re-running validation
    on the same invoice doesn't false-trip.

    Per LHDN_INTEGRATION.md we never auto-renumber; we only warn.
    """
    if _is_blank(invoice.invoice_number):
        return []  # required-fields rule covered the blank case
    duplicate = (
        Invoice.objects.filter(
            organization_id=invoice.organization_id,
            invoice_number=invoice.invoice_number,
        )
        .exclude(id=invoice.id)
        .exists()
    )
    if duplicate:
        return [
            Issue(
                code="invoice_number.duplicate",
                severity=SEVERITY_ERROR,
                field_path="invoice_number",
                message=(
                    f"Invoice number '{invoice.invoice_number}' has already been "
                    "used on another invoice. LHDN requires unique numbers within "
                    "the supplier sequence."
                ),
                detail={"value": invoice.invoice_number},
            )
        ]
    return []


# --- Registry ------------------------------------------------------------------

RuleFn = Callable[[Invoice], list[Issue]]

RULES: list[RuleFn] = [
    rule_required_header_fields,
    rule_at_least_one_line_item,
    rule_buyer_tin_present,
    rule_supplier_tin_format,
    rule_buyer_tin_format,
    rule_currency_code,
    rule_currency_decimal_precision,
    rule_msic_format,
    rule_buyer_country_code,
    rule_line_item_catalogs,
    rule_invoice_dates,
    rule_line_item_arithmetic,
    rule_invoice_total_arithmetic,
    rule_rm10k_threshold,
    rule_sst_consistency,
    rule_self_billed_detection,
    rule_invoice_number_uniqueness,
]


def run_all_rules(invoice: Invoice) -> list[Issue]:
    """Execute every rule and concatenate the issues. Order is rule-registration order."""
    issues: list[Issue] = []
    for rule in RULES:
        issues.extend(rule(invoice))
    return issues
