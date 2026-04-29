"""Tests for the platform tenant directory (Slice 35)."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.audit.models import AuditEvent
from apps.identity.models import Organization, OrganizationMembership, Role, User
from apps.ingestion.models import IngestionJob


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def staff_user(seeded) -> User:
    return User.objects.create_user(email="staff@symprio.com", password="x", is_staff=True)


@pytest.fixture
def populated_orgs(seeded) -> tuple[Organization, Organization]:
    """Two orgs with different shapes:
    - Acme has 2 members + 3 ingestion jobs.
    - Beta has 1 member + 0 jobs (idle tenant).
    """
    acme = Organization.objects.create(
        legal_name="Acme Sdn Bhd", tin="C10000000001", contact_email="ops@acme.example"
    )
    beta = Organization.objects.create(
        legal_name="Beta Trading", tin="C99999999999", contact_email="ops@beta.example"
    )
    user_a = User.objects.create_user(email="a@acme.example", password="x")
    user_b = User.objects.create_user(email="b@acme.example", password="x")
    user_c = User.objects.create_user(email="c@beta.example", password="x")
    OrganizationMembership.objects.create(
        user=user_a, organization=acme, role=Role.objects.get(name="owner")
    )
    OrganizationMembership.objects.create(
        user=user_b, organization=acme, role=Role.objects.get(name="viewer")
    )
    OrganizationMembership.objects.create(
        user=user_c, organization=beta, role=Role.objects.get(name="owner")
    )
    for i in range(3):
        IngestionJob.objects.create(
            organization=acme,
            source_channel=IngestionJob.SourceChannel.WEB_UPLOAD,
            original_filename=f"invoice-{i}.pdf",
            file_size=10,
            file_mime_type="application/pdf",
            s3_object_key=f"tenants/{acme.id}/ingestion/{i}/file.pdf",
            status=IngestionJob.Status.READY_FOR_REVIEW,
        )
    return acme, beta


@pytest.mark.django_db
class TestPlatformTenantsEndpoint:
    def test_unauthenticated_rejected(self, populated_orgs) -> None:
        response = Client().get("/api/v1/admin/tenants/")
        assert response.status_code in (401, 403)

    def test_customer_403(self, populated_orgs, seeded) -> None:
        user = User.objects.create_user(email="cust@x", password="x")
        client = Client()
        client.force_login(user)
        response = client.get("/api/v1/admin/tenants/")
        assert response.status_code == 403

    def test_staff_lists_every_tenant(self, staff_user, populated_orgs) -> None:
        client = Client()
        client.force_login(staff_user)
        response = client.get("/api/v1/admin/tenants/")
        assert response.status_code == 200
        results = response.json()["results"]
        names = {row["legal_name"] for row in results}
        assert "Acme Sdn Bhd" in names
        assert "Beta Trading" in names

    def test_member_and_job_counts(self, staff_user, populated_orgs) -> None:
        client = Client()
        client.force_login(staff_user)
        response = client.get("/api/v1/admin/tenants/")
        rows = {row["legal_name"]: row for row in response.json()["results"]}
        acme = rows["Acme Sdn Bhd"]
        beta = rows["Beta Trading"]
        assert acme["member_count"] == 2
        assert acme["ingestion_jobs_total"] == 3
        assert acme["ingestion_jobs_recent_7d"] == 3
        assert beta["member_count"] == 1
        assert beta["ingestion_jobs_total"] == 0

    def test_search_by_legal_name_substring(self, staff_user, populated_orgs) -> None:
        client = Client()
        client.force_login(staff_user)
        response = client.get("/api/v1/admin/tenants/?search=acme")
        rows = response.json()["results"]
        assert len(rows) == 1
        assert rows[0]["legal_name"] == "Acme Sdn Bhd"

    def test_search_by_tin(self, staff_user, populated_orgs) -> None:
        client = Client()
        client.force_login(staff_user)
        response = client.get("/api/v1/admin/tenants/?search=99999")
        rows = response.json()["results"]
        assert len(rows) == 1
        assert rows[0]["legal_name"] == "Beta Trading"

    def test_invalid_limit_returns_400(self, staff_user) -> None:
        client = Client()
        client.force_login(staff_user)
        response = client.get("/api/v1/admin/tenants/?limit=oops")
        assert response.status_code == 400

    def test_listing_creates_audit_event(self, staff_user, populated_orgs) -> None:
        client = Client()
        client.force_login(staff_user)
        before = AuditEvent.objects.filter(action_type="admin.platform_tenants_listed").count()
        client.get("/api/v1/admin/tenants/?search=acme")
        after = AuditEvent.objects.filter(action_type="admin.platform_tenants_listed").count()
        assert after == before + 1
        # The event records the search filter (truncated to 64 chars).
        event = (
            AuditEvent.objects.filter(action_type="admin.platform_tenants_listed")
            .order_by("-sequence")
            .first()
        )
        assert event.organization_id is None
        assert event.payload["search"] == "acme"
