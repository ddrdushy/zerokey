"""Tests for the webhook surface (Slice 49)."""

from __future__ import annotations

import json

import pytest
from django.test import Client

from apps.audit.models import AuditEvent
from apps.identity.models import Organization, OrganizationMembership, Role, User
from apps.integrations.models import WebhookDelivery, WebhookEndpoint


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org_user(seeded) -> tuple[Organization, User]:
    org = Organization.objects.create(
        legal_name="Acme", tin="C10000000001", contact_email="o@a"
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
class TestCreateWebhook:
    def test_unauthenticated_rejected(self) -> None:
        response = Client().post(
            "/api/v1/integrations/webhooks/",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code in (401, 403)

    def test_create_returns_plaintext_once(self, org_user) -> None:
        client = _client(org_user)
        response = client.post(
            "/api/v1/integrations/webhooks/",
            data=json.dumps(
                {
                    "label": "zapier-prod",
                    "url": "https://hooks.zapier.com/abc/123",
                    "event_types": ["invoice.created", "invoice.lhdn_rejected"],
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 201
        body = response.json()
        plaintext = body["plaintext_secret"]
        assert plaintext.startswith("whsec_")
        assert body["secret_prefix"] == plaintext[: len(body["secret_prefix"])]

        row = WebhookEndpoint.objects.get(id=body["id"])
        assert row.label == "zapier-prod"
        assert row.url == "https://hooks.zapier.com/abc/123"
        assert row.event_types == ["invoice.created", "invoice.lhdn_rejected"]
        # Plaintext NOT stored anywhere on the row.
        assert plaintext not in row.secret_hash
        assert plaintext not in row.secret_prefix

    def test_invalid_url_rejected(self, org_user) -> None:
        client = _client(org_user)
        response = client.post(
            "/api/v1/integrations/webhooks/",
            data=json.dumps({"label": "x", "url": "ftp://nope.example"}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_unknown_event_type_rejected(self, org_user) -> None:
        client = _client(org_user)
        response = client.post(
            "/api/v1/integrations/webhooks/",
            data=json.dumps(
                {
                    "label": "x",
                    "url": "https://example.com/h",
                    "event_types": ["totally.fake"],
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_list_does_not_return_plaintext(self, org_user) -> None:
        client = _client(org_user)
        create = client.post(
            "/api/v1/integrations/webhooks/",
            data=json.dumps(
                {"label": "x", "url": "https://example.com/h"}
            ),
            content_type="application/json",
        )
        plaintext = create.json()["plaintext_secret"]

        listing = client.get("/api/v1/integrations/webhooks/")
        assert listing.status_code == 200
        body_text = json.dumps(listing.json())
        assert plaintext not in body_text


@pytest.mark.django_db
class TestRevoke:
    def _create(self, client) -> str:
        response = client.post(
            "/api/v1/integrations/webhooks/",
            data=json.dumps({"label": "x", "url": "https://e.com/h"}),
            content_type="application/json",
        )
        return response.json()["id"]

    def test_revoke_flips_active(self, org_user) -> None:
        client = _client(org_user)
        webhook_id = self._create(client)
        response = client.delete(
            f"/api/v1/integrations/webhooks/{webhook_id}/"
        )
        assert response.status_code == 200
        row = WebhookEndpoint.objects.get(id=webhook_id)
        assert row.is_active is False
        assert row.revoked_at is not None

    def test_revoke_unknown_404(self, org_user) -> None:
        client = _client(org_user)
        response = client.delete(
            "/api/v1/integrations/webhooks/00000000-0000-0000-0000-000000000000/"
        )
        assert response.status_code == 404


@pytest.mark.django_db
class TestTestDelivery:
    def test_creates_synthetic_delivery_row(self, org_user) -> None:
        client = _client(org_user)
        create = client.post(
            "/api/v1/integrations/webhooks/",
            data=json.dumps({"label": "x", "url": "https://e.com/h"}),
            content_type="application/json",
        )
        webhook_id = create.json()["id"]
        response = client.post(
            f"/api/v1/integrations/webhooks/{webhook_id}/test/"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["outcome"] == "success"
        assert body["event_type"] == "ping"
        # A row exists.
        assert WebhookDelivery.objects.filter(id=body["id"]).exists()

    def test_test_audit_event_recorded(self, org_user) -> None:
        client = _client(org_user)
        create = client.post(
            "/api/v1/integrations/webhooks/",
            data=json.dumps({"label": "x", "url": "https://e.com/h"}),
            content_type="application/json",
        )
        webhook_id = create.json()["id"]
        client.post(f"/api/v1/integrations/webhooks/{webhook_id}/test/")
        event = (
            AuditEvent.objects.filter(action_type="integrations.webhook.test_sent")
            .order_by("-sequence")
            .first()
        )
        assert event is not None
        assert event.affected_entity_id == webhook_id


@pytest.mark.django_db
class TestDeliveriesList:
    def test_filters_by_webhook_id(self, org_user) -> None:
        client = _client(org_user)
        a = client.post(
            "/api/v1/integrations/webhooks/",
            data=json.dumps({"label": "a", "url": "https://e.com/a"}),
            content_type="application/json",
        ).json()["id"]
        b = client.post(
            "/api/v1/integrations/webhooks/",
            data=json.dumps({"label": "b", "url": "https://e.com/b"}),
            content_type="application/json",
        ).json()["id"]
        client.post(f"/api/v1/integrations/webhooks/{a}/test/")
        client.post(f"/api/v1/integrations/webhooks/{a}/test/")
        client.post(f"/api/v1/integrations/webhooks/{b}/test/")

        all_deliveries = client.get("/api/v1/integrations/deliveries/")
        assert len(all_deliveries.json()["results"]) == 3
        only_a = client.get(f"/api/v1/integrations/deliveries/?webhook_id={a}")
        assert len(only_a.json()["results"]) == 2
