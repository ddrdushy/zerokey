"""Tests for the platform-staff system-settings management surface (Slice 41)."""

from __future__ import annotations

import json

import pytest
from django.test import Client

from apps.administration.models import SystemSetting
from apps.audit.models import AuditEvent
from apps.identity.models import Role, User


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
def stripe_setting(db) -> SystemSetting:
    return SystemSetting.objects.create(
        namespace="stripe",
        values={
            "publishable_key": "pk_live_existing",
            "secret_key": "sk_existing_secret",
            "default_currency": "MYR",
        },
        description="Stripe billing",
    )


@pytest.mark.django_db
class TestAdminListSystemSettings:
    def test_unauthenticated_rejected(self) -> None:
        response = Client().get("/api/v1/admin/system-settings/")
        assert response.status_code in (401, 403)

    def test_customer_403(self, seeded) -> None:
        user = User.objects.create_user(email="cust@x", password="x")
        client = Client()
        client.force_login(user)
        response = client.get("/api/v1/admin/system-settings/")
        assert response.status_code == 403

    def test_staff_lists_namespaces_with_redacted_credentials(
        self, staff_user, stripe_setting
    ) -> None:
        client = Client()
        client.force_login(staff_user)
        response = client.get("/api/v1/admin/system-settings/")
        assert response.status_code == 200
        results = response.json()["results"]
        namespaces = {row["namespace"] for row in results}
        # Every schema namespace appears, even ones without DB rows.
        assert {"lhdn", "stripe", "email", "branding", "engine_defaults"} <= namespaces

        stripe = next(r for r in results if r["namespace"] == "stripe")
        # Non-credential keys present in `values`.
        assert stripe["values"]["publishable_key"] == "pk_live_existing"
        assert stripe["values"]["default_currency"] == "MYR"
        # Credential keys exposed as {key: bool}; values themselves NEVER returned.
        assert stripe["credential_keys"]["secret_key"] is True
        assert "sk_existing_secret" not in json.dumps(results)


@pytest.mark.django_db
class TestAdminUpdateSystemSetting:
    def _patch(self, client, namespace, body):
        return client.patch(
            f"/api/v1/admin/system-settings/{namespace}/",
            data=json.dumps(body),
            content_type="application/json",
        )

    def test_set_credential_key(self, staff_user) -> None:
        client = Client()
        client.force_login(staff_user)
        response = self._patch(
            client,
            "stripe",
            {
                "fields": {"secret_key": "sk_live_rotated"},
                "reason": "production cutover",
            },
        )
        assert response.status_code == 200

        setting = SystemSetting.objects.get(namespace="stripe")
        assert setting.values["secret_key"] == "sk_live_rotated"

        # Audit event records key NAME only, never the value.
        event = (
            AuditEvent.objects.filter(action_type="admin.system_setting_updated")
            .order_by("-sequence")
            .first()
        )
        assert event.payload["namespace"] == "stripe"
        assert event.payload["fields_changed"] == ["secret_key"]
        assert "sk_live_rotated" not in json.dumps(event.payload)

    def test_clear_credential_with_empty_string(
        self, staff_user, stripe_setting
    ) -> None:
        client = Client()
        client.force_login(staff_user)
        response = self._patch(
            client,
            "stripe",
            {"fields": {"secret_key": ""}, "reason": "rotated to new key"},
        )
        assert response.status_code == 200
        stripe_setting.refresh_from_db()
        assert "secret_key" not in stripe_setting.values
        # Other fields untouched.
        assert stripe_setting.values["publishable_key"] == "pk_live_existing"

    def test_set_non_credential_value(self, staff_user) -> None:
        client = Client()
        client.force_login(staff_user)
        response = self._patch(
            client,
            "lhdn",
            {
                "fields": {"base_url": "https://api.myinvois.hasil.gov.my"},
                "reason": "production cutover",
            },
        )
        assert response.status_code == 200
        setting = SystemSetting.objects.get(namespace="lhdn")
        assert setting.values["base_url"] == "https://api.myinvois.hasil.gov.my"

    def test_unknown_namespace_400(self, staff_user) -> None:
        client = Client()
        client.force_login(staff_user)
        response = self._patch(
            client, "supervillain", {"fields": {}, "reason": "x"}
        )
        assert response.status_code == 400

    def test_unknown_field_in_known_namespace_400(self, staff_user) -> None:
        client = Client()
        client.force_login(staff_user)
        response = self._patch(
            client,
            "lhdn",
            {"fields": {"super_secret": "x"}, "reason": "x"},
        )
        assert response.status_code == 400
        assert "super_secret" in response.json()["detail"]

    def test_reason_required(self, staff_user) -> None:
        client = Client()
        client.force_login(staff_user)
        response = self._patch(
            client, "stripe", {"fields": {"default_currency": "MYR"}}
        )
        assert response.status_code == 400

    def test_no_op_skips_audit(self, staff_user, stripe_setting) -> None:
        client = Client()
        client.force_login(staff_user)
        before = AuditEvent.objects.filter(
            action_type="admin.system_setting_updated"
        ).count()
        response = self._patch(
            client,
            "stripe",
            {"fields": {"default_currency": "MYR"}, "reason": "no-op"},
        )
        assert response.status_code == 200
        after = AuditEvent.objects.filter(
            action_type="admin.system_setting_updated"
        ).count()
        assert before == after

    def test_email_smtp_namespace(self, staff_user) -> None:
        """End-to-end on the email/SMTP namespace — common operator task."""
        client = Client()
        client.force_login(staff_user)
        response = self._patch(
            client,
            "email",
            {
                "fields": {
                    "smtp_host": "smtp.eu-west-1.amazonaws.com",
                    "smtp_port": "587",
                    "smtp_user": "AKIA…",
                    "smtp_password": "secret-rotation-1",
                    "from_address": "no-reply@symprio.com",
                    "from_name": "ZeroKey",
                    "use_tls": "true",
                },
                "reason": "switched from postmark to ses",
            },
        )
        assert response.status_code == 200
        setting = SystemSetting.objects.get(namespace="email")
        assert setting.values["smtp_host"] == "smtp.eu-west-1.amazonaws.com"
        assert setting.values["smtp_password"] == "secret-rotation-1"
        # Body wouldn't return the password back.
        body = response.json()
        assert body["credential_keys"]["smtp_password"] is True
        assert "secret-rotation-1" not in json.dumps(body)
