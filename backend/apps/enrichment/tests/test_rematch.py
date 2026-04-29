"""Tests for the post-apply re-match pass (Slice 76)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from apps.audit.models import AuditEvent
from apps.enrichment.models import CustomerMaster
from apps.enrichment.rematch import rematch_pending_invoices
from apps.identity.models import Organization, Role
from apps.submission.models import Invoice


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org(seeded) -> Organization:
    return Organization.objects.create(
        legal_name="Rematch Test Sdn Bhd",
        tin="C3333333333",
        contact_email="ops@rematch.example",
    )


def _make_invoice(
    *,
    org: Organization,
    status: str = Invoice.Status.READY_FOR_REVIEW,
    buyer_legal_name: str = "Acme",
    buyer_tin: str = "",
    buyer_address: str = "",
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
        status=status,
    )


@pytest.mark.django_db
class TestRematchPendingInvoices:
    def test_no_pending_invoices_zero_counts(self, org) -> None:
        result = rematch_pending_invoices(
            organization_id=org.id, triggered_by="test"
        )
        assert result.rematched == 0
        assert result.lifted == 0

    def test_invoice_with_no_buyer_skipped(self, org) -> None:
        # Invoice with a name that doesn't match anything.
        _make_invoice(org=org, buyer_legal_name="NoMatchEver")
        # Master exists but for a different buyer.
        CustomerMaster.objects.create(
            organization=org,
            legal_name="Different Buyer",
            tin="C9999999999",
            address="Some address",
        )
        result = rematch_pending_invoices(
            organization_id=org.id, triggered_by="test"
        )
        assert result.rematched == 1
        assert result.lifted == 0

    def test_invoice_lifts_when_master_matches(self, org) -> None:
        # Invoice with a known buyer name but blank address.
        invoice = _make_invoice(
            org=org,
            buyer_legal_name="Acme",
            buyer_tin="C9999999999",
            buyer_address="",
        )
        # Master got populated by a sync (post-apply state).
        CustomerMaster.objects.create(
            organization=org,
            legal_name="Acme",
            tin="C9999999999",
            address="Now we have an address",
            phone="+60111",
        )
        result = rematch_pending_invoices(
            organization_id=org.id, triggered_by="connectors.sync_apply"
        )
        assert result.rematched == 1
        assert result.lifted == 1
        assert result.fields_filled_total >= 1

        invoice.refresh_from_db()
        assert invoice.buyer_address == "Now we have an address"
        assert invoice.buyer_phone == "+60111"

    def test_audit_event_emitted_on_lift(self, org) -> None:
        _make_invoice(
            org=org,
            buyer_legal_name="Acme",
            buyer_tin="C9999999999",
            buyer_address="",
        )
        CustomerMaster.objects.create(
            organization=org,
            legal_name="Acme",
            tin="C9999999999",
            address="Filled",
        )
        rematch_pending_invoices(
            organization_id=org.id,
            triggered_by="connectors.sync_apply",
        )
        ev = AuditEvent.objects.filter(
            action_type="invoice.master_match_lifted_by_sync"
        ).first()
        assert ev is not None
        assert ev.payload["triggered_by"] == "connectors.sync_apply"
        # _autofill_buyer reports invoice attribute names
        # (buyer_address) — preserves the existing audit shape from
        # invoice.enriched.
        assert "buyer_address" in ev.payload["fields_filled"]

    def test_idempotent_no_lift_on_second_pass(self, org) -> None:
        _make_invoice(
            org=org,
            buyer_legal_name="Acme",
            buyer_tin="C9999999999",
            buyer_address="",
        )
        CustomerMaster.objects.create(
            organization=org,
            legal_name="Acme",
            tin="C9999999999",
            address="Filled",
        )
        first = rematch_pending_invoices(
            organization_id=org.id, triggered_by="test"
        )
        second = rematch_pending_invoices(
            organization_id=org.id, triggered_by="test"
        )
        assert first.lifted == 1
        # Second run: invoice already has the address, no field
        # left to fill. Re-match still ran (rematched=1) but no
        # lift this time.
        assert second.rematched == 1
        assert second.lifted == 0

    def test_skips_non_ready_for_review_invoices(self, org) -> None:
        # An invoice in VALIDATED state shouldn't be touched even
        # if it has blank fields a master could fill — submitted
        # invoices are immutable.
        _make_invoice(
            org=org,
            buyer_legal_name="Acme",
            buyer_tin="C9999999999",
            buyer_address="",
            status=Invoice.Status.VALIDATED,
        )
        CustomerMaster.objects.create(
            organization=org,
            legal_name="Acme",
            tin="C9999999999",
            address="Master fill",
        )
        result = rematch_pending_invoices(
            organization_id=org.id, triggered_by="test"
        )
        assert result.rematched == 0
        assert result.lifted == 0

    def test_cross_tenant_isolation(self, org, seeded) -> None:
        other_org = Organization.objects.create(
            legal_name="Other Co", tin="C7777777777", contact_email="o@o"
        )
        _make_invoice(
            org=other_org,
            buyer_legal_name="Acme",
            buyer_address="",
        )
        CustomerMaster.objects.create(
            organization=other_org,
            legal_name="Acme",
            address="OtherFill",
        )
        # Re-match for org (not other_org). The other_org's invoice
        # must NOT be touched.
        result = rematch_pending_invoices(
            organization_id=org.id, triggered_by="test"
        )
        assert result.rematched == 0
