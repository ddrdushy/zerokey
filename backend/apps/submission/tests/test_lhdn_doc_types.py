"""Tests for LHDN document type coverage (Slice 60)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.identity.models import (
    Organization,
    OrganizationMembership,
    Role,
    User,
)
from apps.submission import lhdn_json
from apps.submission.lhdn_json import (
    LHDN_TYPE_CODES,
    TYPES_REQUIRING_BILLING_REFERENCE,
)
from apps.submission.models import Invoice, LineItem


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org(seeded) -> Organization:
    return Organization.objects.create(
        legal_name="Acme",
        tin="C1234567890",
        contact_email="o@acme.example",
    )


def _make_invoice(org: Organization, *, invoice_type: str, **overrides) -> Invoice:
    inv = Invoice.objects.create(
        organization=org,
        ingestion_job_id=overrides.pop(
            "ingestion_job_id", "11111111-1111-1111-1111-111111111111"
        ),
        invoice_number=overrides.pop("invoice_number", "INV-001"),
        issue_date=date(2026, 4, 29),
        currency_code="MYR",
        supplier_legal_name="Acme",
        supplier_tin="C1234567890",
        buyer_legal_name="Globex",
        buyer_tin="C9999999999",
        subtotal=Decimal("100.00"),
        total_tax=Decimal("8.00"),
        grand_total=Decimal("108.00"),
        invoice_type=invoice_type,
        **overrides,
    )
    LineItem.objects.create(
        organization=org,
        invoice=inv,
        line_number=1,
        line_subtotal_excl_tax=Decimal("100.00"),
    )
    return inv


# =============================================================================
# Type-code mapping
# =============================================================================


class TestTypeCodeMapping:
    def test_all_eight_lhdn_codes_covered(self) -> None:
        """Every LHDN-defined code (01-04, 11-14) must have an enum entry."""
        codes = set(LHDN_TYPE_CODES.values())
        assert codes >= {"01", "02", "03", "04", "11", "12", "13", "14"}

    def test_billing_reference_required_set(self) -> None:
        """CN/DN/RN — both regular + self-billed — require BillingReference."""
        expected = {"02", "03", "04", "12", "13", "14"}
        assert TYPES_REQUIRING_BILLING_REFERENCE == expected

    def test_legacy_self_billed_alias(self) -> None:
        """Old ``self_billed`` rows still map to type 11 for back-compat."""
        assert LHDN_TYPE_CODES["self_billed"] == "11"


# =============================================================================
# Per-type JSON output checks
# =============================================================================


@pytest.mark.django_db
class TestStandardInvoice:
    def test_emits_type_code_01(self, org) -> None:
        inv = _make_invoice(org, invoice_type=Invoice.InvoiceType.STANDARD)
        doc = lhdn_json.build_invoice_json(inv)
        invoice_body = doc["Invoice"][0]
        assert invoice_body["InvoiceTypeCode"][0]["_"] == "01"

    def test_no_billing_reference(self, org) -> None:
        inv = _make_invoice(org, invoice_type=Invoice.InvoiceType.STANDARD)
        doc = lhdn_json.build_invoice_json(inv)
        assert "BillingReference" not in doc["Invoice"][0]


@pytest.mark.django_db
class TestCreditNote:
    def test_emits_type_code_02(self, org) -> None:
        inv = _make_invoice(
            org,
            invoice_type=Invoice.InvoiceType.CREDIT_NOTE,
            invoice_number="CN-001",
            original_invoice_uuid="ORIG-UUID-XYZ",
            original_invoice_internal_id="INV-001",
        )
        doc = lhdn_json.build_invoice_json(inv)
        invoice_body = doc["Invoice"][0]
        assert invoice_body["InvoiceTypeCode"][0]["_"] == "02"

    def test_billing_reference_emitted(self, org) -> None:
        inv = _make_invoice(
            org,
            invoice_type=Invoice.InvoiceType.CREDIT_NOTE,
            invoice_number="CN-001",
            original_invoice_uuid="ORIG-UUID-XYZ",
            original_invoice_internal_id="INV-001",
            adjustment_reason="Customer returned 1 unit",
        )
        doc = lhdn_json.build_invoice_json(inv)
        body = doc["Invoice"][0]
        assert "BillingReference" in body
        ref = body["BillingReference"][0]["InvoiceDocumentReference"][0]
        assert ref["UUID"][0]["_"] == "ORIG-UUID-XYZ"
        assert ref["ID"][0]["_"] == "INV-001"
        # Adjustment reason becomes the document-level Note.
        assert "Note" in body
        assert "returned 1 unit" in body["Note"][0]["_"]


@pytest.mark.django_db
class TestDebitNote:
    def test_emits_type_code_03(self, org) -> None:
        inv = _make_invoice(
            org,
            invoice_type=Invoice.InvoiceType.DEBIT_NOTE,
            invoice_number="DN-001",
            original_invoice_uuid="ORIG-UUID-AAA",
        )
        doc = lhdn_json.build_invoice_json(inv)
        assert doc["Invoice"][0]["InvoiceTypeCode"][0]["_"] == "03"
        assert "BillingReference" in doc["Invoice"][0]


@pytest.mark.django_db
class TestRefundNote:
    def test_emits_type_code_04(self, org) -> None:
        inv = _make_invoice(
            org,
            invoice_type=Invoice.InvoiceType.REFUND_NOTE,
            invoice_number="RN-001",
            original_invoice_uuid="ORIG-UUID-BBB",
        )
        doc = lhdn_json.build_invoice_json(inv)
        assert doc["Invoice"][0]["InvoiceTypeCode"][0]["_"] == "04"
        assert "BillingReference" in doc["Invoice"][0]


@pytest.mark.django_db
class TestSelfBilled:
    def test_self_billed_invoice_type_11(self, org) -> None:
        inv = _make_invoice(
            org, invoice_type=Invoice.InvoiceType.SELF_BILLED_INVOICE
        )
        doc = lhdn_json.build_invoice_json(inv)
        assert doc["Invoice"][0]["InvoiceTypeCode"][0]["_"] == "11"
        # Self-Billed Invoice (not CN) → no billing reference required.
        assert "BillingReference" not in doc["Invoice"][0]

    def test_self_billed_credit_note_type_12(self, org) -> None:
        inv = _make_invoice(
            org,
            invoice_type=Invoice.InvoiceType.SELF_BILLED_CREDIT_NOTE,
            original_invoice_uuid="UID-12",
        )
        doc = lhdn_json.build_invoice_json(inv)
        assert doc["Invoice"][0]["InvoiceTypeCode"][0]["_"] == "12"
        assert "BillingReference" in doc["Invoice"][0]

    def test_self_billed_debit_note_type_13(self, org) -> None:
        inv = _make_invoice(
            org,
            invoice_type=Invoice.InvoiceType.SELF_BILLED_DEBIT_NOTE,
            original_invoice_uuid="UID-13",
        )
        doc = lhdn_json.build_invoice_json(inv)
        assert doc["Invoice"][0]["InvoiceTypeCode"][0]["_"] == "13"

    def test_self_billed_refund_note_type_14(self, org) -> None:
        inv = _make_invoice(
            org,
            invoice_type=Invoice.InvoiceType.SELF_BILLED_REFUND_NOTE,
            original_invoice_uuid="UID-14",
        )
        doc = lhdn_json.build_invoice_json(inv)
        assert doc["Invoice"][0]["InvoiceTypeCode"][0]["_"] == "14"

    def test_legacy_self_billed_value_maps_to_type_11(self, org) -> None:
        inv = _make_invoice(org, invoice_type=Invoice.InvoiceType.SELF_BILLED)
        doc = lhdn_json.build_invoice_json(inv)
        assert doc["Invoice"][0]["InvoiceTypeCode"][0]["_"] == "11"


@pytest.mark.django_db
class TestBillingReferenceFallback:
    def test_missing_uuid_falls_back_to_NA(self, org) -> None:
        """If a CN is missing original_invoice_uuid (data-quality bug),
        the JSON still serialises with ``NA`` so LHDN's parser doesn't
        choke on a null. LHDN's own validator will return a clean
        BillingRef-missing error rather than a schema crash."""
        inv = _make_invoice(
            org,
            invoice_type=Invoice.InvoiceType.CREDIT_NOTE,
            original_invoice_uuid="",
            original_invoice_internal_id="",
        )
        doc = lhdn_json.build_invoice_json(inv)
        ref = doc["Invoice"][0]["BillingReference"][0]["InvoiceDocumentReference"][0]
        assert ref["UUID"][0]["_"] == "NA"
        assert ref["ID"][0]["_"] in ("NA", "INV-001")
