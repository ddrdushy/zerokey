"""Tests for ``update_invoice`` and the PATCH /invoices/<id>/ endpoint.

Covers:
  - Editing a single field updates the row, bumps confidence to 1.0,
    and emits an ``invoice.updated`` audit event whose payload lists
    field names but never values (PII).
  - Editing multiple fields at once batches a single audit event.
  - Master propagation: a corrected ``buyer_msic_code`` overwrites the
    matched ``CustomerMaster.msic_code`` (corrections beat prior LLM
    extractions).
  - Renaming the buyer files the previous canonical name as an alias.
  - Re-validation runs after the update, so newly-valid invoices clear
    their issues and newly-broken invoices gain new ones.
  - Cross-tenant: PATCH with a different org's invoice id returns 404.
  - Editable-field allowlist: lhdn_uuid and friends can't be flipped.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.test import Client

from apps.audit.models import AuditEvent
from apps.enrichment.models import CustomerMaster
from apps.identity.models import Organization, OrganizationMembership, Role, User
from apps.submission.models import Invoice, LineItem
from apps.submission.services import (
    EDITABLE_HEADER_FIELDS,
    InvoiceUpdateError,
    update_invoice,
)
from apps.validation.models import ValidationIssue


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


def _make_invoice(
    org: Organization,
    *,
    ingestion_job_id: str = "11111111-1111-4111-8111-111111111111",
    buyer_tin: str = "C20880050010",
    buyer_legal_name: str = "Buyer Sdn Bhd",
    buyer_msic_code: str = "",
    grand_total: str = "212.00",
) -> Invoice:
    invoice = Invoice.objects.create(
        organization=org,
        ingestion_job_id=ingestion_job_id,
        invoice_number="INV-100",
        issue_date=date.today(),
        currency_code="MYR",
        supplier_legal_name="Acme",
        supplier_tin="C10000000001",
        buyer_legal_name=buyer_legal_name,
        buyer_tin=buyer_tin,
        buyer_msic_code=buyer_msic_code,
        subtotal=Decimal("200.00"),
        total_tax=Decimal("12.00"),
        grand_total=Decimal(grand_total),
    )
    LineItem.objects.create(
        organization=org,
        invoice=invoice,
        line_number=1,
        description="Widget",
        quantity=Decimal("1"),
        unit_price_excl_tax=Decimal("100.00"),
        line_subtotal_excl_tax=Decimal("100.00"),
        tax_amount=Decimal("6.00"),
        line_total_incl_tax=Decimal("106.00"),
    )
    LineItem.objects.create(
        organization=org,
        invoice=invoice,
        line_number=2,
        description="Widget 2",
        quantity=Decimal("1"),
        unit_price_excl_tax=Decimal("100.00"),
        line_subtotal_excl_tax=Decimal("100.00"),
        tax_amount=Decimal("6.00"),
        line_total_incl_tax=Decimal("106.00"),
    )
    return invoice


@pytest.mark.django_db
class TestUpdateService:
    def test_single_field_update_persists_and_marks_confidence(self, org_user) -> None:
        org, user = org_user
        invoice = _make_invoice(org)

        result = update_invoice(
            organization_id=org.id,
            invoice_id=invoice.id,
            updates={"buyer_msic_code": "62010"},
            actor_user_id=user.id,
        )

        assert result.changed_fields == ["buyer_msic_code"]
        invoice.refresh_from_db()
        assert invoice.buyer_msic_code == "62010"
        assert invoice.per_field_confidence.get("buyer_msic_code") == 1.0

    def test_multi_field_update_emits_one_audit_event(self, org_user) -> None:
        org, user = org_user
        invoice = _make_invoice(org)

        update_invoice(
            organization_id=org.id,
            invoice_id=invoice.id,
            updates={
                "buyer_msic_code": "62010",
                "buyer_phone": "03-1234-5678",
                "buyer_country_code": "MY",
            },
            actor_user_id=user.id,
        )

        events = list(AuditEvent.objects.filter(action_type="invoice.updated"))
        assert len(events) == 1
        payload = events[0].payload
        assert sorted(payload["changed_fields"]) == [
            "buyer_country_code",
            "buyer_msic_code",
            "buyer_phone",
        ]
        # No values — only field names.
        serialized = str(payload)
        assert "62010" not in serialized
        assert "03-1234-5678" not in serialized

    def test_no_changes_emits_no_audit_event(self, org_user) -> None:
        """Setting a field to its existing value is a no-op."""
        org, user = org_user
        invoice = _make_invoice(org, buyer_msic_code="62010")

        result = update_invoice(
            organization_id=org.id,
            invoice_id=invoice.id,
            updates={"buyer_msic_code": "62010"},
            actor_user_id=user.id,
        )

        assert result.changed_fields == []
        assert AuditEvent.objects.filter(action_type="invoice.updated").count() == 0

    def test_decimal_field_coerces_string_input(self, org_user) -> None:
        org, user = org_user
        invoice = _make_invoice(org)

        update_invoice(
            organization_id=org.id,
            invoice_id=invoice.id,
            updates={"grand_total": "RM 500.00"},
            actor_user_id=user.id,
        )

        invoice.refresh_from_db()
        assert invoice.grand_total == Decimal("500.00")

    def test_unknown_field_is_rejected(self, org_user) -> None:
        org, user = org_user
        invoice = _make_invoice(org)

        with pytest.raises(InvoiceUpdateError, match="non-editable"):
            update_invoice(
                organization_id=org.id,
                invoice_id=invoice.id,
                updates={"lhdn_uuid": "tampered-uuid"},
                actor_user_id=user.id,
            )

    def test_invalid_decimal_input_is_rejected(self, org_user) -> None:
        org, user = org_user
        invoice = _make_invoice(org)

        with pytest.raises(InvoiceUpdateError, match="decimal"):
            update_invoice(
                organization_id=org.id,
                invoice_id=invoice.id,
                updates={"grand_total": "not-a-number"},
                actor_user_id=user.id,
            )

    def test_correction_propagates_to_matched_master(self, org_user) -> None:
        org, user = org_user

        # Seed the master via the enrichment pipeline (fresh creation).
        invoice = _make_invoice(org)
        from apps.enrichment.services import enrich_invoice

        enrich_invoice(invoice.id)
        master = CustomerMaster.objects.get(organization=org)
        assert master.msic_code == ""  # the LLM didn't extract it on the first pass

        # User now corrects the MSIC code on the invoice.
        update_invoice(
            organization_id=org.id,
            invoice_id=invoice.id,
            updates={"buyer_msic_code": "62010"},
            actor_user_id=user.id,
        )

        master.refresh_from_db()
        assert master.msic_code == "62010"

    def test_correction_overwrites_wrong_master_value(self, org_user) -> None:
        """Master may already hold a wrong value from a prior LLM pass.

        The user's correction is stronger evidence than the master's
        prior LLM-fed value, so the master is overwritten — that's the
        whole point of the correction feedback loop.
        """
        org, user = org_user
        invoice = _make_invoice(org)

        # Seed the master with a wrong code (simulates a previous bad LLM extraction).
        from apps.enrichment.services import enrich_invoice

        enrich_invoice(invoice.id)
        master = CustomerMaster.objects.get(organization=org)
        master.msic_code = "99999"  # the wrong code
        master.save()

        update_invoice(
            organization_id=org.id,
            invoice_id=invoice.id,
            updates={"buyer_msic_code": "62010"},
            actor_user_id=user.id,
        )
        master.refresh_from_db()
        assert master.msic_code == "62010"

    def test_renaming_buyer_files_old_name_as_alias(self, org_user) -> None:
        org, user = org_user
        invoice = _make_invoice(org, buyer_legal_name="Old Name Sdn Bhd")
        from apps.enrichment.services import enrich_invoice

        enrich_invoice(invoice.id)

        update_invoice(
            organization_id=org.id,
            invoice_id=invoice.id,
            updates={"buyer_legal_name": "Corrected Name Sdn Bhd"},
            actor_user_id=user.id,
        )

        master = CustomerMaster.objects.get(organization=org)
        assert master.legal_name == "Corrected Name Sdn Bhd"
        assert "Old Name Sdn Bhd" in master.aliases

    def test_revalidation_clears_resolved_issues(self, org_user) -> None:
        """Editing a wrong TIN to the right format clears the format issue."""
        org, user = org_user
        invoice = _make_invoice(org, buyer_tin="not-a-tin")
        from apps.enrichment.services import enrich_invoice
        from apps.validation.services import validate_invoice

        enrich_invoice(invoice.id)
        validate_invoice(invoice.id)

        before = set(
            ValidationIssue.objects.filter(invoice_id=invoice.id).values_list(
                "code", flat=True
            )
        )
        assert "buyer.tin.format" in before

        update_invoice(
            organization_id=org.id,
            invoice_id=invoice.id,
            updates={"buyer_tin": "C30000000001"},
            actor_user_id=user.id,
        )

        after = set(
            ValidationIssue.objects.filter(invoice_id=invoice.id).values_list(
                "code", flat=True
            )
        )
        assert "buyer.tin.format" not in after

    def test_revalidation_surfaces_newly_broken_invariants(self, org_user) -> None:
        """Editing the grand total to mismatch breaks the arithmetic rule."""
        org, user = org_user
        invoice = _make_invoice(org)
        from apps.enrichment.services import enrich_invoice
        from apps.validation.services import validate_invoice

        enrich_invoice(invoice.id)
        validate_invoice(invoice.id)

        # Baseline is clean for arithmetic.
        codes_before = set(
            ValidationIssue.objects.filter(invoice_id=invoice.id).values_list(
                "code", flat=True
            )
        )
        assert "totals.grand_total.mismatch" not in codes_before

        update_invoice(
            organization_id=org.id,
            invoice_id=invoice.id,
            updates={"grand_total": "999.99"},
            actor_user_id=user.id,
        )

        codes_after = set(
            ValidationIssue.objects.filter(invoice_id=invoice.id).values_list(
                "code", flat=True
            )
        )
        assert "totals.grand_total.mismatch" in codes_after


@pytest.mark.django_db
class TestUpdateEndpoint:
    @pytest.fixture
    def authed(self, org_user) -> tuple[Client, str, Invoice]:
        org, user = org_user
        client = Client()
        client.force_login(user)
        # Force the active org into the session — the standard auth-via-API
        # path does this on register/login but force_login bypasses that.
        session = client.session
        session["organization_id"] = str(org.id)
        session.save()
        invoice = _make_invoice(org)
        return client, str(org.id), invoice

    def test_patch_updates_field_and_returns_validation(self, authed) -> None:
        client, _, invoice = authed

        response = client.patch(
            f"/api/v1/invoices/{invoice.id}/",
            data={"buyer_msic_code": "62010"},
            content_type="application/json",
        )
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["buyer_msic_code"] == "62010"
        assert "validation_summary" in body
        assert "validation_issues" in body

    def test_patch_unknown_field_is_400(self, authed) -> None:
        client, _, invoice = authed
        response = client.patch(
            f"/api/v1/invoices/{invoice.id}/",
            data={"lhdn_uuid": "tampered"},
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "non-editable" in response.json()["detail"]

    def test_patch_unauthenticated_is_rejected(self) -> None:
        response = Client().patch(
            "/api/v1/invoices/00000000-0000-0000-0000-000000000000/",
            data={"buyer_msic_code": "62010"},
            content_type="application/json",
        )
        assert response.status_code in (401, 403)

    def test_patch_other_orgs_invoice_is_404(self, org_user) -> None:
        """Cross-tenant write attempt: lookup is scoped to the active org."""
        org, user = org_user
        other = Organization.objects.create(
            legal_name="Other Sdn Bhd",
            tin="C99999999999",
            contact_email="other@example",
        )
        their_invoice = _make_invoice(
            other, ingestion_job_id="22222222-2222-4222-8222-222222222222"
        )

        client = Client()
        client.force_login(user)
        session = client.session
        session["organization_id"] = str(org.id)
        session.save()

        response = client.patch(
            f"/api/v1/invoices/{their_invoice.id}/",
            data={"buyer_msic_code": "62010"},
            content_type="application/json",
        )
        assert response.status_code == 404


@pytest.mark.django_db
class TestEditableFieldAllowlist:
    def test_allowlist_excludes_submission_lifecycle_fields(self) -> None:
        """The PATCH endpoint must not let a user flip lhdn_uuid, status, etc."""
        forbidden = {
            "lhdn_uuid",
            "lhdn_qr_code_url",
            "signed_xml_s3_key",
            "validation_timestamp",
            "cancellation_timestamp",
            "status",
            "structuring_engine",
            "raw_extracted_text",
        }
        assert forbidden.isdisjoint(EDITABLE_HEADER_FIELDS)


@pytest.mark.django_db
class TestLineItemUpdates:
    """Line items can be edited via the same PATCH endpoint.

    Each line is addressed by ``line_number`` (stable within an invoice),
    not by database id. Line-item edits go through the same allowlist
    contract (EDITABLE_LINE_FIELDS), trigger the same revalidation pass,
    and propagate corrections to the matched ItemMaster the same way
    buyer corrections propagate to the CustomerMaster.
    """

    def test_edit_line_description_persists(self, org_user) -> None:
        org, user = org_user
        invoice = _make_invoice(org)

        update_invoice(
            organization_id=org.id,
            invoice_id=invoice.id,
            updates={
                "line_items": [
                    {"line_number": 1, "description": "Corrected widget"},
                ],
            },
            actor_user_id=user.id,
        )

        line = invoice.line_items.get(line_number=1)
        assert line.description == "Corrected widget"
        assert line.per_field_confidence.get("description") == 1.0

    def test_edit_line_decimal_field_coerces(self, org_user) -> None:
        org, user = org_user
        invoice = _make_invoice(org)

        update_invoice(
            organization_id=org.id,
            invoice_id=invoice.id,
            updates={
                "line_items": [
                    {"line_number": 1, "unit_price_excl_tax": "RM 250.50"},
                ],
            },
            actor_user_id=user.id,
        )
        line = invoice.line_items.get(line_number=1)
        assert line.unit_price_excl_tax == Decimal("250.50")

    def test_audit_event_summarizes_line_changes_without_values(self, org_user) -> None:
        org, user = org_user
        invoice = _make_invoice(org)

        update_invoice(
            organization_id=org.id,
            invoice_id=invoice.id,
            updates={
                "line_items": [
                    {
                        "line_number": 1,
                        "description": "New description with PII potential",
                        "classification_code": "011",
                    },
                    {"line_number": 2, "tax_type_code": "01"},
                ],
            },
            actor_user_id=user.id,
        )

        event = AuditEvent.objects.filter(action_type="invoice.updated").get()
        line_summaries = event.payload["changed_line_items"]
        # Two lines edited, recorded by line_number not db id.
        line_numbers = {entry["line_number"] for entry in line_summaries}
        assert line_numbers == {1, 2}
        # Field NAMES present, values absent.
        serialized = str(event.payload)
        assert "description" in serialized
        assert "PII potential" not in serialized
        assert "011" not in serialized

    def test_unknown_line_number_is_rejected(self, org_user) -> None:
        org, user = org_user
        invoice = _make_invoice(org)

        with pytest.raises(InvoiceUpdateError, match="line_items\\[99\\]"):
            update_invoice(
                organization_id=org.id,
                invoice_id=invoice.id,
                updates={
                    "line_items": [
                        {"line_number": 99, "description": "Phantom line"},
                    ],
                },
                actor_user_id=user.id,
            )

    def test_non_editable_line_field_rejected(self, org_user) -> None:
        org, user = org_user
        invoice = _make_invoice(org)

        with pytest.raises(InvoiceUpdateError, match="non-editable line fields"):
            update_invoice(
                organization_id=org.id,
                invoice_id=invoice.id,
                updates={
                    "line_items": [
                        {"line_number": 1, "id": "spoofed-uuid"},
                    ],
                },
                actor_user_id=user.id,
            )

    def test_malformed_line_payload_rejected(self, org_user) -> None:
        org, user = org_user
        invoice = _make_invoice(org)

        with pytest.raises(InvoiceUpdateError, match="must be an array"):
            update_invoice(
                organization_id=org.id,
                invoice_id=invoice.id,
                updates={"line_items": {"not": "a list"}},
                actor_user_id=user.id,
            )

        with pytest.raises(InvoiceUpdateError, match="line_number"):
            update_invoice(
                organization_id=org.id,
                invoice_id=invoice.id,
                updates={"line_items": [{"description": "no line number"}]},
                actor_user_id=user.id,
            )

    def test_correction_propagates_to_item_master(self, org_user) -> None:
        """A user correction of a line code overwrites the matched master default."""
        org, user = org_user
        invoice = _make_invoice(org)

        # Seed master state via the enrichment pipeline (creates ItemMaster
        # for "Widget" / "Widget 2" with empty defaults).
        from apps.enrichment.models import ItemMaster
        from apps.enrichment.services import enrich_invoice

        enrich_invoice(invoice.id)
        master = ItemMaster.objects.get(
            organization=org, canonical_name="Widget"
        )
        # Imagine the master picked up a wrong code from a previous LLM pass.
        master.default_classification_code = "999"
        master.save()

        update_invoice(
            organization_id=org.id,
            invoice_id=invoice.id,
            updates={
                "line_items": [
                    {"line_number": 1, "classification_code": "011"},
                ],
            },
            actor_user_id=user.id,
        )
        master.refresh_from_db()
        assert master.default_classification_code == "011"

    def test_combined_header_and_line_update_emits_one_audit_event(self, org_user) -> None:
        org, user = org_user
        invoice = _make_invoice(org)

        update_invoice(
            organization_id=org.id,
            invoice_id=invoice.id,
            updates={
                "buyer_msic_code": "62010",
                "line_items": [
                    {"line_number": 1, "classification_code": "011"},
                ],
            },
            actor_user_id=user.id,
        )

        events = list(AuditEvent.objects.filter(action_type="invoice.updated"))
        assert len(events) == 1
        payload = events[0].payload
        assert payload["changed_fields"] == ["buyer_msic_code"]
        assert len(payload["changed_line_items"]) == 1
        assert payload["changed_line_items"][0]["line_number"] == 1

    def test_no_changes_returns_empty_summary(self, org_user) -> None:
        """Submitting current values for both header + lines is a no-op."""
        org, user = org_user
        invoice = _make_invoice(org)

        result = update_invoice(
            organization_id=org.id,
            invoice_id=invoice.id,
            updates={
                "buyer_msic_code": invoice.buyer_msic_code,
                "line_items": [
                    {
                        "line_number": 1,
                        "description": invoice.line_items.get(line_number=1).description,
                    },
                ],
            },
            actor_user_id=user.id,
        )
        assert result.changed_fields == []
        assert result.changed_line_items == []
        assert AuditEvent.objects.filter(action_type="invoice.updated").count() == 0
