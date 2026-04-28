"""Tests for the admin overview KPI endpoint (Slice 37)."""

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
    return User.objects.create_user(
        email="staff@symprio.com", password="x", is_staff=True
    )


@pytest.fixture
def populated_platform(seeded) -> Organization:
    org = Organization.objects.create(
        legal_name="Acme", tin="C10000000001", contact_email="ops@acme"
    )
    user = User.objects.create_user(email="a@acme.test", password="x")
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name="owner")
    )
    # Two ingestion jobs (counted in totals + last 7d).
    for i in range(2):
        IngestionJob.objects.create(
            organization=org,
            source_channel=IngestionJob.SourceChannel.WEB_UPLOAD,
            original_filename=f"i-{i}.pdf",
            file_size=10,
            file_mime_type="application/pdf",
            s3_object_key=f"tenants/{org.id}/ingestion/{i}/file.pdf",
            status=IngestionJob.Status.READY_FOR_REVIEW,
        )
    # An invoice in pending_review.
    invoice = Invoice.objects.create(
        organization=org,
        ingestion_job_id=IngestionJob.objects.first().id,
        status=Invoice.Status.READY_FOR_REVIEW,
    )
    # An open inbox item.
    ExceptionInboxItem.objects.create(
        organization=org,
        invoice=invoice,
        reason=ExceptionInboxItem.Reason.VALIDATION_FAILURE,
        priority=ExceptionInboxItem.Priority.NORMAL,
        status=ExceptionInboxItem.Status.OPEN,
    )
    # A few audit events.
    for action in ("invoice.created", "invoice.created", "invoice.updated"):
        record_event(
            action_type=action,
            actor_type=AuditEvent.ActorType.USER,
            actor_id=str(user.id),
            organization_id=str(org.id),
        )
    return org


@pytest.mark.django_db
class TestPlatformOverview:
    def test_unauthenticated_rejected(self, populated_platform) -> None:
        response = Client().get("/api/v1/admin/overview/")
        assert response.status_code in (401, 403)

    def test_customer_403(self, populated_platform, seeded) -> None:
        user = User.objects.create_user(email="cust@x", password="x")
        client = Client()
        client.force_login(user)
        response = client.get("/api/v1/admin/overview/")
        assert response.status_code == 403

    def test_staff_returns_full_kpi_block(
        self, staff_user, populated_platform
    ) -> None:
        client = Client()
        client.force_login(staff_user)
        response = client.get("/api/v1/admin/overview/")
        assert response.status_code == 200
        body = response.json()

        # Tenants block: at least 1 tenant (the populated one), 1 active.
        assert body["tenants"]["total"] >= 1
        assert body["tenants"]["active_last_7d"] >= 1

        # Users block: counts both the platform-staff user and the
        # populated tenant's user (and any extras Django creates).
        assert body["users"]["total"] >= 2

        # Ingestion block: 2 jobs created, all in last 7d.
        assert body["ingestion"]["total"] >= 2
        assert body["ingestion"]["last_7d"] >= 2

        # Invoices: 1 invoice in pending_review.
        assert body["invoices"]["total"] >= 1
        assert body["invoices"]["pending_review"] >= 1

        # Inbox: 1 open item.
        assert body["inbox"]["open"] >= 1

        # Audit: at least the 3 we recorded plus the overview-load event itself.
        assert body["audit"]["total"] >= 4

        # Engines block has the breakdown shape, even when empty.
        assert "active" in body["engines"]
        assert isinstance(body["engines"]["calls_last_7d"], list)

    def test_overview_load_emits_audit_event(
        self, staff_user, populated_platform
    ) -> None:
        client = Client()
        client.force_login(staff_user)
        before = AuditEvent.objects.filter(
            action_type="admin.platform_overview_viewed"
        ).count()
        client.get("/api/v1/admin/overview/")
        after = AuditEvent.objects.filter(
            action_type="admin.platform_overview_viewed"
        ).count()
        assert after == before + 1

        event = (
            AuditEvent.objects.filter(action_type="admin.platform_overview_viewed")
            .order_by("-sequence")
            .first()
        )
        # System-level event (no tenant — crosses tenants).
        assert event.organization_id is None
        # Counter snapshot included; values themselves not sensitive.
        assert "counters" in event.payload
