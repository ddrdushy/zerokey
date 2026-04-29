"""Tests for the Customers API surface (list / detail / PATCH).

Covers the contract the frontend Customers route relies on:

  - List sorts by ``usage_count`` desc + ``legal_name`` asc, scoped to
    the active org. RLS belt-and-suspenders.
  - Detail returns the master fields the UI renders, 404s on
    cross-tenant access.
  - PATCH applies allowlisted edits, files the previous canonical name
    as an alias on rename, emits a ``customer_master.updated`` audit
    event whose payload lists field NAMES (no values: PII).
  - PATCH refuses non-editable fields (``aliases``, ``usage_count``,
    ``tin_verification_state``).
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.audit.models import AuditEvent
from apps.enrichment.models import CustomerMaster
from apps.identity.models import Organization, OrganizationMembership, Role, User


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


def _make_master(org: Organization, **overrides) -> CustomerMaster:
    defaults = dict(
        legal_name="Buyer Sdn Bhd",
        tin="C20000000001",
        msic_code="46900",
        usage_count=1,
    )
    defaults.update(overrides)
    return CustomerMaster.objects.create(organization=org, **defaults)


@pytest.mark.django_db
class TestListCustomers:
    def test_returns_only_active_orgs_customers(self, authed) -> None:
        client, org = authed

        # This org's masters.
        _make_master(org, legal_name="Active Org Buyer A", tin="C20000000001")
        _make_master(org, legal_name="Active Org Buyer B", tin="C20000000002")

        # Different org's master — must not appear.
        other = Organization.objects.create(
            legal_name="Other Sdn Bhd", tin="C99999999999", contact_email="other@example"
        )
        _make_master(other, legal_name="Other Org Buyer", tin="C30000000001")

        response = client.get("/api/v1/customers/")
        assert response.status_code == 200
        rows = response.json()["results"]
        assert {r["legal_name"] for r in rows} == {
            "Active Org Buyer A",
            "Active Org Buyer B",
        }

    def test_sorts_by_usage_count_then_name(self, authed) -> None:
        client, org = authed
        _make_master(org, legal_name="Z Buyer", tin="C20000000001", usage_count=10)
        _make_master(org, legal_name="A Buyer", tin="C20000000002", usage_count=10)
        _make_master(org, legal_name="M Buyer", tin="C20000000003", usage_count=99)

        rows = client.get("/api/v1/customers/").json()["results"]
        assert [r["legal_name"] for r in rows] == ["M Buyer", "A Buyer", "Z Buyer"]

    def test_unauthenticated_is_rejected(self) -> None:
        response = Client().get("/api/v1/customers/")
        assert response.status_code in (401, 403)


@pytest.mark.django_db
class TestCustomerDetail:
    def test_returns_master_fields(self, authed) -> None:
        client, org = authed
        master = _make_master(org)

        response = client.get(f"/api/v1/customers/{master.id}/")
        assert response.status_code == 200
        body = response.json()
        # Sample of the expected fields — full set checked by the serializer test.
        assert body["legal_name"] == "Buyer Sdn Bhd"
        assert body["tin"] == "C20000000001"
        assert body["aliases"] == []
        assert body["tin_verification_state"] == "unverified"

    def test_other_orgs_master_returns_404(self, authed) -> None:
        client, _ = authed
        other = Organization.objects.create(
            legal_name="Other Sdn Bhd", tin="C99999999999", contact_email="other@example"
        )
        their_master = _make_master(other)

        response = client.get(f"/api/v1/customers/{their_master.id}/")
        assert response.status_code == 404

    def test_locked_fields_empty_by_default(self, authed) -> None:
        # Slice 81 — the serializer always emits locked_fields,
        # empty when no MasterFieldLock rows exist for the master.
        client, org = authed
        master = _make_master(org)
        response = client.get(f"/api/v1/customers/{master.id}/")
        assert response.status_code == 200
        assert response.json()["locked_fields"] == []

    def test_locked_fields_lists_active_locks(self, authed) -> None:
        # Slice 81 — locked_fields surfaces every field that has an
        # active MasterFieldLock for this master.
        import uuid

        from apps.connectors.models import MasterFieldLock, MasterType

        client, org = authed
        master = _make_master(org)
        for fname in ("tin", "address"):
            MasterFieldLock.objects.create(
                organization=org,
                master_type=MasterType.CUSTOMER,
                master_id=master.id,
                field_name=fname,
                locked_by_user_id=uuid.uuid4(),
            )
        response = client.get(f"/api/v1/customers/{master.id}/")
        assert response.status_code == 200
        assert sorted(response.json()["locked_fields"]) == ["address", "tin"]


@pytest.mark.django_db
class TestPatchCustomer:
    def test_patch_corrects_msic_and_audits(self, authed) -> None:
        client, org = authed
        master = _make_master(org, msic_code="99999")  # wrong code

        response = client.patch(
            f"/api/v1/customers/{master.id}/",
            data={"msic_code": "62010"},
            content_type="application/json",
        )
        assert response.status_code == 200, response.content
        master.refresh_from_db()
        assert master.msic_code == "62010"

        event = AuditEvent.objects.filter(action_type="customer_master.updated").first()
        assert event is not None
        assert event.payload["changed_fields"] == ["msic_code"]
        # No values in the audit payload.
        serialized = str(event.payload)
        assert "62010" not in serialized
        assert "99999" not in serialized

    def test_rename_files_old_canonical_as_alias(self, authed) -> None:
        client, org = authed
        master = _make_master(org, legal_name="Old Name Sdn Bhd")

        response = client.patch(
            f"/api/v1/customers/{master.id}/",
            data={"legal_name": "Corrected Name Sdn Bhd"},
            content_type="application/json",
        )
        assert response.status_code == 200
        master.refresh_from_db()
        assert master.legal_name == "Corrected Name Sdn Bhd"
        assert "Old Name Sdn Bhd" in master.aliases

    def test_rejects_non_editable_fields(self, authed) -> None:
        client, org = authed
        master = _make_master(org)

        response = client.patch(
            f"/api/v1/customers/{master.id}/",
            data={"aliases": ["spoofed"]},
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "non-editable" in response.json()["detail"]

        response = client.patch(
            f"/api/v1/customers/{master.id}/",
            data={"usage_count": 9999},
            content_type="application/json",
        )
        assert response.status_code == 400

        response = client.patch(
            f"/api/v1/customers/{master.id}/",
            data={"tin_verification_state": "verified"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_blank_legal_name_rejected(self, authed) -> None:
        client, org = authed
        master = _make_master(org)

        response = client.patch(
            f"/api/v1/customers/{master.id}/",
            data={"legal_name": "   "},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_no_op_when_nothing_changed(self, authed) -> None:
        client, org = authed
        master = _make_master(org, msic_code="62010")

        response = client.patch(
            f"/api/v1/customers/{master.id}/",
            data={"msic_code": "62010"},
            content_type="application/json",
        )
        assert response.status_code == 200
        # No new audit event because nothing actually changed.
        assert AuditEvent.objects.filter(action_type="customer_master.updated").count() == 0

    def test_patch_other_orgs_master_is_404(self, authed) -> None:
        client, _ = authed
        other = Organization.objects.create(
            legal_name="Other Sdn Bhd", tin="C99999999999", contact_email="other@example"
        )
        their_master = _make_master(other)

        response = client.patch(
            f"/api/v1/customers/{their_master.id}/",
            data={"msic_code": "62010"},
            content_type="application/json",
        )
        assert response.status_code == 404


@pytest.mark.django_db
class TestCustomerInvoicesEndpoint:
    """``GET /api/v1/customers/<id>/invoices/`` lists matching invoices.

    Match policy mirrors the enrichment matcher (services._find_customer_master):
    TIN equality wins when the master has a TIN; otherwise legal_name OR
    any learned alias matches case-insensitively.
    """

    def _make_invoice(
        self,
        org: Organization,
        *,
        ingestion_job_id: str,
        buyer_tin: str = "",
        buyer_legal_name: str = "",
    ):
        from decimal import Decimal

        from apps.submission.models import Invoice

        return Invoice.objects.create(
            organization=org,
            ingestion_job_id=ingestion_job_id,
            invoice_number="INV-001",
            currency_code="MYR",
            supplier_legal_name="Acme",
            supplier_tin="C10000000001",
            buyer_legal_name=buyer_legal_name,
            buyer_tin=buyer_tin,
            grand_total=Decimal("100.00"),
        )

    def test_lists_invoices_matching_master_tin(self, authed) -> None:
        client, org = authed
        master = _make_master(org, tin="C20000000001")

        # Two invoices with the matching TIN, one without.
        self._make_invoice(
            org,
            ingestion_job_id="11111111-1111-4111-8111-111111111111",
            buyer_tin="C20000000001",
            buyer_legal_name="Some Variant Name",
        )
        self._make_invoice(
            org,
            ingestion_job_id="22222222-2222-4222-8222-222222222222",
            buyer_tin="C20000000001",
            buyer_legal_name="Another Variant",
        )
        self._make_invoice(
            org,
            ingestion_job_id="33333333-3333-4333-8333-333333333333",
            buyer_tin="C99999999999",
            buyer_legal_name="Different Buyer",
        )

        response = client.get(f"/api/v1/customers/{master.id}/invoices/")
        assert response.status_code == 200
        rows = response.json()["results"]
        assert len(rows) == 2
        assert {r["invoice_number"] for r in rows} == {"INV-001"}

    def test_falls_back_to_alias_match_when_master_has_no_tin(self, authed) -> None:
        client, org = authed
        # B2C / pre-LHDN buyer with no TIN — match by name.
        master = _make_master(org, tin="", legal_name="Walk-in Customer")
        master.aliases = ["WALK-IN CUSTOMER", "Walk in customer"]
        master.save()

        # Three invoices: canonical match, alias match (case-insensitive),
        # and unrelated.
        self._make_invoice(
            org,
            ingestion_job_id="11111111-1111-4111-8111-111111111111",
            buyer_legal_name="walk-in customer",  # case-insensitive canonical
        )
        self._make_invoice(
            org,
            ingestion_job_id="22222222-2222-4222-8222-222222222222",
            buyer_legal_name="WALK-IN CUSTOMER",  # alias hit
        )
        self._make_invoice(
            org,
            ingestion_job_id="33333333-3333-4333-8333-333333333333",
            buyer_legal_name="Some other person",
        )

        response = client.get(f"/api/v1/customers/{master.id}/invoices/")
        assert response.status_code == 200
        assert len(response.json()["results"]) == 2

    def test_returns_404_for_other_orgs_customer(self, authed) -> None:
        client, _ = authed
        other = Organization.objects.create(
            legal_name="Other Sdn Bhd",
            tin="C99999999999",
            contact_email="other@example",
        )
        their_master = _make_master(other)

        response = client.get(f"/api/v1/customers/{their_master.id}/invoices/")
        assert response.status_code == 404

    def test_empty_list_when_no_matching_invoices(self, authed) -> None:
        client, org = authed
        master = _make_master(org, tin="C20000000001")

        response = client.get(f"/api/v1/customers/{master.id}/invoices/")
        assert response.status_code == 200
        assert response.json()["results"] == []

    def test_unauthenticated_is_rejected(self) -> None:
        response = Client().get("/api/v1/customers/00000000-0000-0000-0000-000000000000/invoices/")
        assert response.status_code in (401, 403)

    def test_serializer_returns_compact_shape(self, authed) -> None:
        client, org = authed
        master = _make_master(org, tin="C20000000001")
        self._make_invoice(
            org,
            ingestion_job_id="11111111-1111-4111-8111-111111111111",
            buyer_tin="C20000000001",
        )

        rows = client.get(f"/api/v1/customers/{master.id}/invoices/").json()["results"]
        assert len(rows) == 1
        # Compact set: enough for the table + the link out, not the full
        # invoice payload.
        assert set(rows[0].keys()) == {
            "id",
            "ingestion_job_id",
            "invoice_number",
            "issue_date",
            "currency_code",
            "grand_total",
            "status",
            "created_at",
        }
