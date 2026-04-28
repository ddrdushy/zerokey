"""Per-rule unit tests for the validation engine.

Rules are pure functions — they take a hydrated ``Invoice`` and return a
list of issues. Tests assemble a minimal valid invoice via fixtures and
mutate it to violate one rule at a time, asserting that the right code
fires (and that the other rules stay quiet for the focused mutation).

The arithmetic and date rules also assert that values *within* tolerance
do not trip — this is where the LHDN spec is most easily misread.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.identity.models import Organization, OrganizationMembership, Role, User
from apps.submission.models import Invoice, LineItem
from apps.validation import rules


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


def _make_valid_invoice(org: Organization) -> Invoice:
    """Fully-valid invoice that should produce zero ERROR-level issues.

    Used as the baseline for the per-rule tests so each test mutates one
    field and asserts only that rule fires. The arithmetic is internally
    consistent: 2 line items at 100.00 = 200.00 subtotal; 6% tax = 12.00;
    grand total = 212.00.
    """
    today = date.today()
    invoice = Invoice.objects.create(
        organization=org,
        ingestion_job_id="11111111-1111-4111-8111-111111111111",
        invoice_number="INV-001",
        issue_date=today,
        due_date=today + timedelta(days=30),
        currency_code="MYR",
        supplier_legal_name="Acme Sdn Bhd",
        supplier_tin="C10000000001",
        supplier_msic_code="62010",
        buyer_legal_name="Customer Sdn Bhd",
        buyer_tin="C20880050010",
        buyer_msic_code="46900",
        buyer_country_code="MY",
        subtotal=Decimal("200.00"),
        total_tax=Decimal("12.00"),
        grand_total=Decimal("212.00"),
    )
    LineItem.objects.create(
        organization=org,
        invoice=invoice,
        line_number=1,
        description="Widget A",
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
        description="Widget B",
        quantity=Decimal("1"),
        unit_price_excl_tax=Decimal("100.00"),
        line_subtotal_excl_tax=Decimal("100.00"),
        tax_amount=Decimal("6.00"),
        line_total_incl_tax=Decimal("106.00"),
    )
    return invoice


def _codes(issues) -> set[str]:
    return {i.code for i in issues}


@pytest.mark.django_db
class TestBaselineInvoiceIsClean:
    def test_no_errors_on_valid_invoice(self, org) -> None:
        invoice = _make_valid_invoice(org)
        all_issues = rules.run_all_rules(invoice)
        errors = [i for i in all_issues if i.severity == rules.SEVERITY_ERROR]
        assert errors == [], f"unexpected errors: {[(e.code, e.message) for e in errors]}"


@pytest.mark.django_db
class TestRequiredFields:
    def test_missing_invoice_number_fires_required(self, org) -> None:
        invoice = _make_valid_invoice(org)
        invoice.invoice_number = ""
        invoice.save()

        issues = rules.rule_required_header_fields(invoice)
        assert "required.invoice_number" in _codes(issues)

    def test_missing_supplier_tin_fires_required(self, org) -> None:
        invoice = _make_valid_invoice(org)
        invoice.supplier_tin = ""
        invoice.save()

        issues = rules.rule_required_header_fields(invoice)
        assert "required.supplier_tin" in _codes(issues)

    def test_no_line_items_trips_dedicated_rule(self, org) -> None:
        invoice = _make_valid_invoice(org)
        invoice.line_items.all().delete()

        issues = rules.rule_at_least_one_line_item(invoice)
        assert _codes(issues) == {"required.line_items"}

    def test_missing_buyer_tin_is_warning_not_error(self, org) -> None:
        invoice = _make_valid_invoice(org)
        invoice.buyer_tin = ""
        invoice.save()

        issues = rules.rule_buyer_tin_present(invoice)
        assert len(issues) == 1
        assert issues[0].severity == rules.SEVERITY_WARNING


@pytest.mark.django_db
class TestTinFormat:
    @pytest.mark.parametrize(
        "tin",
        ["C10000000001", "C2088005001", "IG12345678901", "SG12345678901"],
    )
    def test_valid_tins_produce_no_issues(self, org, tin) -> None:
        invoice = _make_valid_invoice(org)
        invoice.supplier_tin = tin
        invoice.save()
        assert rules.rule_supplier_tin_format(invoice) == []

    @pytest.mark.parametrize(
        "tin",
        ["", "12345", "ABC123", "C12", "X12345678901", "c20880050010"],  # lowercase
    )
    def test_invalid_tins_fire_format_rule_or_skip_when_blank(self, org, tin) -> None:
        invoice = _make_valid_invoice(org)
        invoice.supplier_tin = tin
        invoice.save()
        issues = rules.rule_supplier_tin_format(invoice)
        if tin == "":
            # Blank is the required-fields rule's job, not the format rule.
            assert issues == []
        else:
            assert "supplier.tin.format" in _codes(issues)

    def test_buyer_tin_format_independent_of_supplier(self, org) -> None:
        invoice = _make_valid_invoice(org)
        invoice.buyer_tin = "totally-bogus"
        invoice.save()
        assert "buyer.tin.format" in _codes(rules.rule_buyer_tin_format(invoice))


@pytest.mark.django_db
class TestCurrency:
    def test_unsupported_currency_is_warning(self, org) -> None:
        invoice = _make_valid_invoice(org)
        invoice.currency_code = "ZWL"
        invoice.save()
        issues = rules.rule_currency_code(invoice)
        assert _codes(issues) == {"currency.unsupported"}
        assert issues[0].severity == rules.SEVERITY_WARNING

    def test_malformed_currency_is_error(self, org) -> None:
        invoice = _make_valid_invoice(org)
        invoice.currency_code = "12"
        invoice.save()
        assert "currency.format" in _codes(rules.rule_currency_code(invoice))

    def test_myr_two_decimals_is_clean(self, org) -> None:
        invoice = _make_valid_invoice(org)  # all totals already 2 dp
        assert rules.rule_currency_decimal_precision(invoice) == []

    def test_jpy_with_decimals_trips_precision(self, org) -> None:
        invoice = _make_valid_invoice(org)
        invoice.currency_code = "JPY"
        invoice.subtotal = Decimal("10000.50")  # JPY allows 0 decimals
        invoice.save()
        issues = rules.rule_currency_decimal_precision(invoice)
        assert "currency.precision" in _codes(issues)


@pytest.mark.django_db
class TestMsicAndCountry:
    def test_msic_must_be_5_digits(self, org) -> None:
        invoice = _make_valid_invoice(org)
        invoice.supplier_msic_code = "ABC"
        invoice.save()
        assert "supplier_msic_code.format" in _codes(rules.rule_msic_format(invoice))

    def test_msic_blank_is_skipped(self, org) -> None:
        invoice = _make_valid_invoice(org)
        invoice.supplier_msic_code = ""
        invoice.save()
        assert rules.rule_msic_format(invoice) == []

    def test_country_code_must_be_two_letter_alpha(self, org) -> None:
        invoice = _make_valid_invoice(org)
        invoice.buyer_country_code = "MYS"  # ISO alpha-3, not alpha-2
        invoice.save()
        assert "buyer.country.format" in _codes(rules.rule_buyer_country_code(invoice))


@pytest.mark.django_db
class TestDates:
    def test_issue_date_in_future_is_error(self, org) -> None:
        invoice = _make_valid_invoice(org)
        invoice.issue_date = date.today() + timedelta(days=10)
        invoice.save()
        assert "dates.issue_in_future" in _codes(rules.rule_invoice_dates(invoice))

    def test_due_before_issue_is_error(self, org) -> None:
        invoice = _make_valid_invoice(org)
        invoice.issue_date = date.today()
        invoice.due_date = date.today() - timedelta(days=5)
        invoice.save()
        assert "dates.due_before_issue" in _codes(rules.rule_invoice_dates(invoice))

    def test_due_in_past_is_warning(self, org) -> None:
        invoice = _make_valid_invoice(org)
        invoice.issue_date = date.today() - timedelta(days=60)
        invoice.due_date = date.today() - timedelta(days=30)
        invoice.save()
        codes_to_severity = {
            i.code: i.severity for i in rules.rule_invoice_dates(invoice)
        }
        assert codes_to_severity.get("dates.due_in_past") == rules.SEVERITY_WARNING


@pytest.mark.django_db
class TestArithmetic:
    def test_line_subtotal_mismatch_is_error(self, org) -> None:
        invoice = _make_valid_invoice(org)
        line = invoice.line_items.first()
        line.line_subtotal_excl_tax = Decimal("999.99")  # was 100.00
        line.save()
        assert "line.subtotal.mismatch" in _codes(rules.rule_line_item_arithmetic(invoice))

    def test_line_subtotal_within_tolerance_is_clean(self, org) -> None:
        """A 1-cent rounding wobble is the spec'd tolerance; should not trip."""
        invoice = _make_valid_invoice(org)
        line = invoice.line_items.first()
        line.line_subtotal_excl_tax = Decimal("100.01")
        line.save()
        assert rules.rule_line_item_arithmetic(invoice) == []

    def test_invoice_subtotal_mismatch_outside_tolerance(self, org) -> None:
        invoice = _make_valid_invoice(org)
        invoice.subtotal = Decimal("500.00")  # lines sum to 200.00
        invoice.save()
        assert "totals.subtotal.mismatch" in _codes(
            rules.rule_invoice_total_arithmetic(invoice)
        )

    def test_invoice_subtotal_within_one_ringgit_is_clean(self, org) -> None:
        invoice = _make_valid_invoice(org)
        invoice.subtotal = Decimal("200.50")  # 0.50 wobble inside RM 1.00 tolerance
        # also adjust grand_total to match within tolerance
        invoice.grand_total = Decimal("212.50")
        invoice.save()
        assert rules.rule_invoice_total_arithmetic(invoice) == []

    def test_grand_total_mismatch_is_error(self, org) -> None:
        invoice = _make_valid_invoice(org)
        invoice.grand_total = Decimal("999.99")
        invoice.save()
        assert "totals.grand_total.mismatch" in _codes(
            rules.rule_invoice_total_arithmetic(invoice)
        )


@pytest.mark.django_db
class TestRm10kThreshold:
    def test_invoice_over_threshold_fires_info(self, org) -> None:
        invoice = _make_valid_invoice(org)
        invoice.grand_total = Decimal("15000.00")
        invoice.save()
        issues = rules.rule_rm10k_threshold(invoice)
        assert "rm10k.invoice_threshold" in _codes(issues)
        assert all(i.severity == rules.SEVERITY_INFO for i in issues)

    def test_below_threshold_is_quiet(self, org) -> None:
        invoice = _make_valid_invoice(org)
        # baseline grand_total = 212.00 — well below 10K
        assert rules.rule_rm10k_threshold(invoice) == []

    def test_line_over_threshold_fires_per_line(self, org) -> None:
        invoice = _make_valid_invoice(org)
        line = invoice.line_items.first()
        line.line_total_incl_tax = Decimal("12000.00")
        line.save()
        issues = rules.rule_rm10k_threshold(invoice)
        assert "rm10k.line_threshold" in _codes(issues)

    def test_threshold_only_applies_to_myr(self, org) -> None:
        """Foreign-currency totals don't trip the rule until BNM rates wire in."""
        invoice = _make_valid_invoice(org)
        invoice.currency_code = "USD"
        invoice.grand_total = Decimal("99999.00")
        invoice.save()
        assert rules.rule_rm10k_threshold(invoice) == []


@pytest.mark.django_db
class TestSstConsistency:
    def test_registered_supplier_with_no_tax_anywhere_is_warning(self, org) -> None:
        invoice = _make_valid_invoice(org)
        invoice.supplier_sst_number = "W10-1234-56789012"
        invoice.save()
        for line in invoice.line_items.all():
            line.tax_amount = Decimal("0.00")
            line.save()
        invoice.refresh_from_db()
        issues = rules.rule_sst_consistency(invoice)
        assert "sst.no_tax_on_registered_supplier" in _codes(issues)
        assert issues[0].severity == rules.SEVERITY_WARNING

    def test_unregistered_supplier_skips_check(self, org) -> None:
        invoice = _make_valid_invoice(org)
        invoice.supplier_sst_number = ""
        invoice.save()
        for line in invoice.line_items.all():
            line.tax_amount = Decimal("0.00")
            line.save()
        invoice.refresh_from_db()
        assert rules.rule_sst_consistency(invoice) == []


@pytest.mark.django_db
class TestInvoiceNumberUniqueness:
    def test_duplicate_within_org_fires(self, org) -> None:
        first = _make_valid_invoice(org)
        # Second invoice on same org with same invoice_number.
        second = Invoice.objects.create(
            organization=org,
            ingestion_job_id="22222222-2222-4222-8222-222222222222",
            invoice_number=first.invoice_number,
            issue_date=date.today(),
            currency_code="MYR",
            supplier_legal_name="Acme",
            supplier_tin="C10000000001",
            buyer_legal_name="Customer",
            buyer_tin="C20880050010",
        )
        issues = rules.rule_invoice_number_uniqueness(second)
        assert "invoice_number.duplicate" in _codes(issues)

    def test_revalidating_same_invoice_doesnt_self_collide(self, org) -> None:
        invoice = _make_valid_invoice(org)
        # Re-running uniqueness on the same row must not flag itself.
        assert rules.rule_invoice_number_uniqueness(invoice) == []

    def test_same_number_in_different_org_is_fine(self, org) -> None:
        _make_valid_invoice(org)

        other = Organization.objects.create(
            legal_name="Other Sdn Bhd", tin="C99999999999", contact_email="ops@other.example"
        )
        # Hand-build an invoice on the OTHER org with the same number.
        clash = Invoice.objects.create(
            organization=other,
            ingestion_job_id="33333333-3333-4333-8333-333333333333",
            invoice_number="INV-001",
            issue_date=date.today(),
            currency_code="MYR",
            supplier_legal_name="Other",
            supplier_tin="C99999999999",
            buyer_legal_name="Customer",
            buyer_tin="C20880050010",
        )
        # Each tenant has its own invoice-number namespace.
        assert rules.rule_invoice_number_uniqueness(clash) == []
