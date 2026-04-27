"""End-to-end tests for the auth flow + audit signal wiring.

These exercise the full request → service → audit-log path so that any future
refactor that drops the audit signal (or skips ``record_event``) breaks loudly.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.audit.models import AuditEvent
from apps.identity.models import OrganizationMembership, Role, User

REGISTRATION_PAYLOAD = {
    "email": "owner@acme.example",
    "password": "long-enough-password",
    "organization_legal_name": "ACME Sdn Bhd",
    "organization_tin": "C20880050010",
    "contact_email": "ops@acme.example",
}


@pytest.fixture
def seeded_roles(db) -> None:
    """Seed the five system roles. The 0003 data migration handles this in real
    deployments; tests with the in-memory sqlite db re-seed manually because
    pytest-django wipes between tests."""
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.mark.django_db
class TestRegister:
    def test_creates_user_organization_and_membership(self, seeded_roles) -> None:
        response = Client().post(
            "/api/v1/identity/register/",
            data=REGISTRATION_PAYLOAD,
            content_type="application/json",
        )
        assert response.status_code == 201, response.content
        body = response.json()
        assert body["email"] == "owner@acme.example"
        assert len(body["memberships"]) == 1
        assert body["memberships"][0]["role"] == "owner"
        assert body["active_organization_id"] is not None

        # And the rows exist.
        user = User.objects.get(email="owner@acme.example")
        membership = OrganizationMembership.objects.get(user=user)
        assert membership.role.name == "owner"

    def test_emits_three_audit_events_in_order(self, seeded_roles) -> None:
        Client().post(
            "/api/v1/identity/register/",
            data=REGISTRATION_PAYLOAD,
            content_type="application/json",
        )
        actions = list(
            AuditEvent.objects.order_by("sequence").values_list("action_type", flat=True)
        )
        # The first three are registration; the fourth is auto-login.
        assert actions[:3] == [
            "identity.user.registered",
            "identity.organization.created",
            "identity.membership.created",
        ]
        assert "auth.login_success" in actions

    def test_duplicate_email_is_rejected(self, seeded_roles) -> None:
        client = Client()
        client.post(
            "/api/v1/identity/register/",
            data=REGISTRATION_PAYLOAD,
            content_type="application/json",
        )
        # Same email, different TIN.
        response = client.post(
            "/api/v1/identity/register/",
            data={**REGISTRATION_PAYLOAD, "organization_tin": "C99999999999"},
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]


@pytest.mark.django_db
class TestLoginLogout:
    def test_login_success_records_audit_event(self, seeded_roles) -> None:
        client = Client()
        client.post(
            "/api/v1/identity/register/",
            data=REGISTRATION_PAYLOAD,
            content_type="application/json",
        )
        # Log out the auto-logged-in session, then log back in.
        client.post("/api/v1/identity/logout/")
        AuditEvent.objects.all().delete()  # isolate the fresh login event
        # ^ Note: in production AuditEvent rows cannot be deleted via the model;
        # this test uses the QuerySet path which bypasses the model save/delete
        # guard. A separate test asserts the model-level immutability holds.

        response = client.post(
            "/api/v1/identity/login/",
            data={"email": "owner@acme.example", "password": "long-enough-password"},
            content_type="application/json",
        )
        assert response.status_code == 200
        login_events = AuditEvent.objects.filter(action_type="auth.login_success")
        assert login_events.count() == 1

    def test_login_failure_records_audit_event(self, seeded_roles) -> None:
        # Register so the user exists; we deliberately use the wrong password.
        Client().post(
            "/api/v1/identity/register/",
            data=REGISTRATION_PAYLOAD,
            content_type="application/json",
        )
        AuditEvent.objects.all().delete()

        response = Client().post(
            "/api/v1/identity/login/",
            data={"email": "owner@acme.example", "password": "WRONG"},
            content_type="application/json",
        )
        assert response.status_code == 401
        failed = AuditEvent.objects.filter(action_type="auth.login_failed").first()
        assert failed is not None
        # The password must NOT appear in the payload.
        assert "WRONG" not in str(failed.payload)
        assert failed.payload.get("email_attempted") == "owner@acme.example"

    def test_logout_records_audit_event_and_ends_session(self, seeded_roles) -> None:
        client = Client()
        client.post(
            "/api/v1/identity/register/",
            data=REGISTRATION_PAYLOAD,
            content_type="application/json",
        )
        AuditEvent.objects.all().delete()

        response = client.post("/api/v1/identity/logout/")
        assert response.status_code == 204
        assert AuditEvent.objects.filter(action_type="auth.logout").count() == 1

        # Subsequent /me must be unauthenticated.
        me = client.get("/api/v1/identity/me/")
        assert me.status_code in (401, 403)


@pytest.mark.django_db
class TestMeAndSwitchOrganization:
    def test_me_returns_current_user_and_active_org(self, seeded_roles) -> None:
        client = Client()
        register = client.post(
            "/api/v1/identity/register/",
            data=REGISTRATION_PAYLOAD,
            content_type="application/json",
        )
        org_id = register.json()["active_organization_id"]
        me = client.get("/api/v1/identity/me/")
        assert me.status_code == 200
        body = me.json()
        assert body["email"] == "owner@acme.example"
        assert body["active_organization_id"] == org_id

    def test_switch_organization_rejects_unrelated_org(self, seeded_roles) -> None:
        import uuid

        client = Client()
        client.post(
            "/api/v1/identity/register/",
            data=REGISTRATION_PAYLOAD,
            content_type="application/json",
        )
        # Random UUID — user has no membership.
        response = client.post(
            "/api/v1/identity/switch-organization/",
            data={"organization_id": str(uuid.uuid4())},
            content_type="application/json",
        )
        assert response.status_code == 403
