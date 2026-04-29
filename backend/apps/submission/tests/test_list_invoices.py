"""Tests for the all-invoices list endpoint (Slice 24)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone

from apps.identity.models import Organization, OrganizationMembership, Role, User
from apps.submission.models import Invoice
from apps.submission.services import (
    count_invoices_for_organization,
    list_invoices_for_organization,
)


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org_user(seeded) -> tuple[Organization, User]:
    org = Organization.objects.create(
        legal_name="Acme Sdn Bhd", tin="C10000000001", contact_email="ops@acme.example"
    )
    user = User.objects.create_user(email="o@acme.example", password="long-enough-password")
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name="owner")
    )
    return org, user


@pytest.fixture
def authed(org_user) -> tuple[Client, Organization]:
    org, user = org_user
    client = Client()
    client.force_login(user)
    session = client.session
    session["organization_id"] = str(org.id)
    session.save()
    return client, org


def _make_invoice(
    org: Organization,
    *,
    ingestion_job_id: str,
    invoice_number: str = "INV-001",
    status: str = Invoice.Status.READY_FOR_REVIEW,
    buyer_legal_name: str = "Buyer Sdn Bhd",
    buyer_tin: str = "C20880050010",
    grand_total: str = "100.00",
) -> Invoice:
    return Invoice.objects.create(
        organization=org,
        ingestion_job_id=ingestion_job_id,
        invoice_number=invoice_number,
        currency_code="MYR",
        supplier_legal_name="Acme",
        supplier_tin="C10000000001",
        buyer_legal_name=buyer_legal_name,
        buyer_tin=buyer_tin,
        status=status,
        grand_total=Decimal(grand_total),
    )


@pytest.mark.django_db
class TestListInvoicesService:
    def test_returns_org_invoices_newest_first(self, org_user) -> None:
        org, _ = org_user
        first = _make_invoice(org, ingestion_job_id="11111111-1111-4111-8111-111111111111")
        second = _make_invoice(org, ingestion_job_id="22222222-2222-4222-8222-222222222222")
        third = _make_invoice(org, ingestion_job_id="33333333-3333-4333-8333-333333333333")
        rows = list_invoices_for_organization(organization_id=org.id)
        assert [r.id for r in rows] == [third.id, second.id, first.id]

    def test_status_filter_exact_match(self, org_user) -> None:
        org, _ = org_user
        _make_invoice(
            org,
            ingestion_job_id="11111111-1111-4111-8111-111111111111",
            status=Invoice.Status.READY_FOR_REVIEW,
        )
        _make_invoice(
            org,
            ingestion_job_id="22222222-2222-4222-8222-222222222222",
            status=Invoice.Status.VALIDATED,
        )
        rows = list_invoices_for_organization(
            organization_id=org.id, status=Invoice.Status.VALIDATED
        )
        assert len(rows) == 1
        assert rows[0].status == Invoice.Status.VALIDATED

    def test_search_matches_invoice_number_or_buyer_name_or_buyer_tin(self, org_user) -> None:
        org, _ = org_user
        # Invoice number match
        _make_invoice(
            org,
            ingestion_job_id="11111111-1111-4111-8111-111111111111",
            invoice_number="INV-2026-001",
            buyer_legal_name="Buyer A",
        )
        # Buyer-name match
        _make_invoice(
            org,
            ingestion_job_id="22222222-2222-4222-8222-222222222222",
            invoice_number="ABC-1",
            buyer_legal_name="Smith Trading Sdn Bhd",
        )
        # Buyer-TIN match
        _make_invoice(
            org,
            ingestion_job_id="33333333-3333-4333-8333-333333333333",
            invoice_number="XYZ",
            buyer_tin="C99999999999",
        )

        # Search by partial invoice number.
        rows = list_invoices_for_organization(organization_id=org.id, search="INV-2026")
        assert {r.invoice_number for r in rows} == {"INV-2026-001"}

        # Search by buyer name (case-insensitive).
        rows = list_invoices_for_organization(organization_id=org.id, search="smith")
        assert {r.buyer_legal_name for r in rows} == {"Smith Trading Sdn Bhd"}

        # Search by buyer TIN substring.
        rows = list_invoices_for_organization(organization_id=org.id, search="999999")
        assert {r.buyer_tin for r in rows} == {"C99999999999"}

    def test_before_created_at_paginates(self, org_user) -> None:
        org, _ = org_user
        now = timezone.now()
        invs = []
        for i in range(5):
            inv = _make_invoice(
                org,
                ingestion_job_id=f"{i:08d}-1111-4111-8111-111111111111",
                invoice_number=f"INV-{i}",
            )
            # Backdate so the cursor pagination is unambiguous.
            Invoice.objects.filter(pk=inv.pk).update(created_at=now - timedelta(minutes=i))
            invs.append(inv)

        page1 = list_invoices_for_organization(organization_id=org.id, limit=2)
        cursor = page1[-1].created_at
        page2 = list_invoices_for_organization(
            organization_id=org.id, limit=2, before_created_at=cursor
        )
        assert len(page1) == 2
        assert len(page2) == 2
        assert all(r.created_at < cursor for r in page2)

    def test_other_orgs_invoices_excluded(self, org_user) -> None:
        org, _ = org_user
        other = Organization.objects.create(
            legal_name="Other", tin="C99999999999", contact_email="other@example"
        )
        _make_invoice(org, ingestion_job_id="11111111-1111-4111-8111-111111111111")
        _make_invoice(other, ingestion_job_id="22222222-2222-4222-8222-222222222222")

        rows = list_invoices_for_organization(organization_id=org.id)
        assert len(rows) == 1
        assert rows[0].organization_id == org.id


@pytest.mark.django_db
class TestListInvoicesEndpoint:
    def test_get_returns_results_and_total(self, authed) -> None:
        client, org = authed
        for i in range(3):
            _make_invoice(
                org,
                ingestion_job_id=f"{i:08d}-1111-4111-8111-111111111111",
                invoice_number=f"INV-{i}",
            )
        response = client.get("/api/v1/invoices/")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 3
        assert len(body["results"]) == 3
        # Compact shape — pin the field set.
        assert set(body["results"][0].keys()) == {
            "id",
            "ingestion_job_id",
            "invoice_number",
            "issue_date",
            "currency_code",
            "grand_total",
            "buyer_legal_name",
            "buyer_tin",
            "status",
            "created_at",
        }

    def test_status_filter_via_query_param(self, authed) -> None:
        client, org = authed
        _make_invoice(
            org,
            ingestion_job_id="11111111-1111-4111-8111-111111111111",
            status=Invoice.Status.VALIDATED,
        )
        _make_invoice(
            org,
            ingestion_job_id="22222222-2222-4222-8222-222222222222",
            status=Invoice.Status.READY_FOR_REVIEW,
        )
        response = client.get("/api/v1/invoices/?status=validated")
        assert response.status_code == 200
        results = response.json()["results"]
        assert all(r["status"] == "validated" for r in results)

    def test_search_via_query_param(self, authed) -> None:
        client, org = authed
        _make_invoice(
            org,
            ingestion_job_id="11111111-1111-4111-8111-111111111111",
            invoice_number="MATCH-ME-2026",
        )
        _make_invoice(
            org,
            ingestion_job_id="22222222-2222-4222-8222-222222222222",
            invoice_number="OTHER",
        )
        response = client.get("/api/v1/invoices/?search=MATCH")
        assert response.status_code == 200
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["invoice_number"] == "MATCH-ME-2026"

    def test_invalid_limit_rejected(self, authed) -> None:
        client, _ = authed
        response = client.get("/api/v1/invoices/?limit=abc")
        assert response.status_code == 400

    def test_invalid_before_created_at_rejected(self, authed) -> None:
        client, _ = authed
        response = client.get("/api/v1/invoices/?before_created_at=not-a-date")
        assert response.status_code == 400

    def test_unauthenticated_rejected(self) -> None:
        response = Client().get("/api/v1/invoices/")
        assert response.status_code in (401, 403)


@pytest.mark.django_db
class TestCountInvoicesService:
    def test_counts_active_org_only(self, org_user) -> None:
        org, _ = org_user
        other = Organization.objects.create(
            legal_name="Other", tin="C99999999999", contact_email="other@example"
        )
        _make_invoice(org, ingestion_job_id="11111111-1111-4111-8111-111111111111")
        _make_invoice(org, ingestion_job_id="22222222-2222-4222-8222-222222222222")
        _make_invoice(other, ingestion_job_id="33333333-3333-4333-8333-333333333333")

        assert count_invoices_for_organization(organization_id=org.id) == 2
        assert count_invoices_for_organization(organization_id=other.id) == 1
