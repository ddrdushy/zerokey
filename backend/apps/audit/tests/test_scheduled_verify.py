"""Tests for the background chain verification task (Slice 27).

Covers:
  - Scheduled run on a clean chain records ``status=ok`` and a system-level
    audit event with ``organization_id IS NULL`` and ``actor_type=service``.
  - Scheduled run on a tampered chain records ``status=tampered``, persists
    the operational ``error_detail``, and the system audit event records
    ``ok=false`` without leaking the offending sequence number into a
    customer-readable surface.
  - Manual run via ``verify_chain_for_visibility`` writes a
    ``ChainVerificationRun`` row with ``source=manual`` so the latest-run
    surface unifies both kinds of trigger.
  - ``latest_chain_verification`` returns ``None`` before any run, returns
    a sanitised shape afterwards (no ``error_detail``).
  - ``GET /api/v1/audit/verify/last/`` returns the latest run for any
    authenticated session with an active org; response shape matches the
    service.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.audit.models import AuditEvent, ChainVerificationRun
from apps.audit.services import (
    latest_chain_verification,
    record_event,
    run_scheduled_chain_verification,
    verify_chain_for_visibility,
)
from apps.audit.tasks import verify_audit_chain
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
def authed(org_user) -> tuple[Client, Organization, User]:
    org, user = org_user
    client = Client()
    client.force_login(user)
    session = client.session
    session["organization_id"] = str(org.id)
    session.save()
    return client, org, user


@pytest.mark.django_db
class TestScheduledVerifyService:
    def test_clean_chain_records_ok_run(self, org_user) -> None:
        org, _user = org_user
        for action in ("a", "b", "c"):
            record_event(
                action_type=action,
                actor_type=AuditEvent.ActorType.SERVICE,
                organization_id=str(org.id),
            )

        run = run_scheduled_chain_verification()
        assert run.status == ChainVerificationRun.Status.OK
        assert run.source == ChainVerificationRun.Source.SCHEDULED
        assert run.events_verified >= 3
        assert run.completed_at is not None
        assert run.error_detail == ""

    def test_clean_chain_emits_system_level_audit_event(self, org_user) -> None:
        org, _user = org_user
        record_event(
            action_type="warmup",
            actor_type=AuditEvent.ActorType.SERVICE,
            organization_id=str(org.id),
        )

        run_scheduled_chain_verification()

        event = (
            AuditEvent.objects.filter(action_type="audit.chain_verified")
            .order_by("-sequence")
            .first()
        )
        assert event is not None
        # System-level: no tenant.
        assert event.organization_id is None
        assert event.actor_type == AuditEvent.ActorType.SERVICE
        assert event.actor_id == "audit.verify_audit_chain"
        # Payload carries ok + counts, plus a source marker so the audit
        # log can distinguish scheduled from manual runs.
        assert event.payload.get("ok") is True
        assert event.payload.get("source") == "scheduled"

    def test_tampered_chain_records_tampered_status(self, org_user) -> None:
        org, _user = org_user
        e1 = record_event(
            action_type="invoice.created",
            actor_type=AuditEvent.ActorType.USER,
            actor_id="u1",
            organization_id=str(org.id),
            payload={"amount": "100.00"},
        )
        # Tamper after the chain hash was computed.
        AuditEvent.objects.filter(pk=e1.pk).update(payload={"amount": "9000.00"})

        run = run_scheduled_chain_verification()
        assert run.status == ChainVerificationRun.Status.TAMPERED
        # Operational detail records what went wrong; never returned to
        # customers (latest-run surface filters it out).
        assert "sequence=" in run.error_detail

        # System audit event records ok=false but doesn't put the sequence
        # in the payload (the audit log itself is global; tenants don't see
        # system events anyway, but the convention is consistent).
        event = (
            AuditEvent.objects.filter(action_type="audit.chain_verified")
            .order_by("-sequence")
            .first()
        )
        assert event.payload.get("ok") is False

    def test_celery_task_invokes_service(self, org_user) -> None:
        # CELERY_TASK_ALWAYS_EAGER is on in test settings — calling the
        # task directly exercises the same path the beat scheduler hits.
        result = verify_audit_chain.apply().get()
        assert result["status"] == ChainVerificationRun.Status.OK
        assert result["events_verified"] >= 0
        # A run row exists.
        assert ChainVerificationRun.objects.filter(id=result["run_id"]).exists()


@pytest.mark.django_db
class TestManualRunSharesStorage:
    def test_manual_verify_writes_run_row(self, org_user) -> None:
        org, user = org_user
        before = ChainVerificationRun.objects.count()

        verify_chain_for_visibility(organization_id=org.id, actor_user_id=user.id)

        after = ChainVerificationRun.objects.count()
        assert after == before + 1
        latest = ChainVerificationRun.objects.order_by("-started_at").first()
        assert latest.source == ChainVerificationRun.Source.MANUAL


@pytest.mark.django_db
class TestLatestVerificationService:
    def test_returns_none_before_any_run(self, db) -> None:
        assert latest_chain_verification() is None

    def test_returns_sanitised_shape_after_run(self, org_user) -> None:
        org, _user = org_user
        record_event(
            action_type="warmup",
            actor_type=AuditEvent.ActorType.SERVICE,
            organization_id=str(org.id),
        )
        run_scheduled_chain_verification()

        latest = latest_chain_verification()
        assert latest is not None
        assert latest["ok"] is True
        assert latest["status"] == "ok"
        assert latest["source"] == "scheduled"
        assert "events_verified" in latest
        assert "started_at" in latest
        assert "completed_at" in latest
        # error_detail is operational and must not leak through.
        assert "error_detail" not in latest

    def test_tampered_run_redacts_sequence_from_customer_view(self, org_user) -> None:
        org, _user = org_user
        e1 = record_event(
            action_type="invoice.created",
            actor_type=AuditEvent.ActorType.USER,
            organization_id=str(org.id),
            payload={"amount": "1.00"},
        )
        AuditEvent.objects.filter(pk=e1.pk).update(payload={"amount": "999.00"})
        run_scheduled_chain_verification()

        latest = latest_chain_verification()
        assert latest is not None
        assert latest["status"] == "tampered"
        assert latest["ok"] is False
        # Generic message; the offending sequence stays in error_detail
        # which is excluded from this surface entirely.
        assert (
            "support" in latest["support_message"].lower()
            or "alert" in latest["support_message"].lower()
        )
        for value in latest.values():
            if isinstance(value, str):
                assert "sequence=" not in value


@pytest.mark.django_db
class TestLatestVerificationEndpoint:
    def test_returns_null_before_any_run(self, authed) -> None:
        client, _org, _user = authed
        response = client.get("/api/v1/audit/verify/last/")
        assert response.status_code == 200
        assert response.json() == {"latest": None}

    def test_returns_latest_after_scheduled_run(self, authed) -> None:
        client, org, _user = authed
        record_event(
            action_type="warmup",
            actor_type=AuditEvent.ActorType.SERVICE,
            organization_id=str(org.id),
        )
        run_scheduled_chain_verification()

        response = client.get("/api/v1/audit/verify/last/")
        assert response.status_code == 200
        body = response.json()
        assert body["latest"] is not None
        assert body["latest"]["status"] == "ok"
        assert body["latest"]["source"] == "scheduled"
        assert "error_detail" not in body["latest"]

    def test_unauthenticated_rejected(self) -> None:
        response = Client().get("/api/v1/audit/verify/last/")
        assert response.status_code in (401, 403)

    def test_no_active_org_returns_400(self, seeded) -> None:
        user = User.objects.create_user(email="solo@example.com", password="long-enough-password")
        client = Client()
        client.force_login(user)
        response = client.get("/api/v1/audit/verify/last/")
        assert response.status_code == 400
