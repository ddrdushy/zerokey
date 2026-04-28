"""Tests for the enrichment service.

Covers the contract every other context relies on:

  - First-time buyer creates a CustomerMaster row.
  - Repeat buyer (matching by TIN) increments usage_count, never duplicates.
  - Repeat buyer matched by name (TIN missing or different) still
    consolidates into one master record and learns the alias.
  - Auto-fill copies master values into blank invoice fields, never
    overwrites populated ones, and bumps the per-field confidence to 1.0.
  - Line items match-or-create against ItemMaster, with matched lines
    inheriting the master's default codes.
  - Audit log records counts but no buyer-name PII.
  - Cross-tenant isolation: enrichment for one org never reads or
    writes another org's masters.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.audit.models import AuditEvent
from apps.enrichment.models import CustomerMaster, ItemMaster
from apps.enrichment.services import enrich_invoice
from apps.identity.models import Organization, OrganizationMembership, Role, User
from apps.submission.models import Invoice, LineItem


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org(seeded) -> Organization:
    organization = Organization.objects.create(
        legal_name="Acme Sdn Bhd", tin="C10000000001", contact_email="ops@acme.example"
    )
    user = User.objects.create_user(email="o@acme.example", password="x")
    OrganizationMembership.objects.create(
        user=user, organization=organization, role=Role.objects.get(name="owner")
    )
    return organization


def _make_invoice(
    org: Organization,
    *,
    ingestion_job_id: str,
    buyer_name: str = "Buyer Sdn Bhd",
    buyer_tin: str = "C20880050010",
    buyer_address: str = "",
    buyer_msic: str = "",
    line_descriptions: tuple[str, ...] = ("Widget A",),
) -> Invoice:
    invoice = Invoice.objects.create(
        organization=org,
        ingestion_job_id=ingestion_job_id,
        invoice_number="INV-001",
        currency_code="MYR",
        supplier_legal_name="Acme",
        supplier_tin="C10000000001",
        buyer_legal_name=buyer_name,
        buyer_tin=buyer_tin,
        buyer_address=buyer_address,
        buyer_msic_code=buyer_msic,
    )
    for i, description in enumerate(line_descriptions, start=1):
        LineItem.objects.create(
            organization=org,
            invoice=invoice,
            line_number=i,
            description=description,
            quantity=Decimal("1"),
            unit_price_excl_tax=Decimal("100.00"),
            line_subtotal_excl_tax=Decimal("100.00"),
            tax_amount=Decimal("6.00"),
            line_total_incl_tax=Decimal("106.00"),
        )
    return invoice


@pytest.mark.django_db
class TestCustomerMaster:
    def test_first_invoice_creates_master(self, org) -> None:
        invoice = _make_invoice(
            org,
            ingestion_job_id="11111111-1111-4111-8111-111111111111",
            buyer_address="Lot 5 Some Street",
            buyer_msic="46900",
        )

        result = enrich_invoice(invoice.id)
        assert result.customer_created is True
        assert result.customer_matched is False

        masters = CustomerMaster.objects.filter(organization=org)
        assert masters.count() == 1
        m = masters.first()
        assert m.legal_name == "Buyer Sdn Bhd"
        assert m.tin == "C20880050010"
        assert m.address == "Lot 5 Some Street"
        assert m.usage_count == 1

    def test_repeat_buyer_by_tin_increments_usage(self, org) -> None:
        first = _make_invoice(
            org, ingestion_job_id="22222222-2222-4222-8222-222222222222"
        )
        enrich_invoice(first.id)

        second = _make_invoice(
            org, ingestion_job_id="33333333-3333-4333-8333-333333333333"
        )
        result = enrich_invoice(second.id)

        assert result.customer_matched is True
        assert result.customer_created is False
        masters = CustomerMaster.objects.filter(organization=org)
        assert masters.count() == 1
        assert masters.first().usage_count == 2

    def test_repeat_buyer_with_name_variant_learns_alias(self, org) -> None:
        first = _make_invoice(
            org,
            ingestion_job_id="44444444-4444-4444-8444-444444444444",
            buyer_name="Buyer Sdn Bhd",
        )
        enrich_invoice(first.id)

        second = _make_invoice(
            org,
            ingestion_job_id="55555555-5555-4555-8555-555555555555",
            buyer_name="BUYER SDN BHD",  # uppercase variant from a different LLM extraction
        )
        result = enrich_invoice(second.id)

        assert result.customer_matched is True
        master = CustomerMaster.objects.get(organization=org)
        assert "BUYER SDN BHD" in master.aliases

    def test_matches_by_name_when_tin_missing(self, org) -> None:
        first = _make_invoice(
            org,
            ingestion_job_id="66666666-6666-4666-8666-666666666666",
            buyer_tin="",  # B2C / pre-LHDN buyer with no TIN yet
            buyer_name="Walk-in Customer",
        )
        enrich_invoice(first.id)

        second = _make_invoice(
            org,
            ingestion_job_id="77777777-7777-4777-8777-777777777777",
            buyer_tin="",
            buyer_name="walk-in customer",  # case-insensitive match
        )
        result = enrich_invoice(second.id)

        assert result.customer_matched is True
        assert CustomerMaster.objects.filter(organization=org).count() == 1

    def test_skips_master_when_buyer_completely_blank(self, org) -> None:
        invoice = _make_invoice(
            org,
            ingestion_job_id="88888888-8888-4888-8888-888888888888",
            buyer_tin="",
            buyer_name="",
        )
        result = enrich_invoice(invoice.id)
        assert result.customer_created is False
        assert result.customer_matched is False
        assert CustomerMaster.objects.filter(organization=org).count() == 0


@pytest.mark.django_db
class TestAutofill:
    def test_auto_fills_blank_buyer_address_from_master(self, org) -> None:
        first = _make_invoice(
            org,
            ingestion_job_id="aaaaaaaa-1111-4111-8111-111111111111",
            buyer_address="Lot 5 Some Street",
        )
        enrich_invoice(first.id)

        second = _make_invoice(
            org,
            ingestion_job_id="bbbbbbbb-2222-4222-8222-222222222222",
            buyer_address="",  # this one didn't extract the address
        )
        result = enrich_invoice(second.id)

        assert "buyer_address" in result.fields_autofilled
        second.refresh_from_db()
        assert second.buyer_address == "Lot 5 Some Street"
        # Per-field confidence reflects "from your master".
        assert second.per_field_confidence.get("buyer_address") == 1.0

    def test_does_not_overwrite_populated_buyer_address(self, org) -> None:
        first = _make_invoice(
            org,
            ingestion_job_id="cccccccc-3333-4333-8333-333333333333",
            buyer_address="Original Master Address",
        )
        enrich_invoice(first.id)

        second = _make_invoice(
            org,
            ingestion_job_id="dddddddd-4444-4444-8444-444444444444",
            buyer_address="Different LLM-extracted Address",
        )
        enrich_invoice(second.id)
        second.refresh_from_db()

        assert second.buyer_address == "Different LLM-extracted Address"

    def test_legal_name_is_never_auto_filled_from_master(self, org) -> None:
        """The LLM read SOME name from the document; never silently change it."""
        first = _make_invoice(
            org,
            ingestion_job_id="eeeeeeee-5555-4555-8555-555555555555",
            buyer_name="Master Canonical Name",
        )
        enrich_invoice(first.id)

        # Second invoice somehow has no buyer name (extraction gap).
        second = _make_invoice(
            org,
            ingestion_job_id="ffffffff-6666-4666-8666-666666666666",
            buyer_name="",
        )
        # buyer_tin matches, so the master IS found, but legal_name isn't auto-filled.
        enrich_invoice(second.id)
        second.refresh_from_db()
        assert second.buyer_legal_name == ""


@pytest.mark.django_db
class TestItemMaster:
    def test_first_invoice_creates_one_master_per_line(self, org) -> None:
        invoice = _make_invoice(
            org,
            ingestion_job_id="11112222-1111-4111-8111-111111111111",
            line_descriptions=("Widget A", "Widget B"),
        )
        result = enrich_invoice(invoice.id)
        assert result.items_created == 2
        assert result.items_matched == 0
        assert ItemMaster.objects.filter(organization=org).count() == 2

    def test_repeat_line_matches_existing_master_and_inherits_codes(self, org) -> None:
        # Manually seed a master with some default codes — simulates a
        # previous correction where the user saved good defaults.
        ItemMaster.objects.create(
            organization=org,
            canonical_name="Widget A",
            default_classification_code="011",
            default_tax_type_code="01",
            default_unit_of_measurement="EA",
        )

        invoice = _make_invoice(
            org,
            ingestion_job_id="22223333-2222-4222-8222-222222222222",
            line_descriptions=("Widget A",),
        )
        result = enrich_invoice(invoice.id)

        assert result.items_matched == 1
        assert result.items_created == 0

        line = invoice.line_items.first()
        line.refresh_from_db()
        assert line.classification_code == "011"
        assert line.tax_type_code == "01"
        assert line.unit_of_measurement == "EA"

    def test_repeat_line_does_not_overwrite_populated_codes(self, org) -> None:
        ItemMaster.objects.create(
            organization=org,
            canonical_name="Widget A",
            default_classification_code="011",
        )
        invoice = _make_invoice(
            org,
            ingestion_job_id="33334444-3333-4333-8333-333333333333",
            line_descriptions=("Widget A",),
        )
        line = invoice.line_items.first()
        line.classification_code = "999"  # the LLM extracted something specific
        line.save()

        enrich_invoice(invoice.id)
        line.refresh_from_db()
        assert line.classification_code == "999"

    def test_blank_descriptions_skipped(self, org) -> None:
        invoice = _make_invoice(
            org,
            ingestion_job_id="44445555-4444-4444-8444-444444444444",
            line_descriptions=("",),
        )
        result = enrich_invoice(invoice.id)
        assert result.items_created == 0
        assert ItemMaster.objects.filter(organization=org).count() == 0


@pytest.mark.django_db
class TestAuditAndIsolation:
    def test_emits_invoice_enriched_event_without_pii(self, org) -> None:
        invoice = _make_invoice(
            org,
            ingestion_job_id="55556666-5555-4555-8555-555555555555",
            buyer_name="Customer With Sensitive Name Sdn Bhd",
        )
        enrich_invoice(invoice.id)

        event = AuditEvent.objects.filter(action_type="invoice.enriched").first()
        assert event is not None
        # Counts and the master id are present...
        assert event.payload["customer_created"] is True
        assert "customer_master_id" in event.payload
        # ...but the buyer name (PII) is NOT in the payload.
        serialized = str(event.payload)
        assert "Customer With Sensitive Name" not in serialized

    def test_cross_tenant_isolation(self, org) -> None:
        other = Organization.objects.create(
            legal_name="Other Sdn Bhd",
            tin="C99999999999",
            contact_email="ops@other.example",
        )

        invoice_a = _make_invoice(
            org,
            ingestion_job_id="66667777-6666-4666-8666-666666666666",
            buyer_tin="C20880050010",
        )
        enrich_invoice(invoice_a.id)

        # Same buyer TIN, but on the OTHER org's invoice — must NOT collide
        # with org A's master.
        invoice_b = _make_invoice(
            other,
            ingestion_job_id="77778888-7777-4777-8777-777777777777",
            buyer_tin="C20880050010",
        )
        enrich_invoice(invoice_b.id)

        assert CustomerMaster.objects.filter(organization=org).count() == 1
        assert CustomerMaster.objects.filter(organization=other).count() == 1
