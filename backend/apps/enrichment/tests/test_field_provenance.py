"""Tests for per-field provenance + extended TIN-verification states (Slice 73)."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.enrichment import services as enrichment_services
from apps.enrichment import tin_verification
from apps.enrichment.models import CustomerMaster
from apps.identity.models import Organization, Role
from apps.submission.models import Invoice


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org(seeded) -> Organization:
    return Organization.objects.create(
        legal_name="Provenance Test Sdn Bhd",
        tin="C1111111111",
        contact_email="ops@provenance.example",
    )


def _make_invoice(
    *,
    org: Organization,
    buyer_tin: str = "C9999999999",
    buyer_legal_name: str = "Acme Buyer",
    buyer_address: str = "Level 5, KL Sentral",
    buyer_phone: str = "",
) -> Invoice:
    return Invoice.objects.create(
        organization=org,
        ingestion_job_id=uuid.uuid4(),
        invoice_number=f"INV-{uuid.uuid4().hex[:8]}",
        issue_date=date(2026, 4, 29),
        due_date=date(2026, 5, 29),
        currency_code="MYR",
        supplier_legal_name=org.legal_name,
        supplier_tin=org.tin,
        buyer_legal_name=buyer_legal_name,
        buyer_tin=buyer_tin,
        buyer_address=buyer_address,
        buyer_phone=buyer_phone,
        subtotal=Decimal("100.00"),
        total_tax=Decimal("8.00"),
        grand_total=Decimal("108.00"),
        status=Invoice.Status.READY_FOR_REVIEW,
    )


# =============================================================================
# Provenance written by enrichment
# =============================================================================


@pytest.mark.django_db
class TestEnrichmentWritesProvenance:
    def test_create_path_marks_every_populated_field_extracted(
        self, org
    ) -> None:
        invoice = _make_invoice(
            org=org,
            buyer_tin="C9999999999",
            buyer_legal_name="Acme",
            buyer_address="Some address",
        )
        enrichment_services.enrich_invoice(invoice.id)

        master = CustomerMaster.objects.get(organization=org)
        prov = master.field_provenance
        for field in ("legal_name", "tin", "address"):
            assert prov.get(field, {}).get("source") == "extracted"
            assert "extracted_at" in prov[field]
            assert prov[field]["invoice_id"] == str(invoice.id)
        # Phone was blank on the invoice → no provenance entry.
        assert "phone" not in prov

    def test_match_path_only_writes_for_newly_filled_fields(
        self, org
    ) -> None:
        # Pre-existing master with TIN + legal_name + address.
        master = CustomerMaster.objects.create(
            organization=org,
            legal_name="Acme",
            tin="C9999999999",
            address="Original address",
            field_provenance={
                "legal_name": {"source": "extracted", "extracted_at": "earlier"},
                "tin": {"source": "extracted", "extracted_at": "earlier"},
                "address": {"source": "extracted", "extracted_at": "earlier"},
            },
        )

        # Invoice carries a NEW phone the master didn't know yet.
        invoice = _make_invoice(
            org=org,
            buyer_tin="C9999999999",
            buyer_legal_name="Acme",
            buyer_address="",
            buyer_phone="+60123456789",
        )
        enrichment_services.enrich_invoice(invoice.id)
        master.refresh_from_db()
        prov = master.field_provenance
        # Phone is newly tagged.
        assert prov.get("phone", {}).get("source") == "extracted"
        # Address provenance untouched (original "earlier" timestamp).
        assert prov["address"]["extracted_at"] == "earlier"

    def test_manual_edit_marks_field_manual(self, org) -> None:
        invoice = _make_invoice(org=org, buyer_address="Original")
        enrichment_services.enrich_invoice(invoice.id)
        master = CustomerMaster.objects.get(organization=org)

        actor_id = uuid.uuid4()
        enrichment_services.update_customer_master(
            organization_id=org.id,
            customer_id=master.id,
            updates={"address": "User-edited address"},
            actor_user_id=actor_id,
        )
        master.refresh_from_db()
        prov = master.field_provenance
        assert prov["address"]["source"] == "manual"
        assert prov["address"]["edited_by"] == str(actor_id)
        # Other fields' provenance not touched.
        assert prov["legal_name"]["source"] == "extracted"


# =============================================================================
# needs_verification — extended states
# =============================================================================


@pytest.mark.django_db
class TestNeedsVerificationExtendedStates:
    def _make(self, *, org, state, last_at=None, tin="C9999999999"):
        return CustomerMaster.objects.create(
            organization=org,
            legal_name="X",
            tin=tin,
            tin_verification_state=state,
            tin_last_verified_at=last_at,
        )

    def test_unverified_external_source_triggers_check(self, org) -> None:
        master = self._make(
            org=org,
            state=CustomerMaster.TinVerificationState.UNVERIFIED_EXTERNAL_SOURCE,
        )
        # External source = customer trusts where it came from, but
        # LHDN hasn't confirmed. Must verify now.
        assert tin_verification.needs_verification(master) is True

    def test_manually_resolved_treated_like_verified(self, org) -> None:
        # Recent manually_resolved → no re-check.
        recent = self._make(
            org=org,
            state=CustomerMaster.TinVerificationState.MANUALLY_RESOLVED,
            last_at=timezone.now() - timedelta(days=5),
        )
        assert tin_verification.needs_verification(recent) is False

        # Stale manually_resolved → re-check.
        stale = self._make(
            org=org,
            state=CustomerMaster.TinVerificationState.MANUALLY_RESOLVED,
            last_at=timezone.now()
            - timedelta(days=tin_verification.VERIFY_REFRESH_DAYS + 1),
            tin="C8888888888",
        )
        assert tin_verification.needs_verification(stale) is True


# =============================================================================
# Backfill — exercises the migration's helper directly so we don't
# depend on the test DB carrying a pre-migration shape.
# =============================================================================


@pytest.mark.django_db
class TestBackfillHelper:
    def test_populated_fields_get_extracted_entries(self, org) -> None:
        # A row with no provenance — same shape as a row that
        # existed before migration 0003.
        master = CustomerMaster.objects.create(
            organization=org,
            legal_name="Pre-migration Co",
            tin="C7777777777",
            address="Some address",
            phone="+60111",
            field_provenance={},
        )

        # Re-import from the migration module + invoke the helper
        # against the live ORM.
        from importlib import import_module

        mod = import_module(
            "apps.enrichment.migrations.0003_field_provenance_and_states"
        )
        from django.apps import apps as live_apps

        mod.backfill_provenance(live_apps, None)

        master.refresh_from_db()
        prov = master.field_provenance
        for field in ("legal_name", "tin", "address", "phone"):
            assert prov.get(field, {}).get("source") == "extracted"
            assert "extracted_at" in prov[field]
        # Blank fields stay un-tagged.
        assert "registration_number" not in prov

    def test_provenance_default_empty_dict(self, org) -> None:
        master = CustomerMaster.objects.create(
            organization=org, legal_name="X", tin=""
        )
        assert master.field_provenance == {}
