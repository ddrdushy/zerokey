"""Tests for admin tenant edit (Slice 40)."""

from __future__ import annotations

import json

import pytest
from django.test import Client

from apps.audit.models import AuditEvent
from apps.identity.models import Organization, Role, User


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
def org(seeded) -> Organization:
    return Organization.objects.create(
        legal_name="Acme",
        tin="C10000000001",
        contact_email="ops@acme.example",
        timezone="Asia/Kuala_Lumpur",
        billing_currency="MYR",
    )


@pytest.mark.django_db
class TestAdminUpdateTenant:
    def _patch(self, client, oid, body):
        return client.patch(
            f"/api/v1/admin/tenants/{oid}/edit/",
            data=json.dumps(body),
            content_type="application/json",
        )

    def test_unauthenticated_rejected(self, org) -> None:
        response = Client().patch(
            f"/api/v1/admin/tenants/{org.id}/edit/",
            data="{}",
            content_type="application/json",
        )
        assert response.status_code in (401, 403)

    def test_customer_403(self, org, seeded) -> None:
        user = User.objects.create_user(email="cust@x", password="x")
        client = Client()
        client.force_login(user)
        response = self._patch(
            client, org.id, {"fields": {"legal_name": "X"}, "reason": "y"}
        )
        assert response.status_code == 403

    def test_update_legal_name_and_contact(self, staff_user, org) -> None:
        client = Client()
        client.force_login(staff_user)
        response = self._patch(
            client,
            org.id,
            {
                "fields": {
                    "legal_name": "Acme (M) Sdn Bhd",
                    "contact_phone": "+60 3 9999 0000",
                },
                "reason": "support ticket #4421 — corporate rebrand",
            },
        )
        assert response.status_code == 200
        org.refresh_from_db()
        assert org.legal_name == "Acme (M) Sdn Bhd"
        assert org.contact_phone == "+60 3 9999 0000"

        event = (
            AuditEvent.objects.filter(action_type="admin.tenant_updated")
            .order_by("-sequence")
            .first()
        )
        assert event.organization_id == org.id
        assert event.affected_entity_id == str(org.id)
        assert event.payload["fields_changed"] == ["contact_phone", "legal_name"]
        # PII (phone, email) is NOT in the audit payload — only field names.
        assert "+60 3 9999 0000" not in json.dumps(event.payload)
        assert "Acme (M) Sdn Bhd" not in json.dumps(event.payload)

    def test_reason_required(self, staff_user, org) -> None:
        client = Client()
        client.force_login(staff_user)
        response = self._patch(
            client, org.id, {"fields": {"legal_name": "Acme 2"}}
        )
        assert response.status_code == 400

    def test_reject_non_editable_field(self, staff_user, org) -> None:
        client = Client()
        client.force_login(staff_user)
        response = self._patch(
            client,
            org.id,
            {"fields": {"tin": "C00000000099"}, "reason": "x"},
        )
        assert response.status_code == 400
        assert "tin" in response.json()["detail"]

    def test_unknown_tenant_404(self, staff_user) -> None:
        client = Client()
        client.force_login(staff_user)
        response = self._patch(
            client,
            "00000000-0000-0000-0000-000000000000",
            {"fields": {"legal_name": "X"}, "reason": "x"},
        )
        assert response.status_code == 404

    def test_no_op_skips_audit(self, staff_user, org) -> None:
        client = Client()
        client.force_login(staff_user)
        before = AuditEvent.objects.filter(
            action_type="admin.tenant_updated"
        ).count()
        # Pass the same legal_name already on the row.
        response = self._patch(
            client,
            org.id,
            {"fields": {"legal_name": "Acme"}, "reason": "no-op"},
        )
        assert response.status_code == 200
        after = AuditEvent.objects.filter(
            action_type="admin.tenant_updated"
        ).count()
        assert before == after

    def test_subscription_state_change(self, staff_user, org) -> None:
        """Operator promotes a trial tenant to active after pre-payment."""
        client = Client()
        client.force_login(staff_user)
        response = self._patch(
            client,
            org.id,
            {
                "fields": {"subscription_state": "active"},
                "reason": "annual prepay received via wire",
            },
        )
        assert response.status_code == 200
        org.refresh_from_db()
        assert org.subscription_state == "active"
