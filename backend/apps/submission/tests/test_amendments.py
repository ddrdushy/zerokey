"""Tests for invoice amendments — Credit Notes (Slice 61)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.identity.models import (
    Organization,
    OrganizationMembership,
    Role,
    User,
)
from apps.submission import amendments
from apps.submission.models import Invoice, LineItem


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org_user(seeded) -> tuple[Organization, User]:
    org = Organization.objects.create(
        legal_name="Acme",
        tin="C1234567890",
        contact_email="o@a",
    )
    user = User.objects.create_user(
        email="o@a", password="long-enough-password"
    )
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name="owner")
    )
    return org, user


@pytest.fixture
def validated_invoice(org_user) -> Invoice:
    org, _ = org_user
    inv = Invoice.objects.create(
        organization=org,
        ingestion_job_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        invoice_number="INV-001",
        issue_date=date(2026, 4, 1),
        currency_code="MYR",
        supplier_legal_name="Acme",
        supplier_tin="C1234567890",
        supplier_id_type="BRN",
        supplier_id_value="201901012345",
        buyer_legal_name="Globex",
        buyer_tin="C9876543210",
        buyer_id_type="BRN",
        buyer_id_value="199201003468",
        subtotal=Decimal("100.00"),
        total_tax=Decimal("8.00"),
        grand_total=Decimal("108.00"),
        status=Invoice.Status.VALIDATED,
        lhdn_uuid="LHDN-UUID-XYZ-001",
    )
    LineItem.objects.create(
        organization=org,
        invoice=inv,
        line_number=1,
        description="Service A",
        quantity=Decimal("10"),
        unit_price_excl_tax=Decimal("10.00"),
        line_subtotal_excl_tax=Decimal("100.00"),
        tax_type_code="01",
        tax_rate=Decimal("8.00"),
        tax_amount=Decimal("8.00"),
        line_total_incl_tax=Decimal("108.00"),
    )
    return inv


@pytest.mark.django_db
class TestCreateCreditNote:
    def test_full_credit_copies_invoice(
        self, org_user, validated_invoice
    ) -> None:
        _, user = org_user
        cn = amendments.create_credit_note(
            source_invoice_id=validated_invoice.id,
            reason="Customer returned all items",
            actor_user_id=user.id,
        )
        assert cn.invoice_type == Invoice.InvoiceType.CREDIT_NOTE
        assert cn.original_invoice_uuid == "LHDN-UUID-XYZ-001"
        assert cn.original_invoice_internal_id == "INV-001"
        assert cn.adjustment_reason == "Customer returned all items"
        assert cn.subtotal == Decimal("100.00")
        assert cn.grand_total == Decimal("108.00")
        # Buyer + supplier identities propagated.
        assert cn.supplier_id_type == "BRN"
        assert cn.buyer_id_type == "BRN"
        # CN starts ready for review (not auto-submitted).
        assert cn.status == Invoice.Status.READY_FOR_REVIEW

    def test_credit_note_number_pattern(
        self, org_user, validated_invoice
    ) -> None:
        _, user = org_user
        cn = amendments.create_credit_note(
            source_invoice_id=validated_invoice.id,
            reason="r",
            actor_user_id=user.id,
        )
        assert cn.invoice_number == "INV-001-CN-01"

    def test_multiple_credit_notes_increment(
        self, org_user, validated_invoice
    ) -> None:
        _, user = org_user
        cn1 = amendments.create_credit_note(
            source_invoice_id=validated_invoice.id,
            reason="first",
            actor_user_id=user.id,
        )
        cn2 = amendments.create_credit_note(
            source_invoice_id=validated_invoice.id,
            reason="second",
            actor_user_id=user.id,
        )
        assert cn1.invoice_number == "INV-001-CN-01"
        assert cn2.invoice_number == "INV-001-CN-02"

    def test_lines_copied_with_amounts(
        self, org_user, validated_invoice
    ) -> None:
        _, user = org_user
        cn = amendments.create_credit_note(
            source_invoice_id=validated_invoice.id,
            reason="r",
            actor_user_id=user.id,
        )
        cn_lines = list(cn.line_items.all())
        assert len(cn_lines) == 1
        assert cn_lines[0].line_subtotal_excl_tax == Decimal("100.00")

    def test_partial_credit_via_adjustments(
        self, org_user, validated_invoice
    ) -> None:
        _, user = org_user
        cn = amendments.create_credit_note(
            source_invoice_id=validated_invoice.id,
            reason="partial refund of 30%",
            actor_user_id=user.id,
            line_adjustments=[
                {"line_number": 1, "amount": "30.00"},
            ],
        )
        cn_lines = list(cn.line_items.all())
        assert len(cn_lines) == 1
        assert cn_lines[0].line_subtotal_excl_tax == Decimal("30.00")
        # Tax recomputed at 8%: 30 * 0.08 = 2.40
        assert cn_lines[0].tax_amount == Decimal("2.40")
        # Totals on the CN match the new amounts.
        cn.refresh_from_db()
        assert cn.subtotal == Decimal("30.00")
        assert cn.total_tax == Decimal("2.40")
        assert cn.grand_total == Decimal("32.40")

    def test_refuse_unvalidated_source(self, org_user) -> None:
        org, user = org_user
        # Source still in READY_FOR_REVIEW — has no LHDN UUID yet.
        unsaved = Invoice.objects.create(
            organization=org,
            ingestion_job_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            invoice_number="DRAFT-001",
            status=Invoice.Status.READY_FOR_REVIEW,
        )
        with pytest.raises(amendments.AmendmentError, match="Validated"):
            amendments.create_credit_note(
                source_invoice_id=unsaved.id,
                reason="r",
                actor_user_id=user.id,
            )

    def test_refuse_blank_reason(self, org_user, validated_invoice) -> None:
        _, user = org_user
        with pytest.raises(amendments.AmendmentError, match="reason"):
            amendments.create_credit_note(
                source_invoice_id=validated_invoice.id,
                reason="   ",
                actor_user_id=user.id,
            )

    def test_audit_event_recorded(
        self, org_user, validated_invoice
    ) -> None:
        from apps.audit.models import AuditEvent

        _, user = org_user
        cn = amendments.create_credit_note(
            source_invoice_id=validated_invoice.id,
            reason="returned defective product",
            actor_user_id=user.id,
        )
        event = (
            AuditEvent.objects.filter(
                action_type="submission.amendment.credit_note_created"
            )
            .order_by("-sequence")
            .first()
        )
        assert event is not None
        assert event.affected_entity_id == str(cn.id)
        assert event.payload["source_lhdn_uuid"] == "LHDN-UUID-XYZ-001"
        assert event.payload["credit_note_number"] == "INV-001-CN-01"


@pytest.mark.django_db
class TestCreditNoteEndpoint:
    def test_unauthenticated_403(self, validated_invoice) -> None:
        from django.test import Client
        import json

        response = Client().post(
            f"/api/v1/invoices/{validated_invoice.id}/issue-credit-note/",
            data=json.dumps({"reason": "x"}),
            content_type="application/json",
        )
        assert response.status_code in (401, 403)

    def test_happy_path(self, org_user, validated_invoice) -> None:
        from django.test import Client
        import json

        org, user = org_user
        client = Client()
        client.force_login(user)
        session = client.session
        session["organization_id"] = str(org.id)
        session.save()
        response = client.post(
            f"/api/v1/invoices/{validated_invoice.id}/issue-credit-note/",
            data=json.dumps(
                {"reason": "customer returned 1 unit"}
            ),
            content_type="application/json",
        )
        assert response.status_code == 201
        body = response.json()
        assert body["credit_note_number"] == "INV-001-CN-01"
        assert body["invoice"]["invoice_type"] == "credit_note"
        assert body["invoice"]["original_invoice_uuid"] == "LHDN-UUID-XYZ-001"
