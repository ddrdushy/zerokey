"""Integration tests for ``validate_invoice`` — the dispatcher.

The per-rule logic is exercised in test_rules.py. These tests focus on
the dispatch + persistence behaviour:

  - issue rows land in the database
  - re-running validation replaces the prior set rather than duplicating
  - audit event payload reports counts + codes (never message text)
  - cross-tenant isolation: querying issues for one org never returns
    rows from another org
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.audit.models import AuditEvent
from apps.identity.models import Organization, OrganizationMembership, Role, User
from apps.submission.models import Invoice, LineItem
from apps.validation.models import ValidationIssue
from apps.validation.services import issues_for_invoice, validate_invoice


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org(seeded) -> Organization:
    organization = Organization.objects.create(
        legal_name="Acme Sdn Bhd", tin="C10000000001", contact_email="ops@acme.example"
    )
    user = User.objects.create_user(email="owner@acme.example", password="x")
    OrganizationMembership.objects.create(
        user=user, organization=organization, role=Role.objects.get(name="owner")
    )
    return organization


def _invoice_with_errors(org: Organization, *, ingestion_job_id: str) -> Invoice:
    """Three deliberate violations: bad TIN, missing buyer name, broken arithmetic."""
    invoice = Invoice.objects.create(
        organization=org,
        ingestion_job_id=ingestion_job_id,
        invoice_number="INV-100",
        issue_date=date.today(),
        currency_code="MYR",
        supplier_legal_name="Acme",
        supplier_tin="not-a-tin",  # format error
        buyer_legal_name="",  # required-fields error
        buyer_tin="C20880050010",
        subtotal=Decimal("200.00"),
        total_tax=Decimal("12.00"),
        grand_total=Decimal("999.99"),  # arithmetic mismatch
    )
    LineItem.objects.create(
        organization=org,
        invoice=invoice,
        line_number=1,
        description="Widget",
        quantity=Decimal("1"),
        unit_price_excl_tax=Decimal("100.00"),
        line_subtotal_excl_tax=Decimal("100.00"),
        tax_amount=Decimal("6.00"),
        line_total_incl_tax=Decimal("106.00"),
    )
    LineItem.objects.create(
        organization=org,
        invoice=invoice,
        line_number=2,
        description="Widget",
        quantity=Decimal("1"),
        unit_price_excl_tax=Decimal("100.00"),
        line_subtotal_excl_tax=Decimal("100.00"),
        tax_amount=Decimal("6.00"),
        line_total_incl_tax=Decimal("106.00"),
    )
    return invoice


@pytest.mark.django_db
class TestValidateInvoice:
    def test_persists_issues_with_correct_severities(self, org) -> None:
        invoice = _invoice_with_errors(
            org, ingestion_job_id="11111111-1111-4111-8111-111111111111"
        )

        result = validate_invoice(invoice.id)

        assert result.error_count >= 3
        assert result.has_blocking_errors

        codes = set(
            ValidationIssue.objects.filter(invoice_id=invoice.id).values_list(
                "code", flat=True
            )
        )
        assert "supplier.tin.format" in codes
        assert "required.buyer_legal_name" in codes
        assert "totals.grand_total.mismatch" in codes

    def test_rerun_replaces_prior_issue_set(self, org) -> None:
        invoice = _invoice_with_errors(
            org, ingestion_job_id="22222222-2222-4222-8222-222222222222"
        )

        validate_invoice(invoice.id)
        first_count = ValidationIssue.objects.filter(invoice_id=invoice.id).count()
        assert first_count >= 3

        # Fix one of the issues — the supplier TIN.
        invoice.supplier_tin = "C10000000001"
        invoice.save()
        validate_invoice(invoice.id)

        codes = set(
            ValidationIssue.objects.filter(invoice_id=invoice.id).values_list(
                "code", flat=True
            )
        )
        assert "supplier.tin.format" not in codes  # fixed
        assert "totals.grand_total.mismatch" in codes  # still wrong

        # No duplicates.
        assert ValidationIssue.objects.filter(invoice_id=invoice.id).count() == len(codes)

    def test_audit_event_carries_counts_and_codes_but_no_message_text(self, org) -> None:
        invoice = _invoice_with_errors(
            org, ingestion_job_id="33333333-3333-4333-8333-333333333333"
        )
        validate_invoice(invoice.id)

        event = AuditEvent.objects.filter(action_type="invoice.validated").last()
        assert event is not None
        payload = event.payload
        assert payload["errors"] >= 3
        assert isinstance(payload["codes"], list)
        # Codes should be present; no human-readable message text leaks in.
        serialized = str(payload)
        assert "supplier.tin.format" in serialized
        assert "Supplier TIN format is invalid" not in serialized

    def test_clean_invoice_records_zero_errors(self, org) -> None:
        # Build a clean invoice (mirrors the baseline from test_rules.py).
        invoice = Invoice.objects.create(
            organization=org,
            ingestion_job_id="44444444-4444-4444-8444-444444444444",
            invoice_number="INV-200",
            issue_date=date.today(),
            currency_code="MYR",
            supplier_legal_name="Acme",
            supplier_tin="C10000000001",
            supplier_msic_code="62010",
            buyer_legal_name="Customer",
            buyer_tin="C20880050010",
            buyer_msic_code="46900",
            buyer_country_code="MY",
            subtotal=Decimal("100.00"),
            total_tax=Decimal("6.00"),
            grand_total=Decimal("106.00"),
        )
        LineItem.objects.create(
            organization=org,
            invoice=invoice,
            line_number=1,
            description="Widget",
            quantity=Decimal("1"),
            unit_price_excl_tax=Decimal("100.00"),
            line_subtotal_excl_tax=Decimal("100.00"),
            tax_amount=Decimal("6.00"),
            line_total_incl_tax=Decimal("106.00"),
        )

        result = validate_invoice(invoice.id)
        assert result.error_count == 0
        assert not result.has_blocking_errors

    def test_issues_for_invoice_filters_by_organization(self, org) -> None:
        a = _invoice_with_errors(
            org, ingestion_job_id="55555555-5555-4555-8555-555555555555"
        )
        validate_invoice(a.id)

        # Different org with the same broken invoice — issues must NOT cross.
        other_org = Organization.objects.create(
            legal_name="Other Sdn Bhd",
            tin="C99999999999",
            contact_email="ops@other.example",
        )
        b = _invoice_with_errors(
            other_org, ingestion_job_id="66666666-6666-4666-8666-666666666666"
        )
        validate_invoice(b.id)

        a_issues = issues_for_invoice(organization_id=org.id, invoice_id=a.id)
        # All A's issues must reference A; none should reference B.
        for issue in a_issues:
            assert str(issue.invoice_id) == str(a.id)
            assert str(issue.organization_id) == str(org.id)
