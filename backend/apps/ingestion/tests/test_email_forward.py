"""Tests for email-forward ingestion (Slice 64)."""

from __future__ import annotations

import base64
import json
import uuid
from unittest.mock import patch

import pytest

from apps.administration.services import upsert_system_setting
from apps.identity.models import (
    Organization,
    OrganizationMembership,
    Role,
    User,
)
from apps.ingestion import email_forward
from apps.ingestion.email_forward import (
    EmailForwardError,
    InboundAttachment,
    InboundEmail,
    InboxNotFoundError,
)
from apps.ingestion.models import IngestionJob


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org_with_inbox(seeded) -> tuple[Organization, str]:
    org = Organization.objects.create(
        legal_name="Acme",
        tin="C1234567890",
        contact_email="o@acme.example",
        inbox_token="testtoken1234567",
    )
    return org, org.inbox_token


@pytest.fixture
def authed_user(org_with_inbox) -> tuple[Organization, User]:
    org, _ = org_with_inbox
    user = User.objects.create_user(email="dushy@acme.example", password="long-enough-password")
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name="owner")
    )
    return org, user


# =============================================================================
# Tenant resolution
# =============================================================================


@pytest.mark.django_db
class TestResolveTenant:
    def test_correct_token_resolves(self, org_with_inbox) -> None:
        org, token = org_with_inbox
        resolved = email_forward.resolve_tenant_from_address(
            f"invoices+{token}@inbox.zerokey.symprio.com"
        )
        assert str(resolved) == str(org.id)

    def test_unknown_token_404(self, org_with_inbox) -> None:
        with pytest.raises(InboxNotFoundError, match="No organization"):
            email_forward.resolve_tenant_from_address(
                "invoices+notarealtoken1@inbox.zerokey.symprio.com"
            )

    def test_malformed_address(self, seeded) -> None:
        with pytest.raises(InboxNotFoundError, match="pattern"):
            email_forward.resolve_tenant_from_address("random@gmail.com")

    def test_empty_address(self, seeded) -> None:
        with pytest.raises(InboxNotFoundError, match="No recipient"):
            email_forward.resolve_tenant_from_address("")


# =============================================================================
# Inbox token + address generation
# =============================================================================


@pytest.mark.django_db
class TestInboxToken:
    def test_first_call_generates(self, seeded) -> None:
        org = Organization.objects.create(
            legal_name="Bare Org",
            tin="C2222222222",
            contact_email="o@b",
            inbox_token="",
        )
        token = email_forward.ensure_inbox_token(org.id)
        assert len(token) == 16
        org.refresh_from_db()
        assert org.inbox_token == token

    def test_subsequent_calls_idempotent(self, org_with_inbox) -> None:
        org, original_token = org_with_inbox
        again = email_forward.ensure_inbox_token(org.id)
        assert again == original_token

    def test_address_format(self, org_with_inbox) -> None:
        org, token = org_with_inbox
        addr = email_forward.inbox_address_for_org(org.id)
        assert addr == f"invoices+{token}@inbox.zerokey.symprio.com"


# =============================================================================
# process_inbound_email
# =============================================================================


def _email(*, to: str, attachments: list[InboundAttachment]) -> InboundEmail:
    return InboundEmail(
        to=to,
        sender="billing@vendor.example",
        subject="Invoice INV-001",
        message_id="<msg-1@vendor.example>",
        attachments=attachments,
    )


@pytest.mark.django_db
class TestProcessInbound:
    def test_creates_job_per_pdf_attachment(self, org_with_inbox) -> None:
        org, token = org_with_inbox
        # Mock S3 + extraction so the test is hermetic.
        with (
            patch(
                "apps.integrations.storage.put_object",
                return_value=type(
                    "Stored",
                    (),
                    {"size": 1024, "content_type": "application/pdf"},
                )(),
            ),
            patch("apps.extraction.tasks.extract_invoice.delay"),
        ):
            result = email_forward.process_inbound_email(
                _email(
                    to=f"invoices+{token}@inbox.zerokey.symprio.com",
                    attachments=[
                        InboundAttachment(
                            filename="invoice.pdf",
                            mime_type="application/pdf",
                            body=b"%PDF-1.4 fake content",
                        )
                    ],
                )
            )
        assert len(result["jobs_created"]) == 1
        # Job exists in DB.
        job_id = result["jobs_created"][0]
        job = IngestionJob.objects.get(id=job_id)
        assert job.organization_id == org.id
        assert job.source_channel == IngestionJob.SourceChannel.EMAIL_FORWARD
        assert job.source_identifier == "<msg-1@vendor.example>"

    def test_unsupported_mime_skipped(self, org_with_inbox) -> None:
        _, token = org_with_inbox
        result = email_forward.process_inbound_email(
            _email(
                to=f"invoices+{token}@inbox.zerokey.symprio.com",
                attachments=[
                    InboundAttachment(
                        filename="weird.zip",
                        mime_type="application/zip",
                        body=b"PK\x03\x04",
                    )
                ],
            )
        )
        assert result["jobs_created"] == []
        assert result["skipped"][0]["reason"].startswith("mime_type:")

    def test_octet_stream_pdf_promoted(self, org_with_inbox) -> None:
        """Some scanners send PDFs as octet-stream — sniff magic bytes."""
        _, token = org_with_inbox
        with (
            patch(
                "apps.integrations.storage.put_object",
                return_value=type("Stored", (), {"size": 5, "content_type": "application/pdf"})(),
            ),
            patch("apps.extraction.tasks.extract_invoice.delay"),
        ):
            result = email_forward.process_inbound_email(
                _email(
                    to=f"invoices+{token}@inbox.zerokey.symprio.com",
                    attachments=[
                        InboundAttachment(
                            filename="scan.pdf",
                            mime_type="application/octet-stream",
                            body=b"%PDF-1.4 octet-stream pdf",
                        )
                    ],
                )
            )
        assert len(result["jobs_created"]) == 1

    def test_no_attachments_acks_with_audit(self, org_with_inbox) -> None:
        from apps.audit.models import AuditEvent

        _, token = org_with_inbox
        result = email_forward.process_inbound_email(
            _email(
                to=f"invoices+{token}@inbox.zerokey.symprio.com",
                attachments=[],
            )
        )
        assert result["jobs_created"] == 0
        ev = AuditEvent.objects.filter(action_type="ingestion.email_forward.empty").first()
        assert ev is not None

    def test_too_many_attachments_rejected(self, org_with_inbox) -> None:
        _, token = org_with_inbox
        with pytest.raises(EmailForwardError, match="Too many"):
            email_forward.process_inbound_email(
                _email(
                    to=f"invoices+{token}@inbox.zerokey.symprio.com",
                    attachments=[
                        InboundAttachment(
                            filename=f"f{i}.pdf",
                            mime_type="application/pdf",
                            body=b"%PDF",
                        )
                        for i in range(11)
                    ],
                )
            )

    def test_oversized_attachment_skipped(self, org_with_inbox) -> None:
        _, token = org_with_inbox
        # Just over the 25 MB limit.
        big = InboundAttachment(
            filename="big.pdf",
            mime_type="application/pdf",
            body=b"X" * (26 * 1024 * 1024),
        )
        result = email_forward.process_inbound_email(
            _email(
                to=f"invoices+{token}@inbox.zerokey.symprio.com",
                attachments=[big],
            )
        )
        assert result["jobs_created"] == []
        assert result["skipped"][0]["reason"] == "too_large"

    def test_audit_redacts_sender_email(self, org_with_inbox) -> None:
        from apps.audit.models import AuditEvent

        _, token = org_with_inbox
        with (
            patch(
                "apps.integrations.storage.put_object",
                return_value=type("S", (), {"size": 1, "content_type": "application/pdf"})(),
            ),
            patch("apps.extraction.tasks.extract_invoice.delay"),
        ):
            email_forward.process_inbound_email(
                _email(
                    to=f"invoices+{token}@inbox.zerokey.symprio.com",
                    attachments=[
                        InboundAttachment(
                            filename="i.pdf",
                            mime_type="application/pdf",
                            body=b"%PDF",
                        )
                    ],
                )
            )
        ev = AuditEvent.objects.filter(action_type="ingestion.email_forward.processed").first()
        # billing@vendor.example → b******@vendor.example (masked)
        assert "billing" not in ev.payload["sender"]
        assert "vendor.example" in ev.payload["sender"]


# =============================================================================
# Endpoints
# =============================================================================


@pytest.mark.django_db
class TestInboxAddressEndpoint:
    def test_unauthenticated_403(self, seeded) -> None:
        from django.test import Client

        response = Client().get("/api/v1/ingestion/inbox/address/")
        assert response.status_code in (401, 403)

    def test_returns_address(self, authed_user) -> None:
        from django.test import Client

        org, user = authed_user
        client = Client()
        client.force_login(user)
        session = client.session
        session["organization_id"] = str(org.id)
        session.save()
        response = client.get("/api/v1/ingestion/inbox/address/")
        assert response.status_code == 200
        body = response.json()
        assert body["address"].startswith("invoices+")
        assert body["address"].endswith("@inbox.zerokey.symprio.com")


@pytest.mark.django_db
class TestEmailForwardWebhook:
    def test_unauthorized_without_token(self, org_with_inbox) -> None:
        from django.test import Client

        response = Client().post(
            "/api/v1/ingestion/inbox/email-forward/",
            data=json.dumps({"to": "x"}),
            content_type="application/json",
        )
        assert response.status_code == 401

    def test_unauthorized_with_wrong_token(self, org_with_inbox) -> None:
        from django.test import Client

        upsert_system_setting(
            namespace="email_inbound",
            values={"webhook_token": "expected-secret"},
        )
        response = Client().post(
            "/api/v1/ingestion/inbox/email-forward/",
            data=json.dumps({"to": "x"}),
            content_type="application/json",
            HTTP_X_ZEROKEY_INBOUND_TOKEN="wrong-secret",
        )
        assert response.status_code == 401

    def test_happy_path_creates_job(self, org_with_inbox) -> None:
        from django.test import Client

        org, token = org_with_inbox
        upsert_system_setting(
            namespace="email_inbound",
            values={"webhook_token": "expected-secret"},
        )
        body = {
            "to": f"invoices+{token}@inbox.zerokey.symprio.com",
            "from": "billing@vendor.example",
            "subject": "Invoice attached",
            "message_id": "<id-x@vendor.example>",
            "attachments": [
                {
                    "filename": "inv.pdf",
                    "mime_type": "application/pdf",
                    "body_b64": base64.b64encode(b"%PDF-1.4").decode("ascii"),
                }
            ],
        }
        with (
            patch(
                "apps.integrations.storage.put_object",
                return_value=type(
                    "S",
                    (),
                    {"size": 8, "content_type": "application/pdf"},
                )(),
            ),
            patch("apps.extraction.tasks.extract_invoice.delay"),
        ):
            response = Client().post(
                "/api/v1/ingestion/inbox/email-forward/",
                data=json.dumps(body),
                content_type="application/json",
                HTTP_X_ZEROKEY_INBOUND_TOKEN="expected-secret",
            )
        assert response.status_code == 200
        result = response.json()
        assert len(result["jobs_created"]) == 1

    def test_unknown_inbox_404(self, seeded) -> None:
        from django.test import Client

        upsert_system_setting(
            namespace="email_inbound",
            values={"webhook_token": "ok"},
        )
        response = Client().post(
            "/api/v1/ingestion/inbox/email-forward/",
            data=json.dumps(
                {
                    "to": "invoices+nonexistent@inbox.zerokey.symprio.com",
                    "from": "x@x",
                    "subject": "s",
                    "message_id": "<m@x>",
                    "attachments": [
                        {
                            "filename": "i.pdf",
                            "mime_type": "application/pdf",
                            "body_b64": base64.b64encode(b"%PDF").decode("ascii"),
                        }
                    ],
                }
            ),
            content_type="application/json",
            HTTP_X_ZEROKEY_INBOUND_TOKEN="ok",
        )
        assert response.status_code == 404


# =============================================================================
# Slice 80 — inbox token rotation
# =============================================================================


@pytest.mark.django_db
class TestRotateInboxToken:
    def test_service_replaces_token_and_invalidates_old(self, org_with_inbox) -> None:
        org, original_token = org_with_inbox
        new_address = email_forward.rotate_inbox_token(
            organization_id=org.id,
            actor_user_id=uuid.uuid4(),
            reason="suspected leak",
        )
        # New address starts with the prefix + uses the inbox domain.
        assert new_address.startswith("invoices+")
        assert new_address.endswith("@inbox.zerokey.symprio.com")

        # Org now carries a different token.
        org.refresh_from_db()
        assert org.inbox_token != original_token

        # Old token no longer resolves; new one does.
        with pytest.raises(InboxNotFoundError):
            email_forward.resolve_tenant_from_address(
                f"invoices+{original_token}@inbox.zerokey.symprio.com"
            )
        resolved = email_forward.resolve_tenant_from_address(new_address)
        assert str(resolved) == str(org.id)

    def test_audit_event_records_prefixes_only(self, org_with_inbox) -> None:
        from apps.audit.models import AuditEvent

        org, original_token = org_with_inbox
        actor = uuid.uuid4()
        email_forward.rotate_inbox_token(
            organization_id=org.id,
            actor_user_id=actor,
            reason="quarterly rotation",
        )
        ev = AuditEvent.objects.filter(action_type="ingestion.inbox_token.rotated").first()
        assert ev is not None
        assert ev.payload["from_token_prefix"] == original_token[:4]
        # Full token never appears in the payload.
        org.refresh_from_db()
        assert org.inbox_token not in str(ev.payload)
        assert original_token not in str(ev.payload)
        assert ev.payload["reason"] == "quarterly rotation"


@pytest.mark.django_db
class TestRotateInboxTokenEndpoint:
    def test_unauthenticated_blocked(self, org_with_inbox) -> None:
        from django.test import Client

        response = Client().post(
            "/api/v1/ingestion/inbox/rotate-token/",
            data=json.dumps({"reason": "test"}),
            content_type="application/json",
        )
        assert response.status_code in (401, 403)

    def test_owner_rotates_successfully(self, authed_user) -> None:
        from django.test import Client

        from apps.identity.models import Organization

        org, user = authed_user
        org.refresh_from_db()
        before = org.inbox_token

        client = Client()
        client.force_login(user)
        session = client.session
        session["organization_id"] = str(org.id)
        session.save()

        response = client.post(
            "/api/v1/ingestion/inbox/rotate-token/",
            data=json.dumps({"reason": "regular hygiene"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["address"].startswith("invoices+")
        assert body["address"].endswith("@inbox.zerokey.symprio.com")

        # Token actually changed.
        org = Organization.objects.get(id=org.id)
        assert org.inbox_token != before

    def test_viewer_cannot_rotate(self, org_with_inbox, seeded) -> None:
        from django.test import Client

        org, _ = org_with_inbox
        viewer = User.objects.create_user(
            email="viewer@acme.example", password="long-enough-password"
        )
        OrganizationMembership.objects.create(
            user=viewer,
            organization=org,
            role=Role.objects.get(name="viewer"),
        )
        client = Client()
        client.force_login(viewer)
        session = client.session
        session["organization_id"] = str(org.id)
        session.save()
        response = client.post(
            "/api/v1/ingestion/inbox/rotate-token/",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 403
