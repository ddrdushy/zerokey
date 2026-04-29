"""Tests for the per-tenant detail endpoint (Slice 38)."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.identity.models import Organization, OrganizationMembership, Role, User
from apps.ingestion.models import IngestionJob
from apps.submission.models import ExceptionInboxItem, Invoice


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def staff_user(seeded) -> User:
    return User.objects.create_user(email="staff@symprio.com", password="x", is_staff=True)


@pytest.fixture
def populated_tenant(seeded) -> tuple[Organization, list[IngestionJob], list[Invoice]]:
    org = Organization.objects.create(
        legal_name="Acme Sdn Bhd",
        tin="C10000000001",
        contact_email="ops@acme.example",
        contact_phone="+60 3 1234 5678",
    )
    user_a = User.objects.create_user(email="a@acme.example", password="x")
    user_b = User.objects.create_user(email="b@acme.example", password="x")
    OrganizationMembership.objects.create(
        user=user_a, organization=org, role=Role.objects.get(name="owner")
    )
    OrganizationMembership.objects.create(
        user=user_b, organization=org, role=Role.objects.get(name="viewer")
    )
    jobs = []
    for i in range(3):
        jobs.append(
            IngestionJob.objects.create(
                organization=org,
                source_channel=IngestionJob.SourceChannel.WEB_UPLOAD,
                original_filename=f"invoice-{i}.pdf",
                file_size=1024,
                file_mime_type="application/pdf",
                s3_object_key=f"tenants/{org.id}/ingestion/{i}/file.pdf",
                status=IngestionJob.Status.READY_FOR_REVIEW,
                extraction_engine="ollama-structure",
                extraction_confidence=0.9,
            )
        )
    invoices = []
    for i, job in enumerate(jobs):
        invoices.append(
            Invoice.objects.create(
                organization=org,
                ingestion_job_id=job.id,
                status=Invoice.Status.READY_FOR_REVIEW,
                invoice_number=f"INV-{i:04d}",
                buyer_legal_name="Buyer Co",
                currency_code="MYR",
            )
        )
    ExceptionInboxItem.objects.create(
        organization=org,
        invoice=invoices[0],
        reason=ExceptionInboxItem.Reason.VALIDATION_FAILURE,
        priority=ExceptionInboxItem.Priority.NORMAL,
        status=ExceptionInboxItem.Status.OPEN,
    )
    record_event(
        action_type="invoice.created",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(user_a.id),
        organization_id=str(org.id),
    )
    return org, jobs, invoices


@pytest.mark.django_db
class TestTenantDetail:
    def test_unauthenticated_rejected(self, populated_tenant) -> None:
        org, _, _ = populated_tenant
        response = Client().get(f"/api/v1/admin/tenants/{org.id}/")
        assert response.status_code in (401, 403)

    def test_customer_403(self, populated_tenant, seeded) -> None:
        org, _, _ = populated_tenant
        user = User.objects.create_user(email="cust@x", password="x")
        client = Client()
        client.force_login(user)
        response = client.get(f"/api/v1/admin/tenants/{org.id}/")
        assert response.status_code == 403

    def test_staff_sees_full_detail(self, staff_user, populated_tenant) -> None:
        org, jobs, invoices = populated_tenant
        client = Client()
        client.force_login(staff_user)
        response = client.get(f"/api/v1/admin/tenants/{org.id}/")
        assert response.status_code == 200
        body = response.json()

        assert body["legal_name"] == "Acme Sdn Bhd"
        assert body["tin"] == "C10000000001"
        assert body["contact_email"] == "ops@acme.example"
        assert body["contact_phone"] == "+60 3 1234 5678"

        assert body["stats"]["member_count"] == 2
        assert body["stats"]["ingestion_jobs_total"] == 3
        assert body["stats"]["invoices_total"] == 3
        assert body["stats"]["invoices_pending_review"] == 3
        assert body["stats"]["inbox_open"] == 1
        # Audit count >= 1 (the seeded invoice.created)
        assert body["stats"]["audit_events"] >= 1

        assert len(body["members"]) == 2
        emails = {m["email"] for m in body["members"]}
        assert emails == {"a@acme.example", "b@acme.example"}

        assert len(body["recent_jobs"]) == 3
        first_job = body["recent_jobs"][0]
        assert first_job["filename"].startswith("invoice-")
        assert first_job["engine"] == "ollama-structure"
        assert first_job["confidence"] == 0.9

        assert len(body["recent_invoices"]) == 3
        assert body["recent_invoices"][0]["invoice_number"].startswith("INV-")

        # Inbox-by-reason rollup is populated.
        assert body["inbox_open_by_reason"]["validation_failure"] == 1

    def test_unknown_tenant_returns_404(self, staff_user) -> None:
        client = Client()
        client.force_login(staff_user)
        response = client.get("/api/v1/admin/tenants/00000000-0000-0000-0000-000000000000/")
        assert response.status_code == 404

    def test_detail_view_emits_audit_event(self, staff_user, populated_tenant) -> None:
        org, _, _ = populated_tenant
        client = Client()
        client.force_login(staff_user)
        before = AuditEvent.objects.filter(action_type="admin.tenant_detail_viewed").count()
        client.get(f"/api/v1/admin/tenants/{org.id}/")
        after = AuditEvent.objects.filter(action_type="admin.tenant_detail_viewed").count()
        assert after == before + 1

        event = (
            AuditEvent.objects.filter(action_type="admin.tenant_detail_viewed")
            .order_by("-sequence")
            .first()
        )
        # System-level (no tenant — crosses tenants by definition).
        assert event.organization_id is None
        # affected_entity_id carries the tenant id so investigators can
        # filter "who looked at this tenant" without a payload search.
        assert event.affected_entity_id == str(org.id)
        # Payload includes the legal name + stats snapshot but never PII
        # like emails, addresses, phone numbers.
        assert event.payload["tenant_legal_name"] == "Acme Sdn Bhd"
        assert "ops@acme.example" not in str(event.payload)
