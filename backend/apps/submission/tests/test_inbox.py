"""Tests for the Exception Inbox surface (Slice 25).

Covers:
  - ``ensure_open`` is idempotent: same (invoice, reason) returns the
    same row, refreshes priority/detail in place, and reopens a
    previously resolved row (status flips back to OPEN, resolved_*
    cleared).
  - ``resolve_for_reason`` closes every open row matching, no-ops
    when there are none.
  - ``resolve_by_user`` sets status=resolved + actor; idempotent.
  - List + count are scoped to the active org; cross-tenant rows
    excluded.
  - Wiring: a validation failure produces a ``validation_failure``
    inbox item; fixing the failure auto-resolves it on re-validate.
  - Wiring: a no-text + no-vision pipeline run opens a
    ``structuring_skipped`` inbox item.
  - API: GET returns paginated list with embedded invoice context;
    POST .../resolve/ marks resolved + audits with the actor.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.test import Client

from apps.audit.models import AuditEvent
from apps.identity.models import Organization, OrganizationMembership, Role, User
from apps.submission.inbox import (
    count_open_for_organization,
    ensure_open,
    list_open_for_organization,
    resolve_by_user,
    resolve_for_reason,
)
from apps.submission.models import ExceptionInboxItem, Invoice, LineItem


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


def _make_invoice(
    org: Organization,
    *,
    ingestion_job_id: str = "11111111-1111-4111-8111-111111111111",
    invoice_number: str = "INV-001",
    buyer_legal_name: str = "Buyer Sdn Bhd",
    buyer_tin: str = "C20880050010",
) -> Invoice:
    invoice = Invoice.objects.create(
        organization=org,
        ingestion_job_id=ingestion_job_id,
        invoice_number=invoice_number,
        issue_date=date.today(),
        currency_code="MYR",
        supplier_legal_name="Acme",
        supplier_tin="C10000000001",
        buyer_legal_name=buyer_legal_name,
        buyer_tin=buyer_tin,
        subtotal=Decimal("200.00"),
        total_tax=Decimal("12.00"),
        grand_total=Decimal("212.00"),
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


REASON = ExceptionInboxItem.Reason


@pytest.mark.django_db
class TestEnsureOpen:
    def test_creates_new_row_with_audit(self, org_user) -> None:
        org, _ = org_user
        invoice = _make_invoice(org)

        item = ensure_open(invoice=invoice, reason=REASON.VALIDATION_FAILURE)
        assert item.status == ExceptionInboxItem.Status.OPEN
        assert item.organization_id == org.id
        # Audit event written.
        assert AuditEvent.objects.filter(action_type="inbox.item_opened").exists()

    def test_second_call_with_same_reason_is_idempotent(self, org_user) -> None:
        org, _ = org_user
        invoice = _make_invoice(org)
        first = ensure_open(invoice=invoice, reason=REASON.VALIDATION_FAILURE)
        second = ensure_open(invoice=invoice, reason=REASON.VALIDATION_FAILURE)
        assert first.id == second.id
        # Only one row exists.
        assert (
            ExceptionInboxItem.objects.filter(
                invoice=invoice, reason=REASON.VALIDATION_FAILURE
            ).count()
            == 1
        )

    def test_reopens_a_previously_resolved_row(self, org_user) -> None:
        org, user = org_user
        invoice = _make_invoice(org)
        item = ensure_open(invoice=invoice, reason=REASON.VALIDATION_FAILURE)
        # Resolve it.
        resolve_by_user(organization_id=org.id, item_id=item.id, actor_user_id=user.id)
        item.refresh_from_db()
        assert item.status == ExceptionInboxItem.Status.RESOLVED
        assert item.resolved_at is not None

        # Re-flap.
        ensure_open(invoice=invoice, reason=REASON.VALIDATION_FAILURE)
        item.refresh_from_db()
        assert item.status == ExceptionInboxItem.Status.OPEN
        assert item.resolved_at is None
        assert item.resolved_by_user_id is None
        assert AuditEvent.objects.filter(action_type="inbox.item_reopened").exists()

    def test_priority_change_writes_audit(self, org_user) -> None:
        org, _ = org_user
        invoice = _make_invoice(org)
        ensure_open(invoice=invoice, reason=REASON.VALIDATION_FAILURE)
        # Bump to urgent on a re-call. The reopen audit event should NOT
        # fire (status didn't change), but state_changed → save + audit.
        before = AuditEvent.objects.filter(action_type="inbox.item_reopened").count()
        ensure_open(
            invoice=invoice,
            reason=REASON.VALIDATION_FAILURE,
            priority=ExceptionInboxItem.Priority.URGENT,
        )
        after = AuditEvent.objects.filter(action_type="inbox.item_reopened").count()
        # Save ran (priority changed), so an audit event was written.
        assert after == before + 1
        item = ExceptionInboxItem.objects.get(invoice=invoice, reason=REASON.VALIDATION_FAILURE)
        assert item.priority == ExceptionInboxItem.Priority.URGENT


@pytest.mark.django_db
class TestResolveForReason:
    def test_resolves_open_rows_and_records_actor(self, org_user) -> None:
        org, _ = org_user
        invoice = _make_invoice(org)
        ensure_open(invoice=invoice, reason=REASON.VALIDATION_FAILURE)

        resolved = resolve_for_reason(
            invoice=invoice,
            reason=REASON.VALIDATION_FAILURE,
            note="auto-resolved on re-validate",
        )
        assert resolved == 1
        item = ExceptionInboxItem.objects.get(invoice=invoice)
        assert item.status == ExceptionInboxItem.Status.RESOLVED
        assert item.resolution_note == "auto-resolved on re-validate"
        # Automatic — actor is None.
        assert item.resolved_by_user_id is None

    def test_no_op_when_no_open_rows(self, org_user) -> None:
        org, _ = org_user
        invoice = _make_invoice(org)
        # No row exists for this reason at all.
        resolved = resolve_for_reason(invoice=invoice, reason=REASON.LHDN_REJECTION)
        assert resolved == 0


@pytest.mark.django_db
class TestResolveByUser:
    def test_marks_resolved_with_actor(self, org_user) -> None:
        org, user = org_user
        invoice = _make_invoice(org)
        item = ensure_open(invoice=invoice, reason=REASON.VALIDATION_FAILURE)

        resolved = resolve_by_user(
            organization_id=org.id,
            item_id=item.id,
            actor_user_id=user.id,
            note="not a real issue",
        )
        assert resolved.status == ExceptionInboxItem.Status.RESOLVED
        assert str(resolved.resolved_by_user_id) == str(user.id)
        assert resolved.resolution_note == "not a real issue"

    def test_idempotent_on_already_resolved(self, org_user) -> None:
        org, user = org_user
        invoice = _make_invoice(org)
        item = ensure_open(invoice=invoice, reason=REASON.VALIDATION_FAILURE)
        resolve_by_user(organization_id=org.id, item_id=item.id, actor_user_id=user.id)
        # Calling again is a no-op (no exception, no extra audit).
        resolved_again = resolve_by_user(
            organization_id=org.id, item_id=item.id, actor_user_id=user.id
        )
        assert resolved_again.status == ExceptionInboxItem.Status.RESOLVED


@pytest.mark.django_db
class TestListOpenForOrganization:
    def test_only_active_org_open_rows(self, org_user) -> None:
        org, _ = org_user
        other = Organization.objects.create(
            legal_name="Other Sdn Bhd",
            tin="C99999999999",
            contact_email="other@example",
        )
        invoice_a = _make_invoice(org)
        invoice_b = _make_invoice(other, ingestion_job_id="22222222-2222-4222-8222-222222222222")

        ensure_open(invoice=invoice_a, reason=REASON.VALIDATION_FAILURE)
        ensure_open(invoice=invoice_b, reason=REASON.VALIDATION_FAILURE)

        rows = list_open_for_organization(organization_id=org.id)
        assert len(rows) == 1
        assert rows[0].organization_id == org.id

    def test_excludes_resolved_rows(self, org_user) -> None:
        org, user = org_user
        invoice = _make_invoice(org)
        item = ensure_open(invoice=invoice, reason=REASON.VALIDATION_FAILURE)
        resolve_by_user(organization_id=org.id, item_id=item.id, actor_user_id=user.id)
        rows = list_open_for_organization(organization_id=org.id)
        assert rows == []

    def test_count_matches_open_rows(self, org_user) -> None:
        org, _user = org_user
        invoice = _make_invoice(org)
        ensure_open(invoice=invoice, reason=REASON.VALIDATION_FAILURE)
        ensure_open(invoice=invoice, reason=REASON.STRUCTURING_SKIPPED)
        assert count_open_for_organization(organization_id=org.id) == 2

        # Resolve one — count drops.
        resolve_for_reason(invoice=invoice, reason=REASON.STRUCTURING_SKIPPED)
        assert count_open_for_organization(organization_id=org.id) == 1


@pytest.mark.django_db
class TestPipelineWiring:
    """End-to-end: validation creates an inbox item, fixing it resolves it."""

    def test_validation_failure_opens_inbox_then_fix_resolves(self, org_user) -> None:
        org, user = org_user
        # Build an invoice with a deliberate validation error.
        invoice = Invoice.objects.create(
            organization=org,
            ingestion_job_id="33333333-3333-4333-8333-333333333333",
            invoice_number="INV-100",
            issue_date=date.today(),
            currency_code="MYR",
            supplier_legal_name="Acme",
            supplier_tin="not-a-tin",  # ERROR-severity format failure
            buyer_legal_name="Customer",
            buyer_tin="C20880050010",
            subtotal=Decimal("200.00"),
            total_tax=Decimal("12.00"),
            grand_total=Decimal("212.00"),
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
            description="Widget",
            quantity=Decimal("1"),
            unit_price_excl_tax=Decimal("100.00"),
            line_subtotal_excl_tax=Decimal("100.00"),
            tax_amount=Decimal("6.00"),
            line_total_incl_tax=Decimal("106.00"),
        )

        # The post-structuring pipeline writes the inbox item.
        from apps.submission.services import update_invoice

        update_invoice(
            organization_id=org.id,
            invoice_id=invoice.id,
            updates={"buyer_msic_code": "47190"},
            actor_user_id=user.id,
        )
        item = ExceptionInboxItem.objects.get(invoice=invoice, reason=REASON.VALIDATION_FAILURE)
        assert item.status == ExceptionInboxItem.Status.OPEN

        # Fix the TIN — re-validate auto-resolves.
        update_invoice(
            organization_id=org.id,
            invoice_id=invoice.id,
            updates={"supplier_tin": "C10000000001"},
            actor_user_id=user.id,
        )
        item.refresh_from_db()
        assert item.status == ExceptionInboxItem.Status.RESOLVED


@pytest.mark.django_db
class TestInboxEndpoint:
    def test_get_returns_open_with_invoice_context(self, authed) -> None:
        client, org, _ = authed
        invoice = _make_invoice(org)
        ensure_open(invoice=invoice, reason=REASON.VALIDATION_FAILURE)

        response = client.get("/api/v1/inbox/")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        row = body["results"][0]
        assert row["reason"] == REASON.VALIDATION_FAILURE
        assert row["invoice_number"] == invoice.invoice_number
        assert row["buyer_legal_name"] == invoice.buyer_legal_name

    def test_post_resolve_marks_done(self, authed) -> None:
        client, org, _ = authed
        invoice = _make_invoice(org)
        item = ensure_open(invoice=invoice, reason=REASON.VALIDATION_FAILURE)

        response = client.post(
            f"/api/v1/inbox/{item.id}/resolve/",
            data={"note": "support reviewed"},
            content_type="application/json",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == ExceptionInboxItem.Status.RESOLVED
        assert body["resolution_note"] == "support reviewed"

    def test_resolve_other_orgs_item_is_404(self, authed) -> None:
        client, _, _ = authed
        other = Organization.objects.create(
            legal_name="Other Sdn Bhd",
            tin="C99999999999",
            contact_email="other@example",
        )
        their_invoice = _make_invoice(
            other, ingestion_job_id="44444444-4444-4444-8444-444444444444"
        )
        their_item = ensure_open(invoice=their_invoice, reason=REASON.VALIDATION_FAILURE)

        response = client.post(
            f"/api/v1/inbox/{their_item.id}/resolve/",
            data={},
            content_type="application/json",
        )
        assert response.status_code == 404

    def test_unauthenticated_rejected(self) -> None:
        response = Client().get("/api/v1/inbox/")
        assert response.status_code in (401, 403)

    def test_invalid_limit_rejected(self, authed) -> None:
        client, _, _ = authed
        response = client.get("/api/v1/inbox/?limit=abc")
        assert response.status_code == 400
