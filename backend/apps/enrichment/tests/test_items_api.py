"""Tests for the Items API surface (Slice 83).

Symmetric to test_customers_api.py — same list / detail / PATCH /
locks contract, ItemMaster instead of CustomerMaster.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.audit.models import AuditEvent
from apps.enrichment.models import ItemMaster
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


def _make_item(org: Organization, **overrides) -> ItemMaster:
    defaults = dict(
        canonical_name="Widget A",
        default_msic_code="25920",
        default_classification_code="022",
        default_tax_type_code="06",
        default_unit_of_measurement="UNIT",
        usage_count=1,
    )
    defaults.update(overrides)
    return ItemMaster.objects.create(organization=org, **defaults)


@pytest.mark.django_db
class TestListItems:
    def test_returns_only_active_orgs_items(self, authed) -> None:
        client, org = authed
        _make_item(org, canonical_name="Active A")
        _make_item(org, canonical_name="Active B")

        other = Organization.objects.create(
            legal_name="Other Sdn Bhd", tin="C99999999999", contact_email="other@example"
        )
        _make_item(other, canonical_name="Other Item")

        response = client.get("/api/v1/items/")
        assert response.status_code == 200
        rows = response.json()["results"]
        assert {r["canonical_name"] for r in rows} == {"Active A", "Active B"}

    def test_sorts_by_usage_count_then_name(self, authed) -> None:
        client, org = authed
        _make_item(org, canonical_name="Z Item", usage_count=10)
        _make_item(org, canonical_name="A Item", usage_count=10)
        _make_item(org, canonical_name="M Item", usage_count=99)

        rows = client.get("/api/v1/items/").json()["results"]
        assert [r["canonical_name"] for r in rows] == ["M Item", "A Item", "Z Item"]

    def test_unauthenticated_is_rejected(self) -> None:
        response = Client().get("/api/v1/items/")
        assert response.status_code in (401, 403)


@pytest.mark.django_db
class TestItemDetail:
    def test_returns_master_fields(self, authed) -> None:
        client, org = authed
        master = _make_item(org)

        response = client.get(f"/api/v1/items/{master.id}/")
        assert response.status_code == 200
        body = response.json()
        assert body["canonical_name"] == "Widget A"
        assert body["default_msic_code"] == "25920"
        assert body["default_unit_of_measurement"] == "UNIT"
        assert body["aliases"] == []

    def test_other_orgs_master_returns_404(self, authed) -> None:
        client, _ = authed
        other = Organization.objects.create(
            legal_name="Other Sdn Bhd", tin="C99999999999", contact_email="other@example"
        )
        their_master = _make_item(other)
        response = client.get(f"/api/v1/items/{their_master.id}/")
        assert response.status_code == 404

    def test_locked_fields_empty_by_default(self, authed) -> None:
        client, org = authed
        master = _make_item(org)
        response = client.get(f"/api/v1/items/{master.id}/")
        assert response.status_code == 200
        assert response.json()["locked_fields"] == []

    def test_locked_fields_lists_active_locks(self, authed) -> None:
        import uuid

        from apps.connectors.models import MasterFieldLock, MasterType

        client, org = authed
        master = _make_item(org)
        for fname in ("default_msic_code", "default_tax_type_code"):
            MasterFieldLock.objects.create(
                organization=org,
                master_type=MasterType.ITEM,
                master_id=master.id,
                field_name=fname,
                locked_by_user_id=uuid.uuid4(),
            )
        response = client.get(f"/api/v1/items/{master.id}/")
        assert response.status_code == 200
        assert sorted(response.json()["locked_fields"]) == [
            "default_msic_code",
            "default_tax_type_code",
        ]


@pytest.mark.django_db
class TestPatchItem:
    def test_patch_corrects_msic_and_audits(self, authed) -> None:
        client, org = authed
        master = _make_item(org)

        response = client.patch(
            f"/api/v1/items/{master.id}/",
            data='{"default_msic_code": "47611"}',
            content_type="application/json",
        )
        assert response.status_code == 200
        master.refresh_from_db()
        assert master.default_msic_code == "47611"

        # Audit logs the field name only.
        ev = AuditEvent.objects.filter(action_type="item_master.updated").first()
        assert ev is not None
        assert ev.payload["changed_fields"] == ["default_msic_code"]
        assert "47611" not in str(ev.payload)

    def test_rename_files_old_canonical_as_alias(self, authed) -> None:
        client, org = authed
        master = _make_item(org, canonical_name="Old Name")
        response = client.patch(
            f"/api/v1/items/{master.id}/",
            data='{"canonical_name": "New Name"}',
            content_type="application/json",
        )
        assert response.status_code == 200
        master.refresh_from_db()
        assert master.canonical_name == "New Name"
        assert "Old Name" in master.aliases

    def test_rejects_non_editable_fields(self, authed) -> None:
        client, org = authed
        master = _make_item(org)
        response = client.patch(
            f"/api/v1/items/{master.id}/",
            data='{"usage_count": 99}',
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "non-editable" in response.json()["detail"]

    def test_blank_canonical_name_rejected(self, authed) -> None:
        client, org = authed
        master = _make_item(org)
        response = client.patch(
            f"/api/v1/items/{master.id}/",
            data='{"canonical_name": "   "}',
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "canonical_name" in response.json()["detail"]

    def test_no_op_when_nothing_changed(self, authed) -> None:
        client, org = authed
        master = _make_item(org, default_msic_code="46900")
        response = client.patch(
            f"/api/v1/items/{master.id}/",
            data='{"default_msic_code": "46900"}',
            content_type="application/json",
        )
        assert response.status_code == 200
        # No audit event was emitted because nothing actually changed.
        assert AuditEvent.objects.filter(action_type="item_master.updated").count() == 0

    def test_unit_price_clears_on_empty_string(self, authed) -> None:
        # Editor sends an empty string when the user clears the field;
        # the service maps that to None on the model.
        client, org = authed
        master = _make_item(org)
        master.default_unit_price_excl_tax = "12.50"
        master.save()

        response = client.patch(
            f"/api/v1/items/{master.id}/",
            data='{"default_unit_price_excl_tax": null}',
            content_type="application/json",
        )
        assert response.status_code == 200
        master.refresh_from_db()
        assert master.default_unit_price_excl_tax is None

    def test_patch_other_orgs_master_is_404(self, authed) -> None:
        client, _ = authed
        other = Organization.objects.create(
            legal_name="Other Sdn Bhd", tin="C99999999999", contact_email="other@example"
        )
        their = _make_item(other)
        response = client.patch(
            f"/api/v1/items/{their.id}/",
            data='{"default_msic_code": "47611"}',
            content_type="application/json",
        )
        assert response.status_code == 404
