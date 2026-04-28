"""Tests for the customer-side Members tab (Slice 45)."""

from __future__ import annotations

import json

import pytest
from django.test import Client

from apps.audit.models import AuditEvent
from apps.identity.models import Organization, OrganizationMembership, Role, User


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org(seeded) -> Organization:
    return Organization.objects.create(
        legal_name="Acme", tin="C10000000001", contact_email="ops@acme"
    )


def _membership(org: Organization, email: str, role_name: str = "viewer") -> OrganizationMembership:
    user = User.objects.create_user(email=email, password="x")
    return OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name=role_name)
    )


@pytest.fixture
def owner_membership(org) -> OrganizationMembership:
    return _membership(org, "owner@a.test", "owner")


@pytest.fixture
def admin_membership(org) -> OrganizationMembership:
    return _membership(org, "admin@a.test", "admin")


@pytest.fixture
def viewer_membership(org) -> OrganizationMembership:
    return _membership(org, "viewer@a.test", "viewer")


def _client_for(membership: OrganizationMembership) -> Client:
    client = Client()
    client.force_login(membership.user)
    session = client.session
    session["organization_id"] = str(membership.organization_id)
    session.save()
    return client


@pytest.mark.django_db
class TestListMembers:
    def test_unauthenticated_rejected(self, org) -> None:
        response = Client().get("/api/v1/identity/organization/members/")
        assert response.status_code in (401, 403)

    def test_no_active_org_400(self, seeded) -> None:
        u = User.objects.create_user(email="u@x", password="x")
        client = Client()
        client.force_login(u)
        response = client.get("/api/v1/identity/organization/members/")
        assert response.status_code == 400

    def test_member_can_list(
        self, owner_membership, admin_membership, viewer_membership
    ) -> None:
        client = _client_for(viewer_membership)
        response = client.get("/api/v1/identity/organization/members/")
        assert response.status_code == 200
        results = response.json()["results"]
        emails = {m["email"] for m in results}
        assert {"owner@a.test", "admin@a.test", "viewer@a.test"} <= emails


@pytest.mark.django_db
class TestPatchMember:
    def _patch(self, client, mid, body):
        return client.patch(
            f"/api/v1/identity/organization/members/{mid}/",
            data=json.dumps(body),
            content_type="application/json",
        )

    def test_owner_can_change_admin_role(
        self, owner_membership, admin_membership
    ) -> None:
        client = _client_for(owner_membership)
        response = self._patch(
            client, admin_membership.id, {"role_name": "viewer"}
        )
        assert response.status_code == 200
        admin_membership.refresh_from_db()
        assert admin_membership.role.name == "viewer"

    def test_owner_can_deactivate_member(
        self, owner_membership, viewer_membership
    ) -> None:
        client = _client_for(owner_membership)
        response = self._patch(
            client, viewer_membership.id, {"is_active": False}
        )
        assert response.status_code == 200
        viewer_membership.refresh_from_db()
        assert viewer_membership.is_active is False

        # Customer-side audit event distinguishes from admin path.
        event = (
            AuditEvent.objects.filter(action_type="organization.membership.updated")
            .order_by("-sequence")
            .first()
        )
        assert event.organization_id == owner_membership.organization_id
        assert event.affected_entity_id == str(viewer_membership.id)
        assert event.payload["fields_changed"] == ["is_active"]

    def test_admin_cannot_change_owner(
        self, owner_membership, admin_membership
    ) -> None:
        client = _client_for(admin_membership)
        response = self._patch(
            client, owner_membership.id, {"role_name": "viewer"}
        )
        assert response.status_code == 403

    def test_admin_cannot_promote_to_owner(
        self, admin_membership, viewer_membership
    ) -> None:
        client = _client_for(admin_membership)
        response = self._patch(
            client, viewer_membership.id, {"role_name": "owner"}
        )
        assert response.status_code == 403
        assert "owner" in response.json()["detail"].lower()

    def test_owner_can_promote_to_owner(
        self, owner_membership, viewer_membership
    ) -> None:
        client = _client_for(owner_membership)
        response = self._patch(
            client, viewer_membership.id, {"role_name": "owner"}
        )
        assert response.status_code == 200

    def test_viewer_cannot_change_anyone(
        self, viewer_membership, admin_membership
    ) -> None:
        client = _client_for(viewer_membership)
        response = self._patch(
            client, admin_membership.id, {"role_name": "viewer"}
        )
        assert response.status_code == 403

    def test_self_change_rejected(self, owner_membership) -> None:
        """Owners cannot demote / deactivate themselves through this route."""
        client = _client_for(owner_membership)
        response = self._patch(
            client, owner_membership.id, {"role_name": "viewer"}
        )
        assert response.status_code == 403
        assert "your own" in response.json()["detail"].lower()

    def test_unknown_membership_404(self, owner_membership) -> None:
        client = _client_for(owner_membership)
        response = self._patch(
            client,
            "00000000-0000-0000-0000-000000000000",
            {"role_name": "viewer"},
        )
        assert response.status_code == 404

    def test_unknown_role_400(
        self, owner_membership, viewer_membership
    ) -> None:
        client = _client_for(owner_membership)
        response = self._patch(
            client, viewer_membership.id, {"role_name": "supervillain"}
        )
        assert response.status_code == 400

    def test_at_least_one_field_required(
        self, owner_membership, viewer_membership
    ) -> None:
        client = _client_for(owner_membership)
        response = self._patch(client, viewer_membership.id, {})
        assert response.status_code == 400

    def test_no_op_does_not_audit(
        self, owner_membership, viewer_membership
    ) -> None:
        client = _client_for(owner_membership)
        before = AuditEvent.objects.filter(
            action_type="organization.membership.updated"
        ).count()
        response = self._patch(
            client, viewer_membership.id, {"role_name": "viewer", "is_active": True}
        )
        assert response.status_code == 200
        after = AuditEvent.objects.filter(
            action_type="organization.membership.updated"
        ).count()
        assert before == after

    def test_cross_org_membership_404(
        self, owner_membership, seeded
    ) -> None:
        """Membership in a different org is not visible here."""
        other_org = Organization.objects.create(
            legal_name="Beta", tin="C99999999999", contact_email="b@b"
        )
        other = _membership(other_org, "x@b.test", "viewer")
        client = _client_for(owner_membership)
        response = self._patch(
            client, other.id, {"role_name": "admin"}
        )
        assert response.status_code == 404
