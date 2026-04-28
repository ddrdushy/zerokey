"""Tests for invoice structuring.

The Claude adapter is patched via the registry so unit tests don't need a real
API key. End-to-end exercise against the live docker stack happens manually.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from apps.audit.models import AuditEvent
from apps.extraction.capabilities import (
    EngineUnavailable,
    FieldStructureEngine,
    StructuredExtractResult,
)
from apps.extraction.models import Engine, EngineCall, EngineRoutingRule
from apps.identity.models import Organization, OrganizationMembership, Role, User
from apps.submission.models import Invoice, LineItem
from apps.submission.services import (
    create_invoice_from_extraction,
    structure_invoice,
)


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org_and_user(seeded) -> tuple[Organization, User]:
    org = Organization.objects.create(
        legal_name="ACME", tin="C10000000001", contact_email="ops@acme"
    )
    user = User.objects.create_user(email="o@acme.example", password="x")
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name="owner")
    )
    return org, user


@pytest.fixture
def field_structure_engine(db) -> Engine:
    engine, _ = Engine.objects.update_or_create(
        name="anthropic-claude-sonnet-structure",
        defaults={"vendor": "anthropic", "capability": "field_structure"},
    )
    EngineRoutingRule.objects.update_or_create(
        capability="field_structure",
        priority=100,
        engine=engine,
        defaults={"match_mime_types": "*", "is_active": True},
    )
    return engine


class _StructureAdapter(FieldStructureEngine):
    name = "anthropic-claude-sonnet-structure"

    def __init__(self, fields: dict[str, str], confidence: float = 0.85) -> None:
        self._fields = fields
        self._confidence = confidence

    def structure_fields(self, *, text, target_schema):
        return StructuredExtractResult(
            fields=self._fields,
            per_field_confidence={k: self._confidence for k in self._fields},
            overall_confidence=self._confidence,
            cost_micros=4000,
            diagnostics={},
        )


class _BrokenAdapter(FieldStructureEngine):
    name = "anthropic-claude-sonnet-structure"

    def structure_fields(self, *, text, target_schema):
        raise EngineUnavailable("ANTHROPIC_API_KEY is not set")


@pytest.mark.django_db
class TestStructuring:
    def test_create_invoice_is_idempotent(self, org_and_user) -> None:
        org, _ = org_and_user
        from uuid import uuid4

        job_id = uuid4()
        a = create_invoice_from_extraction(
            organization_id=org.id, ingestion_job_id=job_id, extracted_text="hi"
        )
        b = create_invoice_from_extraction(
            organization_id=org.id, ingestion_job_id=job_id, extracted_text="hi again"
        )
        assert a.id == b.id

    def test_structure_populates_header_and_line_items(
        self, org_and_user, field_structure_engine
    ) -> None:
        org, _ = org_and_user
        from uuid import uuid4

        invoice = create_invoice_from_extraction(
            organization_id=org.id,
            ingestion_job_id=uuid4(),
            extracted_text="Invoice INV-001 ACME RM 100",
        )
        structured_fields = {
            "invoice_number": "INV-001",
            "issue_date": "2026-04-15",
            "currency_code": "MYR",
            "supplier_legal_name": "ACME Sdn Bhd",
            "supplier_tin": "C20880050010",
            "subtotal": "100.00",
            "total_tax": "6.00",
            "grand_total": "106.00",
            "line_items": json.dumps(
                [
                    {
                        "description": "Widget",
                        "quantity": "2",
                        "unit_price_excl_tax": "50.00",
                        "line_subtotal_excl_tax": "100.00",
                        "tax_rate": "6",
                        "tax_amount": "6.00",
                        "line_total_incl_tax": "106.00",
                    }
                ]
            ),
        }
        with patch(
            "apps.extraction.registry.get_adapter",
            return_value=_StructureAdapter(structured_fields, confidence=0.85),
        ):
            result = structure_invoice(invoice.id)

        assert result.line_count == 1
        # Slice 29 added Ollama at priority 50 as the launch primary for
        # field structuring; Anthropic remains at priority 100 as fallback.
        assert result.engine == "ollama-structure"

        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.READY_FOR_REVIEW
        assert invoice.invoice_number == "INV-001"
        assert invoice.supplier_legal_name == "ACME Sdn Bhd"
        assert str(invoice.grand_total) == "106.00"
        assert invoice.overall_confidence == 0.85

        line = LineItem.objects.get(invoice=invoice, line_number=1)
        assert line.description == "Widget"
        assert str(line.quantity) == "2.0000"
        assert str(line.line_total_incl_tax) == "106.00"

        # Audit chain has the invoice.created + invoice.structured events.
        actions = list(
            AuditEvent.objects.order_by("sequence").values_list("action_type", flat=True)
        )
        assert "invoice.created" in actions
        assert "invoice.structured" in actions

    def test_structure_degrades_gracefully_when_engine_unavailable(
        self, org_and_user, field_structure_engine
    ) -> None:
        org, _ = org_and_user
        from uuid import uuid4

        invoice = create_invoice_from_extraction(
            organization_id=org.id, ingestion_job_id=uuid4(), extracted_text="bla"
        )
        with patch("apps.extraction.registry.get_adapter", return_value=_BrokenAdapter()):
            result = structure_invoice(invoice.id)

        assert result.engine == ""
        assert result.line_count == 0

        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.READY_FOR_REVIEW
        assert "Auto-structuring skipped" in invoice.error_message
        # An EngineCall row exists with UNAVAILABLE outcome.
        assert EngineCall.objects.filter(outcome=EngineCall.Outcome.UNAVAILABLE).count() == 1
        # Audit recorded the skip.
        assert AuditEvent.objects.filter(action_type="invoice.structuring_skipped").count() == 1

    def test_decimal_parsing_strips_currency_symbols(
        self, org_and_user, field_structure_engine
    ) -> None:
        org, _ = org_and_user
        from uuid import uuid4

        invoice = create_invoice_from_extraction(
            organization_id=org.id, ingestion_job_id=uuid4(), extracted_text="x"
        )
        adapter = _StructureAdapter({"grand_total": "RM 1,234.56", "subtotal": "MYR 1,165.00"})
        with patch("apps.extraction.registry.get_adapter", return_value=adapter):
            structure_invoice(invoice.id)

        invoice.refresh_from_db()
        assert str(invoice.grand_total) == "1234.56"
        assert str(invoice.subtotal) == "1165.00"

    def test_garbled_line_items_json_does_not_break_invoice(
        self, org_and_user, field_structure_engine
    ) -> None:
        org, _ = org_and_user
        from uuid import uuid4

        invoice = create_invoice_from_extraction(
            organization_id=org.id, ingestion_job_id=uuid4(), extracted_text="x"
        )
        adapter = _StructureAdapter({"invoice_number": "INV-9", "line_items": "not json at all"})
        with patch("apps.extraction.registry.get_adapter", return_value=adapter):
            structure_invoice(invoice.id)

        invoice.refresh_from_db()
        assert invoice.invoice_number == "INV-9"
        assert LineItem.objects.filter(invoice=invoice).count() == 0
