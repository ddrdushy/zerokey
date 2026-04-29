"""Tests for WhatsApp ingestion (Slice 82)."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import patch

import pytest

from apps.administration.services import upsert_system_setting
from apps.identity.models import Organization, Role
from apps.ingestion import whatsapp
from apps.ingestion.models import IngestionJob
from apps.ingestion.whatsapp import (
    InboundWhatsAppAttachment,
    InboundWhatsAppMessage,
    PhoneNumberNotFoundError,
    WhatsAppForwardError,
)


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org_with_wa(seeded) -> tuple[Organization, str]:
    org = Organization.objects.create(
        legal_name="Acme",
        tin="C1234567890",
        contact_email="o@acme.example",
        whatsapp_phone_number_id="9999999900",
    )
    return org, org.whatsapp_phone_number_id


# =============================================================================
# Tenant resolution
# =============================================================================


@pytest.mark.django_db
class TestResolveTenant:
    def test_correct_phone_number_id_resolves(self, org_with_wa) -> None:
        org, pnid = org_with_wa
        resolved = whatsapp.resolve_tenant_from_phone_number_id(pnid)
        assert str(resolved) == str(org.id)

    def test_unknown_phone_number_id_404(self, org_with_wa) -> None:
        with pytest.raises(PhoneNumberNotFoundError, match="No organization"):
            whatsapp.resolve_tenant_from_phone_number_id("0000000000")

    def test_empty_phone_number_id(self, seeded) -> None:
        with pytest.raises(PhoneNumberNotFoundError, match="No phone_number_id"):
            whatsapp.resolve_tenant_from_phone_number_id("")


# =============================================================================
# process_inbound_whatsapp_message
# =============================================================================


def _msg(*, pnid: str, attachments: list[InboundWhatsAppAttachment]) -> InboundWhatsAppMessage:
    return InboundWhatsAppMessage(
        sender="60123456789",
        message_id="wamid.HBgLNjAxMjM0NTY3ODkVAgARGBI=",
        phone_number_id=pnid,
        timestamp="1704067200",
        attachments=attachments,
    )


@pytest.mark.django_db
class TestProcessInbound:
    def test_creates_job_per_pdf_media(self, org_with_wa) -> None:
        org, pnid = org_with_wa
        with (
            patch(
                "apps.integrations.storage.put_object",
                return_value=type(
                    "Stored", (), {"size": 1024, "content_type": "application/pdf"}
                )(),
            ),
            patch("apps.extraction.tasks.extract_invoice.delay"),
        ):
            result = whatsapp.process_inbound_whatsapp_message(
                _msg(
                    pnid=pnid,
                    attachments=[
                        InboundWhatsAppAttachment(
                            filename="invoice.pdf",
                            mime_type="application/pdf",
                            body=b"%PDF-1.4 fake content",
                            media_id="media-abc",
                        )
                    ],
                )
            )
        assert len(result["jobs_created"]) == 1
        job_id = result["jobs_created"][0]
        job = IngestionJob.objects.get(id=job_id)
        assert job.organization_id == org.id
        assert job.source_channel == IngestionJob.SourceChannel.WHATSAPP
        assert job.source_identifier.startswith("wamid.")

    def test_unsupported_mime_skipped(self, org_with_wa) -> None:
        _, pnid = org_with_wa
        result = whatsapp.process_inbound_whatsapp_message(
            _msg(
                pnid=pnid,
                attachments=[
                    InboundWhatsAppAttachment(
                        filename="audio.ogg",
                        mime_type="audio/ogg",
                        body=b"OggS",
                    )
                ],
            )
        )
        assert result["jobs_created"] == []
        assert result["skipped"][0]["reason"].startswith("mime_type:")

    def test_no_attachments_acks_with_audit(self, org_with_wa) -> None:
        from apps.audit.models import AuditEvent

        _, pnid = org_with_wa
        result = whatsapp.process_inbound_whatsapp_message(_msg(pnid=pnid, attachments=[]))
        assert result["jobs_created"] == 0
        ev = AuditEvent.objects.filter(action_type="ingestion.whatsapp.empty").first()
        assert ev is not None

    def test_too_many_attachments_rejected(self, org_with_wa) -> None:
        _, pnid = org_with_wa
        with pytest.raises(WhatsAppForwardError, match="Too many"):
            whatsapp.process_inbound_whatsapp_message(
                _msg(
                    pnid=pnid,
                    attachments=[
                        InboundWhatsAppAttachment(
                            filename=f"f{i}.pdf",
                            mime_type="application/pdf",
                            body=b"%PDF",
                        )
                        for i in range(11)
                    ],
                )
            )

    def test_oversized_media_skipped(self, org_with_wa) -> None:
        _, pnid = org_with_wa
        big = InboundWhatsAppAttachment(
            filename="big.pdf",
            mime_type="application/pdf",
            body=b"X" * (26 * 1024 * 1024),
        )
        result = whatsapp.process_inbound_whatsapp_message(_msg(pnid=pnid, attachments=[big]))
        assert result["jobs_created"] == []
        assert result["skipped"][0]["reason"] == "too_large"

    def test_audit_redacts_sender_phone(self, org_with_wa) -> None:
        from apps.audit.models import AuditEvent

        _, pnid = org_with_wa
        with (
            patch(
                "apps.integrations.storage.put_object",
                return_value=type("S", (), {"size": 1, "content_type": "application/pdf"})(),
            ),
            patch("apps.extraction.tasks.extract_invoice.delay"),
        ):
            whatsapp.process_inbound_whatsapp_message(
                _msg(
                    pnid=pnid,
                    attachments=[
                        InboundWhatsAppAttachment(
                            filename="i.pdf",
                            mime_type="application/pdf",
                            body=b"%PDF",
                            media_id="m1",
                        )
                    ],
                )
            )
        ev = AuditEvent.objects.filter(action_type="ingestion.whatsapp.processed").first()
        # 60123456789 → 6012******* (subscriber digits masked)
        assert "456789" not in ev.payload["sender"]
        assert ev.payload["sender"].startswith("6012")


# =============================================================================
# Meta payload parser
# =============================================================================


def _meta_payload(*, pnid: str, media_id: str = "media-1") -> dict:
    """Minimal Meta Cloud API webhook body with one document message."""
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": pnid},
                            "messages": [
                                {
                                    "id": "wamid.test1",
                                    "from": "60123456789",
                                    "timestamp": "1704067200",
                                    "type": "document",
                                    "document": {
                                        "id": media_id,
                                        "filename": "invoice.pdf",
                                        "mime_type": "application/pdf",
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


class TestMetaParser:
    def test_parses_document_message(self) -> None:
        def fetcher(media_id: str) -> tuple[bytes, str, str]:
            assert media_id == "media-1"
            return (b"%PDF-1.4", "application/pdf", "")

        messages = whatsapp.parse_meta_webhook_payload(
            _meta_payload(pnid="abc"), media_fetcher=fetcher
        )
        assert len(messages) == 1
        m = messages[0]
        assert m.phone_number_id == "abc"
        assert m.message_id == "wamid.test1"
        assert m.sender == "60123456789"
        assert len(m.attachments) == 1
        att = m.attachments[0]
        assert att.filename == "invoice.pdf"
        assert att.mime_type == "application/pdf"
        assert att.media_id == "media-1"

    def test_text_message_yields_no_attachment(self) -> None:
        body = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": "abc"},
                                "messages": [
                                    {
                                        "id": "wamid.txt",
                                        "from": "60123456789",
                                        "timestamp": "1",
                                        "type": "text",
                                        "text": {"body": "Hello"},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }
        messages = whatsapp.parse_meta_webhook_payload(
            body, media_fetcher=lambda _id: (b"", "", "")
        )
        assert len(messages) == 1
        assert messages[0].attachments == []

    def test_empty_payload(self) -> None:
        assert (
            whatsapp.parse_meta_webhook_payload({}, media_fetcher=lambda _id: (b"", "", "")) == []
        )

    def test_media_fetch_failure_drops_attachment(self) -> None:
        def boom(_media_id: str) -> tuple[bytes, str, str]:
            raise RuntimeError("network down")

        messages = whatsapp.parse_meta_webhook_payload(
            _meta_payload(pnid="abc"), media_fetcher=boom
        )
        # Message still emitted (so audit chain sees the no-media
        # outcome) but with no attachments — drives the "empty" path.
        assert len(messages) == 1
        assert messages[0].attachments == []


# =============================================================================
# Signature verification
# =============================================================================


class TestSignature:
    def test_valid_signature_passes(self) -> None:
        secret = "appsecret"
        body = b'{"entry":[]}'
        digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert whatsapp.verify_meta_signature(
            app_secret=secret, body=body, signature_header=f"sha256={digest}"
        )

    def test_wrong_signature_fails(self) -> None:
        assert not whatsapp.verify_meta_signature(
            app_secret="appsecret", body=b"x", signature_header="sha256=deadbeef"
        )

    def test_missing_prefix_fails(self) -> None:
        assert not whatsapp.verify_meta_signature(
            app_secret="appsecret", body=b"x", signature_header="deadbeef"
        )

    def test_empty_secret_fails_closed(self) -> None:
        assert not whatsapp.verify_meta_signature(
            app_secret="", body=b"x", signature_header="sha256=anything"
        )


# =============================================================================
# Webhook endpoint
# =============================================================================


@pytest.mark.django_db
class TestWhatsAppWebhook:
    def test_get_verify_unconfigured_503(self, seeded) -> None:
        from django.test import Client

        response = Client().get(
            "/api/v1/ingestion/inbox/whatsapp/",
            {
                "hub.mode": "subscribe",
                "hub.verify_token": "x",
                "hub.challenge": "12345",
            },
        )
        assert response.status_code == 503

    def test_get_verify_handshake(self, seeded) -> None:
        from django.test import Client

        upsert_system_setting(
            namespace="whatsapp",
            values={"verify_token": "expected"},
        )
        response = Client().get(
            "/api/v1/ingestion/inbox/whatsapp/",
            {
                "hub.mode": "subscribe",
                "hub.verify_token": "expected",
                "hub.challenge": "12345",
            },
        )
        assert response.status_code == 200
        assert response.content == b"12345"

    def test_get_wrong_token_403(self, seeded) -> None:
        from django.test import Client

        upsert_system_setting(
            namespace="whatsapp",
            values={"verify_token": "expected"},
        )
        response = Client().get(
            "/api/v1/ingestion/inbox/whatsapp/",
            {
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong",
                "hub.challenge": "12345",
            },
        )
        assert response.status_code == 403

    def test_post_unconfigured_503(self, org_with_wa) -> None:
        from django.test import Client

        response = Client().post(
            "/api/v1/ingestion/inbox/whatsapp/",
            data=json.dumps({"entry": []}),
            content_type="application/json",
        )
        assert response.status_code == 503

    def test_post_invalid_signature_401(self, org_with_wa) -> None:
        from django.test import Client

        upsert_system_setting(
            namespace="whatsapp",
            values={"app_secret": "appsecret", "access_token": "tok"},
        )
        response = Client().post(
            "/api/v1/ingestion/inbox/whatsapp/",
            data=json.dumps({"entry": []}),
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256="sha256=wrong",
        )
        assert response.status_code == 401

    def test_post_happy_path_creates_job(self, org_with_wa) -> None:
        from django.test import Client

        org, pnid = org_with_wa
        upsert_system_setting(
            namespace="whatsapp",
            values={"app_secret": "appsecret", "access_token": "tok"},
        )
        body_dict = _meta_payload(pnid=pnid)
        body_bytes = json.dumps(body_dict).encode()
        sig = hmac.new(b"appsecret", body_bytes, hashlib.sha256).hexdigest()

        with (
            patch(
                "apps.integrations.storage.put_object",
                return_value=type("S", (), {"size": 8, "content_type": "application/pdf"})(),
            ),
            patch("apps.extraction.tasks.extract_invoice.delay"),
            patch(
                "apps.ingestion.views._fetch_meta_media",
                return_value=(b"%PDF-1.4", "application/pdf", ""),
            ),
        ):
            response = Client().post(
                "/api/v1/ingestion/inbox/whatsapp/",
                data=body_bytes,
                content_type="application/json",
                HTTP_X_HUB_SIGNATURE_256=f"sha256={sig}",
            )
        assert response.status_code == 200
        result = response.json()
        assert len(result["results"]) == 1
        assert len(result["results"][0]["jobs_created"]) == 1

    def test_post_unknown_phone_number_continues_batch(self, seeded) -> None:
        from django.test import Client

        upsert_system_setting(
            namespace="whatsapp",
            values={"app_secret": "appsecret", "access_token": "tok"},
        )
        body_dict = _meta_payload(pnid="not-registered")
        body_bytes = json.dumps(body_dict).encode()
        sig = hmac.new(b"appsecret", body_bytes, hashlib.sha256).hexdigest()
        with patch(
            "apps.ingestion.views._fetch_meta_media",
            return_value=(b"%PDF-1.4", "application/pdf", ""),
        ):
            response = Client().post(
                "/api/v1/ingestion/inbox/whatsapp/",
                data=body_bytes,
                content_type="application/json",
                HTTP_X_HUB_SIGNATURE_256=f"sha256={sig}",
            )
        # Per-message error returned in batch — overall 200 so Meta
        # doesn't retry the entire payload.
        assert response.status_code == 200
        results = response.json()["results"]
        assert "error" in results[0]
