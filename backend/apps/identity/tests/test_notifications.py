"""Tests for the notification-preferences surface (Slice 47)."""

from __future__ import annotations

import json

import pytest
from django.test import Client

from apps.audit.models import AuditEvent
from apps.identity.models import (
    NotificationPreference,
    Organization,
    OrganizationMembership,
    Role,
    User,
)
from apps.identity.notifications import EVENT_KEYS


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org_user(seeded) -> tuple[Organization, User]:
    org = Organization.objects.create(
        legal_name="Acme", tin="C10000000001", contact_email="ops@acme"
    )
    user = User.objects.create_user(email="o@a.test", password="x")
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name="owner")
    )
    return org, user


def _client(org_user) -> Client:
    org, user = org_user
    client = Client()
    client.force_login(user)
    session = client.session
    session["organization_id"] = str(org.id)
    session.save()
    return client


@pytest.mark.django_db
class TestGetPreferences:
    def test_unauthenticated_rejected(self) -> None:
        response = Client().get(
            "/api/v1/identity/organization/notification-preferences/"
        )
        assert response.status_code in (401, 403)

    def test_returns_full_event_schema_with_defaults(self, org_user) -> None:
        client = _client(org_user)
        response = client.get(
            "/api/v1/identity/organization/notification-preferences/"
        )
        assert response.status_code == 200
        body = response.json()
        keys_in_response = {e["key"] for e in body["events"]}
        keys_in_schema = {key for key, _, _ in EVENT_KEYS}
        assert keys_in_schema == keys_in_response
        # Defaults: every channel on for every event.
        for event in body["events"]:
            assert event["in_app"] is True
            assert event["email"] is True

    def test_first_get_materialises_row(self, org_user) -> None:
        org, user = org_user
        assert (
            NotificationPreference.objects.filter(
                user=user, organization_id=org.id
            ).count()
            == 0
        )
        client = _client(org_user)
        client.get("/api/v1/identity/organization/notification-preferences/")
        assert (
            NotificationPreference.objects.filter(
                user=user, organization_id=org.id
            ).count()
            == 1
        )


@pytest.mark.django_db
class TestSetPreferences:
    def _patch(self, client, body):
        return client.patch(
            "/api/v1/identity/organization/notification-preferences/",
            data=json.dumps(body),
            content_type="application/json",
        )

    def test_disable_email_for_one_event(self, org_user) -> None:
        client = _client(org_user)
        response = self._patch(
            client,
            {"inbox.item_opened": {"in_app": True, "email": False}},
        )
        assert response.status_code == 200
        body = response.json()
        inbox_pref = next(
            e for e in body["events"] if e["key"] == "inbox.item_opened"
        )
        assert inbox_pref["in_app"] is True
        assert inbox_pref["email"] is False
        # Other events untouched (defaults — both channels on).
        validated = next(
            e for e in body["events"] if e["key"] == "invoice.validated"
        )
        assert validated["email"] is True

    def test_unknown_event_key_rejected(self, org_user) -> None:
        client = _client(org_user)
        response = self._patch(
            client,
            {"made.up.event": {"in_app": False}},
        )
        assert response.status_code == 400

    def test_unknown_channel_silently_dropped(self, org_user) -> None:
        """Future channels (push, sms) might land before the FE knows;
        we drop unknowns rather than rejecting so a stale FE doesn't
        block the save."""
        client = _client(org_user)
        response = self._patch(
            client,
            {
                "inbox.item_opened": {
                    "in_app": False,
                    "email": True,
                    "push": True,  # not in VALID_CHANNELS
                }
            },
        )
        assert response.status_code == 200
        body = response.json()
        inbox = next(
            e for e in body["events"] if e["key"] == "inbox.item_opened"
        )
        assert inbox["in_app"] is False
        assert inbox["email"] is True

    def test_audit_event_records_event_keys_only(self, org_user) -> None:
        client = _client(org_user)
        self._patch(
            client,
            {"audit.chain_verified": {"in_app": True, "email": False}},
        )
        event = (
            AuditEvent.objects.filter(
                action_type="identity.notification_preferences.updated"
            )
            .order_by("-sequence")
            .first()
        )
        assert event.payload["event_keys_changed"] == ["audit.chain_verified"]
        # No values in payload — false/true booleans not present.
        assert "true" not in json.dumps(event.payload).lower()
        assert "false" not in json.dumps(event.payload).lower()

    def test_no_op_does_not_audit(self, org_user) -> None:
        client = _client(org_user)
        # First save, then re-save same.
        self._patch(
            client,
            {"inbox.item_opened": {"in_app": False, "email": False}},
        )
        before = AuditEvent.objects.filter(
            action_type="identity.notification_preferences.updated"
        ).count()
        self._patch(
            client,
            {"inbox.item_opened": {"in_app": False, "email": False}},
        )
        after = AuditEvent.objects.filter(
            action_type="identity.notification_preferences.updated"
        ).count()
        assert after == before

    def test_per_user_per_org_isolation(self, seeded) -> None:
        """Same user belonging to two orgs has separate preferences rows."""
        u = User.objects.create_user(email="dual@x", password="x")
        org_a = Organization.objects.create(
            legal_name="A", tin="C10000000001", contact_email="a"
        )
        org_b = Organization.objects.create(
            legal_name="B", tin="C99999999999", contact_email="b"
        )
        OrganizationMembership.objects.create(
            user=u, organization=org_a, role=Role.objects.get(name="owner")
        )
        OrganizationMembership.objects.create(
            user=u, organization=org_b, role=Role.objects.get(name="viewer")
        )

        # Disable email on inbox events while in org A.
        client = Client()
        client.force_login(u)
        session = client.session
        session["organization_id"] = str(org_a.id)
        session.save()
        client.patch(
            "/api/v1/identity/organization/notification-preferences/",
            data=json.dumps(
                {"inbox.item_opened": {"in_app": True, "email": False}}
            ),
            content_type="application/json",
        )

        # Switch to org B; the preference shouldn't carry over.
        session = client.session
        session["organization_id"] = str(org_b.id)
        session.save()
        response = client.get(
            "/api/v1/identity/organization/notification-preferences/"
        )
        body = response.json()
        inbox = next(
            e for e in body["events"] if e["key"] == "inbox.item_opened"
        )
        # Org B still has defaults — email on.
        assert inbox["email"] is True
