"""Tests for ExtractionCorrection capture (Slice 44).

Per DATA_MODEL.md §93 the platform records every human correction as
training data for the engine selection / calibration pipeline. The
audit event records the change as a fact; this table records it as a
queryable, structured row.

These tests exercise update_invoice and assert that:
  - Header field corrections produce a row with field_name = the
    Invoice attribute, original/corrected JSON-encoded.
  - Line-item cell corrections use the
    ``line_items[<line_number>].<field>`` naming.
  - Line additions produce a row with original_value="" and
    corrected_value=<JSON snapshot>.
  - Line removals produce a row with original_value=<JSON snapshot>
    and corrected_value="".
  - No-op edits don't write rows.
  - The user_id and extracted_by_engine columns are populated.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from apps.identity.models import Organization, OrganizationMembership, Role, User
from apps.ingestion.models import IngestionJob
from apps.submission.models import ExtractionCorrection, Invoice, LineItem
from apps.submission.services import update_invoice


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org_user(seeded) -> tuple[Organization, User]:
    org = Organization.objects.create(
        legal_name="Acme", tin="C10000000001", contact_email="ops@acme"
    )
    user = User.objects.create_user(email="o@acme.test", password="x")
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name="owner")
    )
    return org, user


@pytest.fixture
def invoice_with_line(org_user) -> Invoice:
    org, _ = org_user
    job = IngestionJob.objects.create(
        organization=org,
        source_channel=IngestionJob.SourceChannel.WEB_UPLOAD,
        original_filename="i.pdf",
        file_size=10,
        file_mime_type="application/pdf",
        s3_object_key=f"tenants/{org.id}/ingestion/{uuid4()}/i.pdf",
        status=IngestionJob.Status.READY_FOR_REVIEW,
    )
    invoice = Invoice.objects.create(
        organization=org,
        ingestion_job_id=job.id,
        status=Invoice.Status.READY_FOR_REVIEW,
        invoice_number="INV-EXTRACTED",
        currency_code="MYR",
        structuring_engine="ollama-structure",
    )
    LineItem.objects.create(
        organization=org,
        invoice=invoice,
        line_number=1,
        description="extracted desc",
        quantity="1",
        unit_price_excl_tax="100.00",
    )
    return invoice


@pytest.mark.django_db
class TestHeaderCorrections:
    def test_header_change_creates_correction(self, org_user, invoice_with_line) -> None:
        org, user = org_user
        update_invoice(
            organization_id=org.id,
            invoice_id=invoice_with_line.id,
            updates={"invoice_number": "INV-CORRECTED"},
            actor_user_id=user.id,
        )

        rows = list(ExtractionCorrection.objects.filter(invoice=invoice_with_line))
        assert len(rows) == 1
        row = rows[0]
        assert row.field_name == "invoice_number"
        assert row.original_value == "INV-EXTRACTED"
        assert row.corrected_value == "INV-CORRECTED"
        assert row.extracted_by_engine == "ollama-structure"
        assert row.user_id == user.id
        assert row.organization_id == org.id

    def test_no_op_edit_does_not_create_correction(self, org_user, invoice_with_line) -> None:
        org, user = org_user
        update_invoice(
            organization_id=org.id,
            invoice_id=invoice_with_line.id,
            updates={"invoice_number": "INV-EXTRACTED"},
            actor_user_id=user.id,
        )
        assert ExtractionCorrection.objects.filter(invoice=invoice_with_line).count() == 0

    def test_multiple_header_changes_create_multiple_rows(
        self, org_user, invoice_with_line
    ) -> None:
        org, user = org_user
        update_invoice(
            organization_id=org.id,
            invoice_id=invoice_with_line.id,
            updates={
                "invoice_number": "INV-NEW",
                "supplier_legal_name": "Acme Supplies",
            },
            actor_user_id=user.id,
        )
        rows = list(
            ExtractionCorrection.objects.filter(invoice=invoice_with_line).order_by("field_name")
        )
        assert len(rows) == 2
        assert {r.field_name for r in rows} == {"invoice_number", "supplier_legal_name"}


@pytest.mark.django_db
class TestLineItemCorrections:
    def test_cell_edit_uses_line_items_naming(self, org_user, invoice_with_line) -> None:
        org, user = org_user
        update_invoice(
            organization_id=org.id,
            invoice_id=invoice_with_line.id,
            updates={"line_items": [{"line_number": 1, "description": "corrected desc"}]},
            actor_user_id=user.id,
        )
        rows = list(
            ExtractionCorrection.objects.filter(
                invoice=invoice_with_line, field_name__startswith="line_items["
            )
        )
        assert len(rows) == 1
        row = rows[0]
        assert row.field_name == "line_items[1].description"
        assert row.original_value == "extracted desc"
        assert row.corrected_value == "corrected desc"

    def test_line_add_records_blank_original(self, org_user, invoice_with_line) -> None:
        org, user = org_user
        update_invoice(
            organization_id=org.id,
            invoice_id=invoice_with_line.id,
            updates={"add_line_items": [{"description": "newly added widget", "quantity": "5"}]},
            actor_user_id=user.id,
        )
        # Line numbers start at max(existing) + 1 = 2.
        row = ExtractionCorrection.objects.get(
            invoice=invoice_with_line, field_name="line_items[2]"
        )
        assert row.original_value == ""
        # corrected_value is a JSON dict with the added line's fields.
        snapshot = json.loads(row.corrected_value)
        assert snapshot["description"] == "newly added widget"
        assert snapshot["quantity"] == "5"
        assert snapshot["line_number"] == 2

    def test_line_remove_records_blank_corrected(self, org_user, invoice_with_line) -> None:
        org, user = org_user
        update_invoice(
            organization_id=org.id,
            invoice_id=invoice_with_line.id,
            updates={"remove_line_items": [1]},
            actor_user_id=user.id,
        )
        row = ExtractionCorrection.objects.get(
            invoice=invoice_with_line, field_name="line_items[1]"
        )
        assert row.corrected_value == ""
        snapshot = json.loads(row.original_value)
        assert snapshot["line_number"] == 1
        assert snapshot["description"] == "extracted desc"


@pytest.mark.django_db
class TestCorrectionTrainingDataShape:
    """Per DATA_MODEL.md the table is the queryable training surface."""

    def test_engine_attribution_populated(self, org_user, invoice_with_line) -> None:
        """The structuring_engine on the Invoice carries through to the row.

        Lets a future analytics query say "ollama-structure had a 23%
        correction rate on supplier_tin last month" without joining
        through Invoice.structuring_engine.
        """
        org, user = org_user
        update_invoice(
            organization_id=org.id,
            invoice_id=invoice_with_line.id,
            updates={"invoice_number": "X"},
            actor_user_id=user.id,
        )
        row = ExtractionCorrection.objects.filter(invoice=invoice_with_line).first()
        assert row is not None
        assert row.extracted_by_engine == "ollama-structure"

    def test_blank_to_value_is_a_correction(self, org_user, invoice_with_line) -> None:
        """A field the extractor left empty + user filled in IS a
        correction — the training signal is "the model missed this"."""
        org, user = org_user
        # supplier_tin is blank by default on the fixture invoice.
        update_invoice(
            organization_id=org.id,
            invoice_id=invoice_with_line.id,
            updates={"supplier_tin": "C12345678901"},
            actor_user_id=user.id,
        )
        row = ExtractionCorrection.objects.get(invoice=invoice_with_line, field_name="supplier_tin")
        assert row.original_value == ""
        assert row.corrected_value == "C12345678901"
