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
