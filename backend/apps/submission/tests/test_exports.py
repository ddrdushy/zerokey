"""Tests for the CSV exports (Slice 88)."""

from __future__ import annotations

import io
import uuid
from datetime import date
from decimal import Decimal

import pytest
from django.test import Client

from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.identity.models import Organization, OrganizationMembership, Role, User
from apps.submission.models import Invoice


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


def _make_org(seeded, **overrides) -> Organization:
    defaults = dict(legal_name="Acme", tin="C1234567890", contact_email="o@a.example")
    defaults.update(overrides)
    return Organization.objects.create(**defaults)


def _login(org: Organization, role: str = "owner") -> tuple[Client, User]:
    user = User.objects.create_user(email=f"{role}@a.example", password="long-enough-password")
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name=role)
    )
    client = Client()
    client.force_login(user)
    session = client.session
    session["organization_id"] = str(org.id)
    session.save()
    return client, user


def _make_invoice(org: Organization, **overrides) -> Invoice:
    defaults = dict(
        ingestion_job_id=uuid.uuid4(),
        invoice_number="INV-001",
        issue_date=date(2026, 4, 15),
        currency_code="MYR",
        supplier_legal_name="Acme",
        supplier_tin="C1234567890",
        buyer_legal_name="Globex",
        buyer_tin="C9999999999",
        grand_total=Decimal("1000.00"),
        status=Invoice.Status.READY_FOR_REVIEW,
    )
    defaults.update(overrides)
    return Invoice.objects.create(organization=org, **defaults)


# =============================================================================
# Invoice CSV export
# =============================================================================


@pytest.mark.django_db
class TestInvoicesExport:
    def test_owner_can_export(self, seeded) -> None:
        org = _make_org(seeded)
        client, _ = _login(org)
        _make_invoice(org, invoice_number="INV-001", grand_total=Decimal("100.00"))
        _make_invoice(org, invoice_number="INV-002", grand_total=Decimal("200.00"))

        response = client.get("/api/v1/invoices/export.csv")
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/csv")

        body = b"".join(response.streaming_content).decode("utf-8")
        # Header row + two data rows.
        rows = list(csv_rows(body))
        assert rows[0][0] == "invoice_id"
        assert {r[1] for r in rows[1:]} == {"INV-001", "INV-002"}

    def test_filters_by_status(self, seeded) -> None:
        org = _make_org(seeded)
        client, _ = _login(org)
        _make_invoice(org, invoice_number="INV-DRAFT", status=Invoice.Status.READY_FOR_REVIEW)
        _make_invoice(org, invoice_number="INV-DONE", status=Invoice.Status.VALIDATED)

        response = client.get("/api/v1/invoices/export.csv?status=validated")
        assert response.status_code == 200
        body = b"".join(response.streaming_content).decode("utf-8")
        rows = list(csv_rows(body))
        assert {r[1] for r in rows[1:]} == {"INV-DONE"}

    def test_invalid_since_returns_400(self, seeded) -> None:
        org = _make_org(seeded)
        client, _ = _login(org)
        response = client.get("/api/v1/invoices/export.csv?since=not-a-date")
        assert response.status_code == 400

    def test_cross_tenant_isolation(self, seeded) -> None:
        # Org A's user gets only Org A's invoices in the export.
        org_a = _make_org(seeded)
        org_b = _make_org(seeded, legal_name="Other", tin="C99999999999", contact_email="b@b")
        _make_invoice(org_a, invoice_number="A-1")
        _make_invoice(org_b, invoice_number="B-1")
        client, _ = _login(org_a)

        response = client.get("/api/v1/invoices/export.csv")
        body = b"".join(response.streaming_content).decode("utf-8")
        assert "A-1" in body
        assert "B-1" not in body

    def test_export_audit_logged(self, seeded) -> None:
        org = _make_org(seeded)
        client, user = _login(org)
        _make_invoice(org)

        response = client.get("/api/v1/invoices/export.csv")
        # Consume the streaming response so the generator's tail
        # — which records the audit event — actually runs.
        b"".join(response.streaming_content)
        ev = AuditEvent.objects.filter(action_type="submission.export.invoices").first()
        assert ev is not None
        assert ev.payload["row_count"] == 1
        assert ev.actor_id == str(user.id)


# =============================================================================
# Audit CSV export
# =============================================================================


@pytest.mark.django_db
class TestAuditExport:
    def test_export_includes_chain_hash_hex(self, seeded) -> None:
        org = _make_org(seeded)
        client, _ = _login(org)
        record_event(
            action_type="invoice.test.event",
            actor_type=AuditEvent.ActorType.SERVICE,
            actor_id="test",
            organization_id=str(org.id),
            affected_entity_type="Invoice",
            affected_entity_id="x",
            payload={"k": "v"},
        )

        response = client.get("/api/v1/audit/export.csv")
        assert response.status_code == 200
        body = b"".join(response.streaming_content).decode("utf-8")
        rows = list(csv_rows(body))
        assert rows[0][-1] == "chain_hash_hex"
        # Chain hash hex is 64 chars (32 bytes hex-encoded).
        relevant = [r for r in rows[1:] if r[2] == "invoice.test.event"]
        assert len(relevant) == 1
        assert len(relevant[0][-1]) == 64

    def test_filters_by_action_type(self, seeded) -> None:
        org = _make_org(seeded)
        client, _ = _login(org)
        record_event(
            action_type="a.x",
            actor_type=AuditEvent.ActorType.SERVICE,
            actor_id="t",
            organization_id=str(org.id),
            affected_entity_type="X",
            affected_entity_id="1",
            payload={},
        )
        record_event(
            action_type="b.y",
            actor_type=AuditEvent.ActorType.SERVICE,
            actor_id="t",
            organization_id=str(org.id),
            affected_entity_type="Y",
            affected_entity_id="2",
            payload={},
        )

        response = client.get("/api/v1/audit/export.csv?action_type=a.x")
        body = b"".join(response.streaming_content).decode("utf-8")
        rows = list(csv_rows(body))
        types = {r[2] for r in rows[1:]}
        assert types == {"a.x"}

    def test_export_is_audit_logged(self, seeded) -> None:
        org = _make_org(seeded)
        client, user = _login(org)
        record_event(
            action_type="seeding.event",
            actor_type=AuditEvent.ActorType.SERVICE,
            actor_id="t",
            organization_id=str(org.id),
            affected_entity_type="X",
            affected_entity_id="1",
            payload={},
        )
        response = client.get("/api/v1/audit/export.csv")
        b"".join(response.streaming_content)
        ev = AuditEvent.objects.filter(action_type="audit.export.events").first()
        assert ev is not None
        assert ev.actor_id == str(user.id)

    def test_unauthenticated_blocked(self, seeded) -> None:
        response = Client().get("/api/v1/audit/export.csv")
        assert response.status_code in (401, 403)


# =============================================================================
# helpers
# =============================================================================


def csv_rows(body: str):
    import csv as _csv

    return _csv.reader(io.StringIO(body))
