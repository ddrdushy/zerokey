"""Tests for the cross-tenant audit log endpoints (Slice 34)."""

from __future__ import annotations

import pytest
from django.test import Client

from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.identity.models import Organization, OrganizationMembership, Role, User


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def staff_user(seeded) -> User:
    return User.objects.create_user(
        email="staff@symprio.com",
        password="long-enough-password",
        is_staff=True,
    )


@pytest.fixture
def two_orgs_with_events(seeded) -> tuple[Organization, Organization]:
    """Two orgs with events apiece — confirms cross-tenant aggregation works."""
    org_a = Organization.objects.create(
        legal_name="Acme A", tin="C10000000001", contact_email="ops@a.example"
    )
    org_b = Organization.objects.create(
        legal_name="Acme B", tin="C10000000002", contact_email="ops@b.example"
    )
    user_a = User.objects.create_user(email="a@a.example", password="x")
    user_b = User.objects.create_user(email="b@b.example", password="x")
    OrganizationMembership.objects.create(
        user=user_a, organization=org_a, role=Role.objects.get(name="owner")
    )
    OrganizationMembership.objects.create(
        user=user_b, organization=org_b, role=Role.objects.get(name="owner")
    )
    for _ in range(3):
        record_event(
            action_type="invoice.created",
            actor_type=AuditEvent.ActorType.USER,
            actor_id=str(user_a.id),
            organization_id=str(org_a.id),
        )
    for _ in range(2):
        record_event(
            action_type="invoice.updated",
            actor_type=AuditEvent.ActorType.USER,
            actor_id=str(user_b.id),
            organization_id=str(org_b.id),
        )
    return org_a, org_b


@pytest.mark.django_db
class TestPlatformAuditEvents:
    def test_unauthenticated_rejected(self, two_orgs_with_events) -> None:
        response = Client().get("/api/v1/admin/audit/events/")
        assert response.status_code in (401, 403)

    def test_customer_user_403(self, two_orgs_with_events, seeded) -> None:
        user = User.objects.create_user(email="cust@x", password="x")
        client = Client()
        client.force_login(user)
        response = client.get("/api/v1/admin/audit/events/")
        assert response.status_code == 403

    def test_staff_sees_all_orgs(self, staff_user, two_orgs_with_events) -> None:
        client = Client()
        client.force_login(staff_user)
        response = client.get("/api/v1/admin/audit/events/")
        assert response.status_code == 200
        body = response.json()
        # 3 events from org A + 2 from org B + the one this very call
        # produced (admin.platform_audit_listed). Plus admin.platform_audit_listed
        # already fired during count, etc. Just assert >= 5.
        assert body["total"] >= 5
        results = body["results"]
        org_ids = {evt["organization_id"] for evt in results if evt["organization_id"]}
        assert len(org_ids) >= 2

    def test_filter_by_organization(self, staff_user, two_orgs_with_events) -> None:
        org_a, _ = two_orgs_with_events
        client = Client()
        client.force_login(staff_user)
        response = client.get(f"/api/v1/admin/audit/events/?organization_id={org_a.id}")
        assert response.status_code == 200
        results = response.json()["results"]
        # All returned events belong to org A.
        for evt in results:
            assert evt["organization_id"] == str(org_a.id)

    def test_filter_by_action_type(self, staff_user, two_orgs_with_events) -> None:
        client = Client()
        client.force_login(staff_user)
        response = client.get("/api/v1/admin/audit/events/?action_type=invoice.created")
        assert response.status_code == 200
        for evt in response.json()["results"]:
            assert evt["action_type"] == "invoice.created"

    def test_invalid_limit_returns_400(self, staff_user) -> None:
        client = Client()
        client.force_login(staff_user)
        response = client.get("/api/v1/admin/audit/events/?limit=oops")
        assert response.status_code == 400

    def test_listing_itself_creates_audit_event(self, staff_user, two_orgs_with_events) -> None:
        """Cross-tenant reads are themselves audited (admin.platform_audit_listed)."""
        client = Client()
        client.force_login(staff_user)

        before = AuditEvent.objects.filter(action_type="admin.platform_audit_listed").count()
        client.get("/api/v1/admin/audit/events/?limit=10")
        after = AuditEvent.objects.filter(action_type="admin.platform_audit_listed").count()
        assert after == before + 1

        # The audit event is system-level (org_id=None — crosses tenants
        # by definition) and the actor is the staff user.
        event = (
            AuditEvent.objects.filter(action_type="admin.platform_audit_listed")
            .order_by("-sequence")
            .first()
        )
        assert event.organization_id is None
        assert event.actor_id == str(staff_user.id)
        assert event.payload["filters"]["limit"] == 10


@pytest.mark.django_db
class TestPlatformActionTypes:
    def test_returns_distinct_set_across_all_tenants(
        self, staff_user, two_orgs_with_events
    ) -> None:
        client = Client()
        client.force_login(staff_user)
        # Two calls so the second call sees the first call's own audit
        # event in its result set. (The audit event is recorded AFTER
        # the query runs, so the very first call doesn't see itself.)
        client.get("/api/v1/admin/audit/action-types/")
        response = client.get("/api/v1/admin/audit/action-types/")
        assert response.status_code == 200
        results = response.json()["results"]
        # invoice.created and invoice.updated come from the fixture data.
        assert "invoice.created" in results
        assert "invoice.updated" in results
        # The action-types listing audits itself — the second call sees
        # the first call's event.
        assert "admin.platform_action_types_listed" in results

    def test_customer_403(self, seeded) -> None:
        user = User.objects.create_user(email="cust@x", password="x")
        client = Client()
        client.force_login(user)
        response = client.get("/api/v1/admin/audit/action-types/")
        assert response.status_code == 403
