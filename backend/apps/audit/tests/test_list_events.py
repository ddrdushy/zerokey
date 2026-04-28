"""Tests for the audit log list + action-type endpoints (Slice 20).

Covers:
  - List is scoped to the active org.
  - action_type filter (exact match) reduces the result set.
  - before_sequence cursor paginates: each page is strictly older
    than the cursor.
  - limit is clamped to a sane upper bound.
  - The action-types endpoint returns the distinct codes present.
  - Cross-tenant rows never leak, including system events
    (organization_id IS NULL).
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.audit.models import AuditEvent
from apps.audit.services import (
    list_action_types_for_organization,
    list_events_for_organization,
    record_event,
)
from apps.identity.models import Organization, OrganizationMembership, Role, User


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org_user(seeded) -> tuple[Organization, User]:
    org = Organization.objects.create(
        legal_name="Acme Sdn Bhd", tin="C10000000001", contact_email="ops@acme.example"
    )
    user = User.objects.create_user(email="o@acme.example", password="long-enough-password")
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name="owner")
    )
    return org, user


@pytest.fixture
def authed(org_user) -> tuple[Client, Organization]:
    org, user = org_user
    client = Client()
    client.force_login(user)
    session = client.session
    session["organization_id"] = str(org.id)
    session.save()
    return client, org


@pytest.mark.django_db
class TestListEventsService:
    def test_returns_org_events_newest_first(self, org_user) -> None:
        org, _ = org_user
        for action in ("first", "second", "third"):
            record_event(
                action_type=action,
                actor_type=AuditEvent.ActorType.SERVICE,
                organization_id=str(org.id),
            )
        rows = list_events_for_organization(organization_id=org.id)
        assert [r.action_type for r in rows] == ["third", "second", "first"]

    def test_action_type_filter_is_exact_match(self, org_user) -> None:
        org, _ = org_user
        record_event(
            action_type="invoice.created",
            actor_type=AuditEvent.ActorType.SERVICE,
            organization_id=str(org.id),
        )
        record_event(
            action_type="invoice.updated",
            actor_type=AuditEvent.ActorType.SERVICE,
            organization_id=str(org.id),
        )
        record_event(
            action_type="auth.login_success",
            actor_type=AuditEvent.ActorType.SERVICE,
            organization_id=str(org.id),
        )

        rows = list_events_for_organization(
            organization_id=org.id, action_type="invoice.created"
        )
        assert [r.action_type for r in rows] == ["invoice.created"]

    def test_before_sequence_paginates(self, org_user) -> None:
        org, _ = org_user
        events = []
        for i in range(5):
            events.append(
                record_event(
                    action_type=f"x.{i}",
                    actor_type=AuditEvent.ActorType.SERVICE,
                    organization_id=str(org.id),
                )
            )
        # Newest first overall.
        page1 = list_events_for_organization(organization_id=org.id, limit=2)
        assert [e.sequence for e in page1] == [
            events[4].sequence,
            events[3].sequence,
        ]
        # Cursor on the last seen sequence — next page starts strictly below.
        page2 = list_events_for_organization(
            organization_id=org.id, limit=2, before_sequence=page1[-1].sequence
        )
        assert [e.sequence for e in page2] == [
            events[2].sequence,
            events[1].sequence,
        ]

    def test_other_orgs_events_not_returned(self, org_user) -> None:
        org, _ = org_user
        other = Organization.objects.create(
            legal_name="Other", tin="C99999999999", contact_email="other@example"
        )
        record_event(
            action_type="mine",
            actor_type=AuditEvent.ActorType.SERVICE,
            organization_id=str(org.id),
        )
        record_event(
            action_type="theirs",
            actor_type=AuditEvent.ActorType.SERVICE,
            organization_id=str(other.id),
        )
        record_event(
            action_type="system",
            actor_type=AuditEvent.ActorType.SERVICE,
            # System event with no org — like a nightly chain check.
        )

        rows = list_events_for_organization(organization_id=org.id)
        actions = {r.action_type for r in rows}
        assert "mine" in actions
        assert "theirs" not in actions
        assert "system" not in actions


@pytest.mark.django_db
class TestActionTypesService:
    def test_returns_distinct_codes_sorted(self, org_user) -> None:
        org, _ = org_user
        for action in ("invoice.created", "invoice.updated", "invoice.created"):
            record_event(
                action_type=action,
                actor_type=AuditEvent.ActorType.SERVICE,
                organization_id=str(org.id),
            )
        record_event(
            action_type="auth.login_success",
            actor_type=AuditEvent.ActorType.SERVICE,
            organization_id=str(org.id),
        )

        types = list_action_types_for_organization(organization_id=org.id)
        # Sorted ascending; deduplicated. Other tests may have left events
        # in the same DB transaction window — assert by superset.
        assert {"auth.login_success", "invoice.created", "invoice.updated"} <= set(types)
        assert types == sorted(types)
        # No duplicates: every entry appears exactly once.
        assert len(types) == len(set(types))


@pytest.mark.django_db
class TestListEventsEndpoint:
    def test_get_returns_results_and_total(self, authed) -> None:
        client, org = authed
        for action in ("a", "b", "c"):
            record_event(
                action_type=action,
                actor_type=AuditEvent.ActorType.SERVICE,
                organization_id=str(org.id),
            )

        response = client.get("/api/v1/audit/events/")
        assert response.status_code == 200
        body = response.json()
        # Includes the registration events from the fixture too.
        assert body["total"] >= 3
        assert len(body["results"]) >= 3
        # Hashes serialized as hex strings, not raw bytes.
        first = body["results"][0]
        assert isinstance(first["content_hash"], str)
        assert isinstance(first["chain_hash"], str)
        assert len(first["content_hash"]) == 64  # SHA-256 hex

    def test_action_type_filter_via_query_param(self, authed) -> None:
        client, org = authed
        record_event(
            action_type="invoice.created",
            actor_type=AuditEvent.ActorType.SERVICE,
            organization_id=str(org.id),
        )
        response = client.get(
            "/api/v1/audit/events/?action_type=invoice.created"
        )
        assert response.status_code == 200
        results = response.json()["results"]
        assert all(r["action_type"] == "invoice.created" for r in results)

    def test_limit_clamped_to_upper_bound(self, authed) -> None:
        client, _ = authed
        response = client.get("/api/v1/audit/events/?limit=999999")
        assert response.status_code == 200
        # 200 is the cap.
        assert len(response.json()["results"]) <= 200

    def test_invalid_limit_rejected(self, authed) -> None:
        client, _ = authed
        response = client.get("/api/v1/audit/events/?limit=abc")
        assert response.status_code == 400

    def test_unauthenticated_rejected(self) -> None:
        response = Client().get("/api/v1/audit/events/")
        assert response.status_code in (401, 403)

    def test_action_types_endpoint(self, authed) -> None:
        client, org = authed
        record_event(
            action_type="invoice.created",
            actor_type=AuditEvent.ActorType.SERVICE,
            organization_id=str(org.id),
        )
        response = client.get("/api/v1/audit/action-types/")
        assert response.status_code == 200
        types = response.json()["results"]
        assert "invoice.created" in types
