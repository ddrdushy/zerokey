"""Tests for the ingestion upload pipeline.

Storage is mocked so the unit tests do not need MinIO running. The full
S3 round-trip is exercised end-to-end against the live docker stack;
those checks are part of the manual verification, not pytest.
"""

from __future__ import annotations

from io import BytesIO
from unittest.mock import patch

import pytest
from django.test import Client

from apps.audit.models import AuditEvent
from apps.identity.models import Role
from apps.ingestion.models import IngestionJob
from apps.ingestion.services import (
    MAX_UPLOAD_BYTES,
    IngestionError,
    upload_web_file,
)

REGISTRATION_PAYLOAD = {
    "email": "owner@acme.example",
    "password": "long-enough-password",
    "organization_legal_name": "ACME Sdn Bhd",
    "organization_tin": "C20880050010",
    "contact_email": "ops@acme.example",
}


@pytest.fixture
def seeded_roles(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def authed_client(seeded_roles) -> tuple[Client, str]:
    client = Client()
    response = client.post(
        "/api/v1/identity/register/",
        data=REGISTRATION_PAYLOAD,
        content_type="application/json",
    )
    org_id = response.json()["active_organization_id"]
    return client, org_id


@pytest.fixture
def fake_storage():
    """Patch storage.put_object so tests don't hit MinIO."""
    from apps.integrations.storage import StoredObject

    with patch("apps.ingestion.services.storage.put_object") as mock_put:

        def _put(*, bucket, key, body, content_type):
            return StoredObject(
                bucket=bucket, key=key, size=len(body.read()), content_type=content_type
            )

        mock_put.side_effect = _put
        yield mock_put


@pytest.mark.django_db
class TestUploadService:
    def test_upload_creates_job_and_emits_audit_event(self, authed_client, fake_storage) -> None:
        _, org_id = authed_client
        from uuid import UUID

        from apps.identity.models import User

        user = User.objects.first()
        result = upload_web_file(
            organization_id=UUID(org_id),
            actor_user_id=user.id,
            file_obj=BytesIO(b"%PDF-1.4 fake"),
            original_filename="invoice.pdf",
            mime_type="application/pdf",
            size=14,
        )
        assert result.job.status == IngestionJob.Status.RECEIVED
        assert result.job.original_filename == "invoice.pdf"
        assert result.job.s3_object_key.startswith(f"tenants/{org_id}/ingestion/")
        assert result.job.s3_object_key.endswith("/invoice.pdf")
        assert AuditEvent.objects.filter(action_type="ingestion.job.received").count() == 1

    def test_upload_rejects_unsupported_mime_type(self, authed_client, fake_storage) -> None:
        _, org_id = authed_client
        from uuid import UUID

        from apps.identity.models import User

        with pytest.raises(IngestionError, match="Unsupported"):
            upload_web_file(
                organization_id=UUID(org_id),
                actor_user_id=User.objects.first().id,
                file_obj=BytesIO(b"x"),
                original_filename="evil.exe",
                mime_type="application/x-msdownload",
                size=1,
            )

    def test_upload_rejects_oversized_file(self, authed_client, fake_storage) -> None:
        _, org_id = authed_client
        from uuid import UUID

        from apps.identity.models import User

        with pytest.raises(IngestionError, match="exceeds"):
            upload_web_file(
                organization_id=UUID(org_id),
                actor_user_id=User.objects.first().id,
                file_obj=BytesIO(b"x"),
                original_filename="huge.pdf",
                mime_type="application/pdf",
                size=MAX_UPLOAD_BYTES + 1,
            )


@pytest.mark.django_db
class TestUploadEndpoint:
    def test_unauthenticated_returns_403(self) -> None:
        response = Client().post("/api/v1/ingestion/jobs/upload/")
        assert response.status_code in (401, 403)

    def test_upload_endpoint_creates_job(self, authed_client, fake_storage) -> None:
        client, _ = authed_client
        response = client.post(
            "/api/v1/ingestion/jobs/upload/",
            data={
                "file": _fake_pdf("invoice.pdf"),
            },
        )
        assert response.status_code == 201, response.content
        body = response.json()
        assert body["status"] == "received"
        assert body["original_filename"] == "invoice.pdf"

    def test_list_endpoint_returns_only_my_jobs(self, authed_client, fake_storage) -> None:
        client, _ = authed_client
        client.post(
            "/api/v1/ingestion/jobs/upload/",
            data={"file": _fake_pdf("a.pdf")},
        )
        client.post(
            "/api/v1/ingestion/jobs/upload/",
            data={"file": _fake_pdf("b.pdf")},
        )
        response = client.get("/api/v1/ingestion/jobs/")
        assert response.status_code == 200
        results = response.json()["results"]
        assert {r["original_filename"] for r in results} == {"a.pdf", "b.pdf"}


def _fake_pdf(name: str) -> object:
    """Build an in-memory upload that DRF MultiPartParser will accept."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(name, b"%PDF-1.4 fake content", content_type="application/pdf")
