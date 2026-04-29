"""Tests for the public API ingestion endpoint (Slice 78)."""

from __future__ import annotations

import base64
import json
from unittest.mock import patch

import pytest
from django.test import Client

from apps.audit.models import AuditEvent
from apps.identity.api_keys import create_api_key
from apps.identity.models import (
    Organization,
    OrganizationMembership,
    Role,
    User,
)
from apps.ingestion.models import IngestionJob


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org_user_key(seeded) -> tuple[Organization, User, str]:
    org = Organization.objects.create(
        legal_name="API Test Sdn Bhd",
        tin="C4444444444",
        contact_email="ops@apitest.example",
    )
    user = User.objects.create_user(
        email="api@apitest.example", password="long-enough-password"
    )
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name="owner")
    )
    _, plaintext = create_api_key(
        organization_id=org.id, label="ci-key", actor_user=user
    )
    return org, user, plaintext


def _stub_storage():
    """Return a context manager that fakes S3 + extraction.

    The api_upload service path calls storage.put_object + queues
    a Celery task; both are mocked so the test runs hermetically.
    """
    return patch.multiple(
        "apps.integrations.storage",
        put_object=lambda **kwargs: type(
            "_Stored",
            (),
            {"size": 1024, "content_type": "application/pdf"},
        )(),
    )


PDF_BYTES = b"%PDF-1.4 fake content"
B64_PDF = base64.b64encode(PDF_BYTES).decode("ascii")


# =============================================================================
# Auth gate
# =============================================================================


@pytest.mark.django_db
class TestAuthGate:
    def test_no_auth_header_401(self, seeded) -> None:
        response = Client().post(
            "/api/v1/ingestion/jobs/api-upload/",
            data=json.dumps(
                {
                    "filename": "x.pdf",
                    "mime_type": "application/pdf",
                    "body_b64": B64_PDF,
                }
            ),
            content_type="application/json",
        )
        # No bearer token → APIKeyAuthentication doesn't authenticate;
        # IsAuthenticated permission denies → 401 or 403.
        assert response.status_code in (401, 403)

    def test_invalid_bearer_401(self, seeded) -> None:
        response = Client().post(
            "/api/v1/ingestion/jobs/api-upload/",
            data=json.dumps(
                {
                    "filename": "x.pdf",
                    "mime_type": "application/pdf",
                    "body_b64": B64_PDF,
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer zk_live_TotallyFakeWrongValueXxxxxxxxxxxxxx",
        )
        assert response.status_code == 401

    def test_session_auth_not_accepted(self, org_user_key) -> None:
        # The endpoint pins authentication_classes to APIKeyAuthentication
        # only — even a logged-in session can't post here.
        org, user, _plaintext = org_user_key
        client = Client()
        client.force_login(user)
        session = client.session
        session["organization_id"] = str(org.id)
        session.save()
        response = client.post(
            "/api/v1/ingestion/jobs/api-upload/",
            data=json.dumps(
                {
                    "filename": "x.pdf",
                    "mime_type": "application/pdf",
                    "body_b64": B64_PDF,
                }
            ),
            content_type="application/json",
        )
        assert response.status_code in (401, 403)


# =============================================================================
# Happy path
# =============================================================================


@pytest.mark.django_db
class TestHappyPath:
    def test_creates_ingestion_job_with_api_source_channel(
        self, org_user_key
    ) -> None:
        org, _user, plaintext = org_user_key
        with _stub_storage(), patch(
            "apps.extraction.tasks.extract_invoice.delay"
        ):
            response = Client().post(
                "/api/v1/ingestion/jobs/api-upload/",
                data=json.dumps(
                    {
                        "filename": "INV-2026-001.pdf",
                        "mime_type": "application/pdf",
                        "body_b64": B64_PDF,
                        "source_identifier": "vendor-row-12345",
                    }
                ),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {plaintext}",
            )
        assert response.status_code == 201, response.json()
        body = response.json()
        job = IngestionJob.objects.get(id=body["id"])
        assert job.organization_id == org.id
        assert job.source_channel == IngestionJob.SourceChannel.API
        assert job.source_identifier == "vendor-row-12345"
        assert job.original_filename == "INV-2026-001.pdf"

    def test_audit_event_actor_external(self, org_user_key) -> None:
        _org, _user, plaintext = org_user_key
        with _stub_storage(), patch(
            "apps.extraction.tasks.extract_invoice.delay"
        ):
            Client().post(
                "/api/v1/ingestion/jobs/api-upload/",
                data=json.dumps(
                    {
                        "filename": "x.pdf",
                        "mime_type": "application/pdf",
                        "body_b64": B64_PDF,
                    }
                ),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {plaintext}",
            )
        ev = AuditEvent.objects.filter(
            action_type="ingestion.job.received"
        ).first()
        assert ev is not None
        assert ev.actor_type == AuditEvent.ActorType.EXTERNAL
        assert ev.payload["source_channel"] == "api"


# =============================================================================
# Validation
# =============================================================================


@pytest.mark.django_db
class TestValidation:
    def test_missing_filename_400(self, org_user_key) -> None:
        _, _, plaintext = org_user_key
        response = Client().post(
            "/api/v1/ingestion/jobs/api-upload/",
            data=json.dumps(
                {"mime_type": "application/pdf", "body_b64": B64_PDF}
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {plaintext}",
        )
        assert response.status_code == 400

    def test_missing_body_b64_400(self, org_user_key) -> None:
        _, _, plaintext = org_user_key
        response = Client().post(
            "/api/v1/ingestion/jobs/api-upload/",
            data=json.dumps(
                {"filename": "x.pdf", "mime_type": "application/pdf"}
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {plaintext}",
        )
        assert response.status_code == 400

    def test_invalid_base64_400(self, org_user_key) -> None:
        _, _, plaintext = org_user_key
        response = Client().post(
            "/api/v1/ingestion/jobs/api-upload/",
            data=json.dumps(
                {
                    "filename": "x.pdf",
                    "mime_type": "application/pdf",
                    "body_b64": "not!valid!base64!",
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {plaintext}",
        )
        assert response.status_code == 400
        assert "base64" in response.json()["detail"].lower()

    def test_unsupported_mime_400(self, org_user_key) -> None:
        _, _, plaintext = org_user_key
        with _stub_storage():
            response = Client().post(
                "/api/v1/ingestion/jobs/api-upload/",
                data=json.dumps(
                    {
                        "filename": "x.exe",
                        "mime_type": "application/x-msdownload",
                        "body_b64": B64_PDF,
                    }
                ),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {plaintext}",
            )
        assert response.status_code == 400

    def test_oversize_decoded_400(self, org_user_key) -> None:
        _, _, plaintext = org_user_key
        # 26 MB of zero bytes, base64-encoded.
        big = base64.b64encode(b"X" * (26 * 1024 * 1024)).decode("ascii")
        response = Client().post(
            "/api/v1/ingestion/jobs/api-upload/",
            data=json.dumps(
                {
                    "filename": "big.pdf",
                    "mime_type": "application/pdf",
                    "body_b64": big,
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {plaintext}",
        )
        assert response.status_code == 400
        assert "limit" in response.json()["detail"].lower()

    def test_zero_byte_decoded_400(self, org_user_key) -> None:
        _, _, plaintext = org_user_key
        response = Client().post(
            "/api/v1/ingestion/jobs/api-upload/",
            data=json.dumps(
                {
                    "filename": "x.pdf",
                    "mime_type": "application/pdf",
                    "body_b64": "",
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {plaintext}",
        )
        # body_b64="" is treated as missing field; both shapes
        # surface as 400 + a helpful message.
        assert response.status_code == 400


# =============================================================================
# Cross-tenant isolation — an API key for org A can't push for org B.
# =============================================================================


@pytest.mark.django_db
class TestTenantIsolation:
    def test_job_lands_under_keys_org(self, org_user_key, seeded) -> None:
        # Same shape as the happy-path test, but verify tenant binding.
        org_a, _user, plaintext = org_user_key
        # Build an unrelated org B in case we ever introduce a path
        # that lets a forged tenant slip through.
        Organization.objects.create(
            legal_name="Other Co",
            tin="C5555555555",
            contact_email="o@o",
        )
        with _stub_storage(), patch(
            "apps.extraction.tasks.extract_invoice.delay"
        ):
            response = Client().post(
                "/api/v1/ingestion/jobs/api-upload/",
                data=json.dumps(
                    {
                        "filename": "x.pdf",
                        "mime_type": "application/pdf",
                        "body_b64": B64_PDF,
                    }
                ),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {plaintext}",
            )
        assert response.status_code == 201
        job = IngestionJob.objects.get(id=response.json()["id"])
        assert job.organization_id == org_a.id
