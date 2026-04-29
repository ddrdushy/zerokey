"""Tests for the webhook surface (Slice 49 + Slice 53 delivery)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest
from django.test import Client

from apps.audit.models import AuditEvent
from apps.identity.models import Organization, OrganizationMembership, Role, User
from apps.integrations.models import WebhookDelivery, WebhookEndpoint


def _mock_response(status_code: int = 200, body: str = "ok") -> MagicMock:
    """Build a fake httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = body
    return resp


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
    def test_test_delivery_fires_real_http(self, org_user) -> None:
        client = _client(org_user)
        create = client.post(
            "/api/v1/integrations/webhooks/",
            data=json.dumps({"label": "x", "url": "https://e.com/h"}),
            content_type="application/json",
        )
        webhook_id = create.json()["id"]
        with patch(
            "apps.integrations.delivery.httpx.post",
            return_value=_mock_response(200, "ok"),
        ) as posted:
            response = client.post(
                f"/api/v1/integrations/webhooks/{webhook_id}/test/"
            )
        assert response.status_code == 200
        body = response.json()
        assert body["outcome"] == "success"
        assert body["event_type"] == "ping"
        assert body["response_status"] == 200
        # We actually called httpx.post against the registered URL.
        assert posted.call_count == 1
        assert posted.call_args.args[0] == "https://e.com/h"
        # A row exists with the SUCCESS outcome.
        row = WebhookDelivery.objects.get(id=body["id"])
        assert row.outcome == "success"
        assert row.response_status == 200

    def test_test_delivery_failure_records_failure_outcome(
        self, org_user
    ) -> None:
        client = _client(org_user)
        create = client.post(
            "/api/v1/integrations/webhooks/",
            data=json.dumps({"label": "x", "url": "https://e.com/h"}),
            content_type="application/json",
        )
        webhook_id = create.json()["id"]
        with patch(
            "apps.integrations.delivery.httpx.post",
            return_value=_mock_response(500, "boom"),
        ):
            response = client.post(
                f"/api/v1/integrations/webhooks/{webhook_id}/test/"
            )
        assert response.status_code == 200
        body = response.json()
        assert body["outcome"] == "failure"
        assert body["response_status"] == 500
        assert "HTTP 500" in body["error_class"]

    def test_test_delivery_network_error_recorded(self, org_user) -> None:
        client = _client(org_user)
        create = client.post(
            "/api/v1/integrations/webhooks/",
            data=json.dumps({"label": "x", "url": "https://e.com/h"}),
            content_type="application/json",
        )
        webhook_id = create.json()["id"]
        with patch(
            "apps.integrations.delivery.httpx.post",
            side_effect=httpx.ConnectError("refused"),
        ):
            response = client.post(
                f"/api/v1/integrations/webhooks/{webhook_id}/test/"
            )
        body = response.json()
        assert body["outcome"] == "failure"
        # Error class only — never str(exc) (tested explicitly).
        assert body["error_class"] == "ConnectError"
        assert "refused" not in body["error_class"]

    def test_test_audit_event_recorded(self, org_user) -> None:
        client = _client(org_user)
        create = client.post(
            "/api/v1/integrations/webhooks/",
            data=json.dumps({"label": "x", "url": "https://e.com/h"}),
            content_type="application/json",
        )
        webhook_id = create.json()["id"]
        with patch(
            "apps.integrations.delivery.httpx.post",
            return_value=_mock_response(200, "ok"),
        ):
            client.post(f"/api/v1/integrations/webhooks/{webhook_id}/test/")
        event = (
            AuditEvent.objects.filter(action_type="integrations.webhook.test_sent")
            .order_by("-sequence")
            .first()
        )
        assert event is not None
        assert event.affected_entity_id == webhook_id
        # Test-send audit captures success/status_code (Slice 53).
        assert event.payload["ok"] is True
        assert event.payload["status_code"] == 200


@pytest.mark.django_db
class TestSignature:
    def test_signature_header_attached_when_secret_present(
        self, org_user
    ) -> None:
        client = _client(org_user)
        create = client.post(
            "/api/v1/integrations/webhooks/",
            data=json.dumps({"label": "x", "url": "https://e.com/h"}),
            content_type="application/json",
        )
        webhook_id = create.json()["id"]
        captured = {}

        def _capture(url, *, content, headers, timeout, follow_redirects):
            captured["headers"] = headers
            captured["body"] = content
            return _mock_response(200)

        with patch(
            "apps.integrations.delivery.httpx.post", side_effect=_capture
        ):
            client.post(f"/api/v1/integrations/webhooks/{webhook_id}/test/")
        sig = captured["headers"].get("X-ZeroKey-Signature")
        assert sig is not None
        # Stripe-style: t=<unix>,v1=<hex>
        assert sig.startswith("t=")
        assert ",v1=" in sig
        # Recompute + verify with the plaintext we captured at create.
        plaintext = create.json()["plaintext_secret"]
        import hashlib, hmac

        t_part, v_part = sig.split(",")
        t_value = t_part[2:]
        v_value = v_part[3:]
        expected = hmac.new(
            plaintext.encode(),
            f"{t_value}.".encode() + captured["body"],
            hashlib.sha256,
        ).hexdigest()
        assert v_value == expected

    def test_event_headers_attached(self, org_user) -> None:
        client = _client(org_user)
        create = client.post(
            "/api/v1/integrations/webhooks/",
            data=json.dumps({"label": "x", "url": "https://e.com/h"}),
            content_type="application/json",
        )
        webhook_id = create.json()["id"]
        captured = {}

        def _capture(url, *, content, headers, timeout, follow_redirects):
            captured["headers"] = headers
            return _mock_response(200)

        with patch(
            "apps.integrations.delivery.httpx.post", side_effect=_capture
        ):
            client.post(f"/api/v1/integrations/webhooks/{webhook_id}/test/")
        h = captured["headers"]
        assert h["X-ZeroKey-Event-Type"] == "ping"
        assert h["X-ZeroKey-Attempt"] == "1"
        assert "X-ZeroKey-Event-Id" in h
        assert "X-ZeroKey-Delivery-Id" in h
        assert h["User-Agent"] == "ZeroKey-Webhooks/1.0"


@pytest.mark.django_db
class TestFanOut:
    def test_only_subscribed_endpoints_get_event(self, org_user) -> None:
        from apps.integrations.services import fan_out_event

        org, _ = org_user
        client = _client(org_user)
        # One subscribed, one not.
        client.post(
            "/api/v1/integrations/webhooks/",
            data=json.dumps(
                {
                    "label": "subscribed",
                    "url": "https://a.example/h",
                    "event_types": ["invoice.validated"],
                }
            ),
            content_type="application/json",
        )
        client.post(
            "/api/v1/integrations/webhooks/",
            data=json.dumps(
                {
                    "label": "not-subscribed",
                    "url": "https://b.example/h",
                    "event_types": ["invoice.lhdn_rejected"],
                }
            ),
            content_type="application/json",
        )

        with patch(
            "apps.integrations.tasks.deliver_webhook_task.delay"
        ) as queued:
            result = fan_out_event(
                organization_id=org.id,
                event_type="invoice.validated",
                payload={"invoice_id": "x"},
            )

        assert result["queued"] == 1
        assert queued.call_count == 1

    def test_inactive_endpoint_not_queued(self, org_user) -> None:
        from apps.integrations.services import fan_out_event

        org, _ = org_user
        client = _client(org_user)
        create = client.post(
            "/api/v1/integrations/webhooks/",
            data=json.dumps(
                {
                    "label": "x",
                    "url": "https://a.example/h",
                    "event_types": ["invoice.validated"],
                }
            ),
            content_type="application/json",
        )
        webhook_id = create.json()["id"]
        # Revoke (flips is_active=False).
        client.delete(f"/api/v1/integrations/webhooks/{webhook_id}/")

        with patch(
            "apps.integrations.tasks.deliver_webhook_task.delay"
        ) as queued:
            result = fan_out_event(
                organization_id=org.id,
                event_type="invoice.validated",
                payload={},
            )

        assert result["queued"] == 0
        queued.assert_not_called()


@pytest.mark.django_db
class TestRetryPolicy:
    def test_5xx_retryable(self) -> None:
        from apps.integrations.tasks import _should_retry

        assert _should_retry(500, "HTTP 500") is True
        assert _should_retry(503, "HTTP 503") is True

    def test_429_retryable(self) -> None:
        from apps.integrations.tasks import _should_retry

        assert _should_retry(429, "HTTP 429") is True

    def test_4xx_not_retryable(self) -> None:
        from apps.integrations.tasks import _should_retry

        assert _should_retry(400, "HTTP 400") is False
        assert _should_retry(404, "HTTP 404") is False
        assert _should_retry(401, "HTTP 401") is False

    def test_network_error_retryable(self) -> None:
        from apps.integrations.tasks import _should_retry

        assert _should_retry(None, "ConnectError") is True
        assert _should_retry(None, "TimeoutException") is True

    def test_endpoint_revoked_not_retryable(self) -> None:
        from apps.integrations.tasks import _should_retry

        assert _should_retry(None, "EndpointRevoked") is False


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
        with patch(
            "apps.integrations.delivery.httpx.post",
            return_value=_mock_response(200, "ok"),
        ):
            client.post(f"/api/v1/integrations/webhooks/{a}/test/")
            client.post(f"/api/v1/integrations/webhooks/{a}/test/")
            client.post(f"/api/v1/integrations/webhooks/{b}/test/")

        all_deliveries = client.get("/api/v1/integrations/deliveries/")
        assert len(all_deliveries.json()["results"]) == 3
        only_a = client.get(f"/api/v1/integrations/deliveries/?webhook_id={a}")
        assert len(only_a.json()["results"]) == 2


@pytest.mark.django_db
class TestCrypto:
    def test_roundtrip(self) -> None:
        from apps.integrations.crypto import decrypt_secret, encrypt_secret

        plain = "whsec_super_secret_value"
        cipher = encrypt_secret(plain)
        assert cipher != plain
        assert cipher != ""
        assert decrypt_secret(cipher) == plain

    def test_empty_decrypts_to_none(self) -> None:
        from apps.integrations.crypto import decrypt_secret

        assert decrypt_secret("") is None

    def test_tampered_returns_none(self) -> None:
        from apps.integrations.crypto import decrypt_secret, encrypt_secret

        cipher = encrypt_secret("hello")
        # Flip a byte → InvalidToken → None.
        tampered = cipher[:-3] + "AAA"
        assert decrypt_secret(tampered) is None
