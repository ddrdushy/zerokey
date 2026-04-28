"""Tests for the customer-facing engine-activity surface (Slice 22)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.extraction.models import Engine, EngineCall
from apps.extraction.services import (
    engine_summary_for_organization,
    list_engine_calls_for_organization,
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
    user = User.objects.create_user(
        email="o@acme.example", password="long-enough-password"
    )
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


def _make_call(
    org: Organization,
    *,
    engine: Engine,
    outcome: str = EngineCall.Outcome.SUCCESS,
    duration_ms: int = 1000,
    cost_micros: int = 1000,
    started_at=None,
) -> EngineCall:
    return EngineCall.objects.create(
        engine=engine,
        organization_id=org.id,
        started_at=started_at or timezone.now(),
        duration_ms=duration_ms,
        outcome=outcome,
        cost_micros=cost_micros,
    )


@pytest.fixture
def engines(db) -> tuple[Engine, Engine]:
    pdfplumber, _ = Engine.objects.update_or_create(
        name="pdfplumber",
        defaults={"vendor": "pdfplumber", "capability": "text_extract"},
    )
    claude, _ = Engine.objects.update_or_create(
        name="anthropic-claude-sonnet-vision",
        defaults={"vendor": "anthropic", "capability": "vision_extract"},
    )
    return pdfplumber, claude


@pytest.mark.django_db
class TestEngineSummary:
    def test_rolls_up_per_engine_with_correct_counts(self, org_user, engines) -> None:
        org, _ = org_user
        pdfplumber, claude = engines

        for _ in range(5):
            _make_call(org, engine=pdfplumber, duration_ms=200)
        _make_call(org, engine=pdfplumber, outcome=EngineCall.Outcome.FAILURE, duration_ms=400)
        for _ in range(2):
            _make_call(
                org, engine=claude, outcome=EngineCall.Outcome.UNAVAILABLE, duration_ms=10
            )

        rollup = engine_summary_for_organization(organization_id=org.id)
        # Two engines, sorted by total_calls desc — pdfplumber 6, claude 2.
        assert [r["engine_name"] for r in rollup] == [
            "pdfplumber",
            "anthropic-claude-sonnet-vision",
        ]
        pdf_row = rollup[0]
        assert pdf_row["total_calls"] == 6
        assert pdf_row["success_count"] == 5
        assert pdf_row["failure_count"] == 1
        assert pdf_row["unavailable_count"] == 0
        # 5/6 success rate.
        assert pdf_row["success_rate"] == pytest.approx(5 / 6)
        # Avg of (200, 200, 200, 200, 200, 400) = 233.33 → int rounds.
        assert pdf_row["avg_duration_ms"] == 233

        claude_row = rollup[1]
        assert claude_row["total_calls"] == 2
        assert claude_row["unavailable_count"] == 2
        assert claude_row["success_rate"] == 0.0

    def test_other_orgs_calls_not_returned(self, org_user, engines) -> None:
        org, _ = org_user
        other = Organization.objects.create(
            legal_name="Other", tin="C99999999999", contact_email="other@example"
        )
        pdfplumber, _ = engines

        _make_call(org, engine=pdfplumber)
        _make_call(other, engine=pdfplumber)
        _make_call(other, engine=pdfplumber)

        rollup = engine_summary_for_organization(organization_id=org.id)
        # Only this org's call counted.
        assert rollup[0]["total_calls"] == 1

    def test_empty_when_no_calls(self, org_user) -> None:
        org, _ = org_user
        assert engine_summary_for_organization(organization_id=org.id) == []


@pytest.mark.django_db
class TestEngineCallsList:
    def test_returns_calls_newest_first(self, org_user, engines) -> None:
        org, _ = org_user
        pdfplumber, _ = engines
        # Three calls, with deliberate timestamps so the order is unambiguous.
        now = timezone.now()
        c1 = _make_call(org, engine=pdfplumber, started_at=now - timedelta(minutes=10))
        c2 = _make_call(org, engine=pdfplumber, started_at=now - timedelta(minutes=5))
        c3 = _make_call(org, engine=pdfplumber, started_at=now)

        rows = list_engine_calls_for_organization(organization_id=org.id)
        assert [r.id for r in rows] == [c3.id, c2.id, c1.id]

    def test_before_started_at_paginates(self, org_user, engines) -> None:
        org, _ = org_user
        pdfplumber, _ = engines
        now = timezone.now()
        for i in range(5):
            _make_call(
                org, engine=pdfplumber, started_at=now - timedelta(minutes=i)
            )

        page1 = list_engine_calls_for_organization(organization_id=org.id, limit=2)
        cursor = page1[-1].started_at
        page2 = list_engine_calls_for_organization(
            organization_id=org.id, limit=2, before_started_at=cursor
        )
        assert len(page1) == 2
        assert len(page2) == 2
        # Page 2 starts strictly older than the cursor.
        assert all(r.started_at < cursor for r in page2)

    def test_other_orgs_calls_not_returned(self, org_user, engines) -> None:
        org, _ = org_user
        other = Organization.objects.create(
            legal_name="Other", tin="C99999999999", contact_email="other@example"
        )
        pdfplumber, _ = engines
        _make_call(org, engine=pdfplumber)
        _make_call(other, engine=pdfplumber)

        rows = list_engine_calls_for_organization(organization_id=org.id)
        assert len(rows) == 1
        assert str(rows[0].organization_id) == str(org.id)


@pytest.mark.django_db
class TestEngineActivityEndpoints:
    def test_summary_endpoint_returns_results(self, authed, engines) -> None:
        client, org = authed
        pdfplumber, _ = engines
        _make_call(org, engine=pdfplumber)

        response = client.get("/api/v1/engines/")
        assert response.status_code == 200
        body = response.json()
        assert len(body["results"]) == 1
        assert body["results"][0]["engine_name"] == "pdfplumber"
        assert body["results"][0]["total_calls"] == 1
        assert body["results"][0]["success_rate"] == 1.0

    def test_calls_endpoint_returns_results(self, authed, engines) -> None:
        client, org = authed
        pdfplumber, _ = engines
        _make_call(org, engine=pdfplumber)

        response = client.get("/api/v1/engines/calls/")
        assert response.status_code == 200
        body = response.json()
        assert len(body["results"]) == 1
        first = body["results"][0]
        # Compact shape with engine name + vendor surfaced via SerializerMethodField.
        assert first["engine_name"] == "pdfplumber"
        assert first["vendor"] == "pdfplumber"
        assert first["outcome"] == "success"

    def test_invalid_limit_rejected(self, authed) -> None:
        client, _ = authed
        response = client.get("/api/v1/engines/calls/?limit=abc")
        assert response.status_code == 400

    def test_invalid_before_started_at_rejected(self, authed) -> None:
        client, _ = authed
        response = client.get(
            "/api/v1/engines/calls/?before_started_at=not-a-date"
        )
        assert response.status_code == 400

    def test_unauthenticated_rejected(self) -> None:
        response = Client().get("/api/v1/engines/")
        assert response.status_code in (401, 403)
