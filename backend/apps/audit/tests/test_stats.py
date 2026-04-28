"""Tests for ``stats_for_organization`` + the GET /audit/stats/ endpoint.

The KPI tile on the dashboard reads from these. The test surface covers:

  - totals roll up only events for the active org (RLS belt-and-suspenders).
  - ``last_24h`` and ``last_7d`` honor their windows.
  - sparkline length always matches the requested ``sparkline_days`` and is
    gap-filled with zero-count days so the front-end renders a complete window.
  - the endpoint requires authentication and an active organization.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import record_event, stats_for_organization
from apps.identity.models import Organization, Role


def _make_org(legal_name: str, tin: str) -> Organization:
    return Organization.objects.create(
        legal_name=legal_name, tin=tin, contact_email=f"ops@{tin.lower()}.example"
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
    assert response.status_code == 201
    return client, response.json()["active_organization_id"]


@pytest.mark.django_db
class TestStatsService:
    def test_counts_roll_up_for_one_org(self) -> None:
        org = _make_org("Solo Sdn Bhd", "C10000000001")
        for _ in range(3):
            record_event(
                action_type="x.thing",
                actor_type=AuditEvent.ActorType.USER,
                organization_id=str(org.id),
            )

        result = stats_for_organization(organization_id=org.id)
        assert result["total"] == 3
        assert result["last_24h"] == 3
        assert result["last_7d"] == 3

    def test_other_orgs_events_are_excluded(self) -> None:
        mine = _make_org("Mine", "C10000000002")
        theirs = _make_org("Theirs", "C10000000003")

        record_event(
            action_type="x", actor_type=AuditEvent.ActorType.USER, organization_id=str(mine.id)
        )
        record_event(
            action_type="x", actor_type=AuditEvent.ActorType.USER, organization_id=str(theirs.id)
        )
        record_event(
            action_type="x", actor_type=AuditEvent.ActorType.USER, organization_id=str(theirs.id)
        )

        assert stats_for_organization(organization_id=mine.id)["total"] == 1
        assert stats_for_organization(organization_id=theirs.id)["total"] == 2

    def test_system_events_with_null_org_are_excluded(self) -> None:
        org = _make_org("ACME", "C10000000004")
        record_event(
            action_type="x", actor_type=AuditEvent.ActorType.USER, organization_id=str(org.id)
        )
        # System event with no org — e.g. nightly chain verification.
        record_event(action_type="system.verify", actor_type=AuditEvent.ActorType.SERVICE)

        assert stats_for_organization(organization_id=org.id)["total"] == 1

    def test_window_filters_respect_timestamps(self) -> None:
        org = _make_org("ACME", "C10000000005")
        now = timezone.now()
        recent = record_event(
            action_type="recent",
            actor_type=AuditEvent.ActorType.USER,
            organization_id=str(org.id),
        )
        old = record_event(
            action_type="old",
            actor_type=AuditEvent.ActorType.USER,
            organization_id=str(org.id),
        )
        # Backdate one event past both windows.
        AuditEvent.objects.filter(pk=old.pk).update(timestamp=now - timedelta(days=10))
        AuditEvent.objects.filter(pk=recent.pk).update(timestamp=now - timedelta(hours=1))

        result = stats_for_organization(organization_id=org.id)
        assert result["total"] == 2
        assert result["last_24h"] == 1
        assert result["last_7d"] == 1

    def test_sparkline_is_gap_filled_to_requested_length(self) -> None:
        org = _make_org("ACME", "C10000000006")
        record_event(
            action_type="x", actor_type=AuditEvent.ActorType.USER, organization_id=str(org.id)
        )

        result = stats_for_organization(organization_id=org.id, sparkline_days=7)
        assert len(result["sparkline"]) == 7
        # Oldest first, today last.
        dates = [entry["date"] for entry in result["sparkline"]]
        assert dates == sorted(dates)
        # Missing days zero-filled.
        assert any(entry["count"] == 0 for entry in result["sparkline"])
        assert sum(entry["count"] for entry in result["sparkline"]) >= 1

    def test_sparkline_length_is_configurable(self) -> None:
        org = _make_org("ACME", "C10000000007")
        result = stats_for_organization(organization_id=org.id, sparkline_days=14)
        assert len(result["sparkline"]) == 14


@pytest.mark.django_db
class TestStatsEndpoint:
    def test_unauthenticated_is_rejected(self) -> None:
        response = Client().get("/api/v1/audit/stats/")
        assert response.status_code in (401, 403)

    def test_returns_only_active_orgs_data(self, authed_client) -> None:
        client, _org_id = authed_client
        # The registration flow already wrote three audit events for this org
        # (user.registered, organization.created, membership.created) plus a
        # login signal; the active org should see at least those.
        response = client.get("/api/v1/audit/stats/")
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["total"] >= 3
        assert "last_24h" in body
        assert "sparkline" in body
        assert len(body["sparkline"]) == 7

        # Events written under a different org must not appear in the
        # active org's totals.
        other_org = _make_org("Other", "C99999999999")
        baseline_total = body["total"]
        record_event(
            action_type="x",
            actor_type=AuditEvent.ActorType.USER,
            organization_id=str(other_org.id),
        )

        response = client.get("/api/v1/audit/stats/")
        assert response.json()["total"] == baseline_total

    def test_no_active_org_returns_400(self, seeded_roles) -> None:
        # Authenticate but do not select an organization.
        from apps.identity.models import User

        user = User.objects.create_user(email="solo@example.com", password="x")
        client = Client()
        client.force_login(user)
        response = client.get("/api/v1/audit/stats/")
        assert response.status_code == 400
