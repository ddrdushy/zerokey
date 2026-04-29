"""Tests for admin membership management (Slice 39)."""

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
def staff_user(seeded) -> User:
    return User.objects.create_user(email="staff@symprio.com", password="x", is_staff=True)


@pytest.fixture
def membership(seeded) -> OrganizationMembership:
    org = Organization.objects.create(
        legal_name="Acme", tin="C10000000001", contact_email="a@a.test"
    )
    user = User.objects.create_user(email="m@a.test", password="x")
    return OrganizationMembership.objects.create(
        user=user,
        organization=org,
        role=Role.objects.get(name="owner"),
        is_active=True,
    )


@pytest.mark.django_db
class TestAdminUpdateMembership:
    def _patch(self, client, mid, body):
        return client.patch(
            f"/api/v1/admin/memberships/{mid}/",
            data=json.dumps(body),
            content_type="application/json",
        )

    def test_unauthenticated_rejected(self, membership) -> None:
        response = Client().patch(
            f"/api/v1/admin/memberships/{membership.id}/",
            data="{}",
            content_type="application/json",
        )
        assert response.status_code in (401, 403)

    def test_customer_403(self, membership, seeded) -> None:
        user = User.objects.create_user(email="cust@x", password="x")
        client = Client()
        client.force_login(user)
        response = self._patch(client, membership.id, {"reason": "x"})
        assert response.status_code == 403

    def test_deactivate_membership(self, staff_user, membership) -> None:
        client = Client()
        client.force_login(staff_user)
        response = self._patch(
            client,
            membership.id,
            {"is_active": False, "reason": "departed employee"},
        )
        assert response.status_code == 200
        membership.refresh_from_db()
        assert membership.is_active is False

        event = (
            AuditEvent.objects.filter(action_type="admin.membership_updated")
            .order_by("-sequence")
            .first()
        )
        assert event.affected_entity_id == str(membership.id)
        assert event.payload["fields_changed"] == ["is_active"]
        assert event.payload["reason"] == "departed employee"

    def test_change_role(self, staff_user, membership) -> None:
        client = Client()
        client.force_login(staff_user)
        response = self._patch(
            client,
            membership.id,
            {"role_name": "viewer", "reason": "demote"},
        )
        assert response.status_code == 200
        membership.refresh_from_db()
        assert membership.role.name == "viewer"

        event = (
            AuditEvent.objects.filter(action_type="admin.membership_updated")
            .order_by("-sequence")
            .first()
        )
        assert "role" in event.payload["fields_changed"]

    def test_reason_required(self, staff_user, membership) -> None:
        client = Client()
        client.force_login(staff_user)
        response = self._patch(client, membership.id, {"is_active": False})
        assert response.status_code == 400
        assert "reason" in response.json()["detail"].lower()

    def test_at_least_one_field_required(self, staff_user, membership) -> None:
        client = Client()
        client.force_login(staff_user)
        response = self._patch(client, membership.id, {"reason": "x"})
        assert response.status_code == 400

    def test_unknown_role_400(self, staff_user, membership) -> None:
        client = Client()
        client.force_login(staff_user)
        response = self._patch(
            client,
            membership.id,
            {"role_name": "supervillain", "reason": "x"},
        )
        assert response.status_code == 400

    def test_unknown_membership_404(self, staff_user) -> None:
        client = Client()
        client.force_login(staff_user)
        response = self._patch(
            client,
            "00000000-0000-0000-0000-000000000000",
            {"is_active": False, "reason": "x"},
        )
        assert response.status_code == 404

    def test_no_op_skips_audit(self, staff_user, membership) -> None:
        client = Client()
        client.force_login(staff_user)
        before = AuditEvent.objects.filter(action_type="admin.membership_updated").count()
        # is_active is already True, role is already owner — nothing changes.
        response = self._patch(
            client,
            membership.id,
            {"is_active": True, "role_name": "owner", "reason": "no-op"},
        )
        assert response.status_code == 200
        after = AuditEvent.objects.filter(action_type="admin.membership_updated").count()
        assert before == after
