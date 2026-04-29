"""Tests for the archive surface (Slice 50)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from apps.archive.models import ArchivedDocument
from apps.archive.services import (
    archive_b2c_transaction,
    archive_ingestion_source,
    archive_invoice_snapshot,
    list_for_invoice,
    list_for_org,
)
from apps.audit.models import AuditEvent
from apps.identity.models import Organization, OrganizationMembership, Role, User


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org(seeded) -> Organization:
    org = Organization.objects.create(legal_name="Acme", tin="C10000000001", contact_email="o@a")
    user = User.objects.create_user(email="o@a.test", password="x")
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name="owner")
    )
    return org


@pytest.mark.django_db
class TestArchiveB2CTransaction:
    def test_creates_row_with_parent_invoice_id(self, org) -> None:
        parent_id = uuid4()
        row = archive_b2c_transaction(
            organization_id=org.id,
            parent_invoice_id=parent_id,
            payload={
                "description": "POS receipt #4421",
                "amount_cents": 25000,
                "tax_amount_cents": 1500,
            },
        )
        assert row.organization_id == org.id
        assert row.document_type == ArchivedDocument.DocumentType.B2C_TRANSACTION
        assert row.parent_invoice_id == parent_id
        assert row.payload["amount_cents"] == 25000
        # 7-year retention (LHDN).
        assert row.retain_until is not None

    def test_list_for_invoice_aggregates_transactions(self, org) -> None:
        parent_id = uuid4()
        for i in range(3):
            archive_b2c_transaction(
                organization_id=org.id,
                parent_invoice_id=parent_id,
                payload={"index": i},
            )
        # Add a different consolidation — should NOT show up in the
        # parent_id query.
        archive_b2c_transaction(
            organization_id=org.id,
            parent_invoice_id=uuid4(),
            payload={"separate": True},
        )

        rows = list_for_invoice(organization_id=org.id, parent_invoice_id=parent_id)
        assert len(rows) == 3

    def test_emits_audit_event(self, org) -> None:
        archive_b2c_transaction(
            organization_id=org.id,
            parent_invoice_id=uuid4(),
            payload={"amount_cents": 100},
        )
        event = (
            AuditEvent.objects.filter(action_type="archive.document_archived")
            .order_by("-sequence")
            .first()
        )
        assert event is not None
        assert event.organization_id == org.id
        assert event.payload["document_type"] == "b2c_transaction"
        assert event.payload["retention_years"] == 7
        # PII not in audit payload (only field/type metadata).
        assert "100" not in str(event.payload).replace("amount_cents", "")


@pytest.mark.django_db
class TestArchiveInvoiceSnapshot:
    def test_keeps_invoice_payload(self, org) -> None:
        invoice_id = uuid4()
        snapshot = {
            "invoice_number": "INV-001",
            "buyer": "Acme",
            "lines": [{"qty": 1, "amount": 5000}],
        }
        row = archive_invoice_snapshot(
            organization_id=org.id,
            invoice_id=invoice_id,
            payload=snapshot,
        )
        assert row.related_entity_id == str(invoice_id)
        assert row.parent_invoice_id is None
        assert row.payload == snapshot


@pytest.mark.django_db
class TestArchiveIngestionSource:
    def test_persists_s3_pointer(self, org) -> None:
        job_id = uuid4()
        row = archive_ingestion_source(
            organization_id=org.id,
            ingestion_job_id=job_id,
            s3_object_key=f"tenants/{org.id}/archive/{job_id}.pdf",
            file_mime_type="application/pdf",
            file_size=12345,
        )
        assert row.s3_object_key.endswith(".pdf")
        assert row.file_size == 12345
        # Ingestion sources have shorter retention (1 year per
        # DATA_MODEL.md). retain_until ~ now + 365d.
        assert row.retain_until is not None


@pytest.mark.django_db
class TestListForOrg:
    def test_filters_by_document_type(self, org) -> None:
        archive_invoice_snapshot(
            organization_id=org.id,
            invoice_id=uuid4(),
            payload={"x": 1},
        )
        archive_b2c_transaction(
            organization_id=org.id,
            parent_invoice_id=uuid4(),
            payload={"y": 2},
        )
        all_rows = list_for_org(organization_id=org.id)
        assert len(all_rows) == 2
        only_snapshots = list_for_org(
            organization_id=org.id,
            document_type=ArchivedDocument.DocumentType.INVOICE_SNAPSHOT,
        )
        assert len(only_snapshots) == 1
        assert only_snapshots[0]["document_type"] == "invoice_snapshot"


@pytest.mark.django_db
class TestRetentionDefaults:
    def test_invoice_snapshot_7_year(self, org) -> None:
        row = archive_invoice_snapshot(
            organization_id=org.id,
            invoice_id=uuid4(),
            payload={},
        )
        from django.utils import timezone

        delta = row.retain_until - timezone.now()
        # 7 * 365 = 2555 days; allow ±2 days for clock skew.
        assert 2553 <= delta.days <= 2557

    def test_ingestion_source_1_year(self, org) -> None:
        row = archive_ingestion_source(
            organization_id=org.id,
            ingestion_job_id=uuid4(),
            s3_object_key="x",
            file_mime_type="application/pdf",
            file_size=1,
        )
        from django.utils import timezone

        delta = row.retain_until - timezone.now()
        assert 363 <= delta.days <= 367
