"""Tests for admin tenant impersonation (Slice 43)."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.administration.models import ImpersonationSession
from apps.audit.models import AuditEvent
from apps.identity.models import Organization, OrganizationMembership, Role, User


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def staff_user(seeded) -> User:
    return User.objects.create_user(
        email="staff@symprio.com", password="x", is_staff=True
    )


@pytest.fixture
def tenant(seeded) -> Organization:
    org = Organization.objects.create(
        legal_name="Acme",
        tin="C10000000001",
        contact_email="ops@acme.example",
    )
    user = User.objects.create_user(email="a@acme.example", password="x")
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name="owner")
    )
    return org


@pytest.mark.django_db
class TestStartImpersonation:
    def _post(self, client, oid, body):
        return client.post(
            f"/api/v1/admin/tenants/{oid}/impersonate/",
            data=json.dumps(body),
            content_type="application/json",
        )

    def test_unauthenticated_rejected(self, tenant) -> None:
        response = Client().post(
            f"/api/v1/admin/tenants/{tenant.id}/impersonate/",
            data="{}",
            content_type="application/json",
        )
        assert response.status_code in (401, 403)

    def test_customer_403(self, tenant, seeded) -> None:
        user = User.objects.create_user(email="cust@x", password="x")
        client = Client()
        client.force_login(user)
        response = self._post(
            client, tenant.id, {"reason": "support ticket #1"}
        )
        assert response.status_code == 403

    def test_reason_required(self, staff_user, tenant) -> None:
        client = Client()
        client.force_login(staff_user)
        response = self._post(client, tenant.id, {})
        assert response.status_code == 400

    def test_unknown_tenant_404(self, staff_user) -> None:
        client = Client()
        client.force_login(staff_user)
        response = self._post(
            client,
            "00000000-0000-0000-0000-000000000000",
            {"reason": "x"},
        )
        assert response.status_code == 404

    def test_starts_session_and_sets_django_session_keys(
        self, staff_user, tenant
    ) -> None:
        client = Client()
        client.force_login(staff_user)
        response = self._post(
            client, tenant.id, {"reason": "support ticket #4421"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["organization_id"] == str(tenant.id)
        assert body["redirect_to"] == "/dashboard"
        # An ImpersonationSession row exists, active, with the reason.
        session = ImpersonationSession.objects.get(id=body["session_id"])
        assert session.reason == "support ticket #4421"
        assert session.is_active is True
        assert session.organization_id == tenant.id
        # Django session has the impersonation pointer + active org.
        assert client.session["impersonation_session_id"] == str(session.id)
        assert client.session["organization_id"] == str(tenant.id)
        # Audit start event recorded.
        event = (
            AuditEvent.objects.filter(
                action_type="admin.tenant_impersonation_started"
            )
            .order_by("-sequence")
            .first()
        )
        assert event.organization_id == tenant.id
        assert event.affected_entity_id == str(session.id)
        assert event.payload["tenant_legal_name"] == "Acme"
        assert event.payload["reason"] == "support ticket #4421"
        assert event.payload["ttl_minutes"] == 30

    def test_starting_second_impersonation_supersedes_first(
        self, staff_user, tenant, seeded
    ) -> None:
        """Same staff, second start, first row gets ended_at + end_reason."""
        client = Client()
        client.force_login(staff_user)
        # First impersonation
        first = self._post(client, tenant.id, {"reason": "first"})
        assert first.status_code == 200
        first_session_id = first.json()["session_id"]

        # Second tenant
        org2 = Organization.objects.create(
            legal_name="Beta", tin="C99999999999", contact_email="b@b"
        )
        second = self._post(client, org2.id, {"reason": "second"})
        assert second.status_code == 200

        first_row = ImpersonationSession.objects.get(id=first_session_id)
        assert first_row.ended_at is not None
        assert first_row.end_reason == "superseded_by_new_session"


@pytest.mark.django_db
class TestEndImpersonation:
    def test_end_clears_django_session_and_audits(
        self, staff_user, tenant
    ) -> None:
        client = Client()
        client.force_login(staff_user)
        # Start one
        client.post(
            f"/api/v1/admin/tenants/{tenant.id}/impersonate/",
            data=json.dumps({"reason": "x"}),
            content_type="application/json",
        )
        sid = client.session["impersonation_session_id"]
        # End it
        response = client.post("/api/v1/admin/impersonation/end/")
        assert response.status_code == 200
        assert response.json()["redirect_to"] == "/admin"
        # Django session keys cleared.
        assert "impersonation_session_id" not in client.session
        assert "organization_id" not in client.session
        # Row marked ended_at.
        row = ImpersonationSession.objects.get(id=sid)
        assert row.ended_at is not None
        assert row.end_reason == "user_ended"
        # End event in the audit chain.
        event = (
            AuditEvent.objects.filter(
                action_type="admin.tenant_impersonation_ended"
            )
            .order_by("-sequence")
            .first()
        )
        assert event.affected_entity_id == sid
        assert event.payload["end_reason"] == "user_ended"

    def test_end_when_no_active_is_noop(self, staff_user) -> None:
        client = Client()
        client.force_login(staff_user)
        response = client.post("/api/v1/admin/impersonation/end/")
        assert response.status_code == 200


@pytest.mark.django_db
class TestImpersonationOnMe:
    """The /me/ endpoint exposes the active impersonation context."""

    def test_me_includes_impersonation_when_active(
        self, staff_user, tenant
    ) -> None:
        client = Client()
        client.force_login(staff_user)
        client.post(
            f"/api/v1/admin/tenants/{tenant.id}/impersonate/",
            data=json.dumps({"reason": "support ticket #4421"}),
            content_type="application/json",
        )
        response = client.get("/api/v1/identity/me/")
        body = response.json()
        assert body["impersonation"] is not None
        assert body["impersonation"]["organization_id"] == str(tenant.id)
        assert body["impersonation"]["tenant_legal_name"] == "Acme"
        assert body["impersonation"]["reason"] == "support ticket #4421"
        assert body["active_organization_id"] == str(tenant.id)

    def test_me_returns_null_after_end(self, staff_user, tenant) -> None:
        client = Client()
        client.force_login(staff_user)
        client.post(
            f"/api/v1/admin/tenants/{tenant.id}/impersonate/",
            data=json.dumps({"reason": "x"}),
            content_type="application/json",
        )
        client.post("/api/v1/admin/impersonation/end/")
        response = client.get("/api/v1/identity/me/")
        assert response.json()["impersonation"] is None

    def test_expired_session_auto_ends(self, staff_user, tenant) -> None:
        """Past expires_at → /me/ auto-ends the row and clears Django session."""
        client = Client()
        client.force_login(staff_user)
        client.post(
            f"/api/v1/admin/tenants/{tenant.id}/impersonate/",
            data=json.dumps({"reason": "x"}),
            content_type="application/json",
        )
        sid = client.session["impersonation_session_id"]

        # Force-expire the row by rewriting expires_at into the past.
        ImpersonationSession.objects.filter(id=sid).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )

        response = client.get("/api/v1/identity/me/")
        assert response.json()["impersonation"] is None
        # The row got ended with end_reason="expired".
        row = ImpersonationSession.objects.get(id=sid)
        assert row.ended_at is not None
        assert row.end_reason == "expired"
