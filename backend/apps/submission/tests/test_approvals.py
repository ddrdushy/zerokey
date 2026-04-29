"""Tests for the two-step approval workflow (Slice 87)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from django.test import Client

from apps.audit.models import AuditEvent
from apps.identity.models import (
    Organization,
    OrganizationMembership,
    Role,
    User,
)
from apps.submission import approvals
from apps.submission.models import ApprovalRequest, Invoice


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


def _make_org(seeded, **overrides) -> Organization:
    defaults = dict(
        legal_name="Acme",
        tin="C1234567890",
        contact_email="o@a.example",
    )
    defaults.update(overrides)
    return Organization.objects.create(**defaults)


def _make_user(email: str, org: Organization, role_name: str) -> User:
    user = User.objects.create_user(email=email, password="long-enough-password")
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name=role_name)
    )
    return user


def _make_invoice(org: Organization, **overrides) -> Invoice:
    import uuid

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
# invoice_requires_approval — policy semantics
# =============================================================================


@pytest.mark.django_db
class TestRequiresApprovalPredicate:
    def test_none_policy_never_requires(self, seeded) -> None:
        org = _make_org(seeded)  # default policy = none
        invoice = _make_invoice(org)
        assert approvals.invoice_requires_approval(invoice) is False

    def test_always_policy_requires(self, seeded) -> None:
        org = _make_org(seeded, approval_policy="always")
        invoice = _make_invoice(org)
        assert approvals.invoice_requires_approval(invoice) is True

    def test_threshold_policy_under_does_not_require(self, seeded) -> None:
        org = _make_org(
            seeded,
            approval_policy="threshold",
            approval_threshold_amount=Decimal("50000.00"),
        )
        invoice = _make_invoice(org, grand_total=Decimal("10000.00"))
        assert approvals.invoice_requires_approval(invoice) is False

    def test_threshold_policy_over_requires(self, seeded) -> None:
        org = _make_org(
            seeded,
            approval_policy="threshold",
            approval_threshold_amount=Decimal("50000.00"),
        )
        invoice = _make_invoice(org, grand_total=Decimal("75000.00"))
        assert approvals.invoice_requires_approval(invoice) is True

    def test_threshold_at_exactly_requires(self, seeded) -> None:
        # Threshold is inclusive — invoice == threshold means
        # approval is required (matches LHDN-style amount cutoff
        # convention).
        org = _make_org(
            seeded,
            approval_policy="threshold",
            approval_threshold_amount=Decimal("50000.00"),
        )
        invoice = _make_invoice(org, grand_total=Decimal("50000.00"))
        assert approvals.invoice_requires_approval(invoice) is True

    def test_threshold_misconfigured_fails_closed(self, seeded) -> None:
        # Threshold policy but no threshold value — fail closed
        # (require approval) instead of silently permitting.
        org = _make_org(seeded, approval_policy="threshold")
        invoice = _make_invoice(org)
        assert approvals.invoice_requires_approval(invoice) is True


# =============================================================================
# request_approval / approve / reject
# =============================================================================


@pytest.mark.django_db
class TestRequestApproval:
    def test_creates_pending_row_and_moves_invoice(self, seeded) -> None:
        org = _make_org(seeded, approval_policy="always")
        submitter = _make_user("sub@a.example", org, "submitter")
        invoice = _make_invoice(org)

        req = approvals.request_approval(
            invoice_id=invoice.id, actor_user_id=submitter.id, reason="month-end"
        )
        assert req.status == ApprovalRequest.Status.PENDING

        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.AWAITING_APPROVAL

        ev = AuditEvent.objects.filter(action_type="invoice.approval.requested").first()
        assert ev is not None
        assert ev.payload["approval_id"] == str(req.id)

    def test_idempotent_on_repeated_request(self, seeded) -> None:
        org = _make_org(seeded, approval_policy="always")
        submitter = _make_user("sub@a.example", org, "submitter")
        invoice = _make_invoice(org)

        first = approvals.request_approval(invoice_id=invoice.id, actor_user_id=submitter.id)
        second = approvals.request_approval(invoice_id=invoice.id, actor_user_id=submitter.id)
        assert first.id == second.id
        assert ApprovalRequest.objects.filter(invoice=invoice).count() == 1

    def test_rejected_already_invoice_state(self, seeded) -> None:
        # Calling request_approval after submission is forbidden.
        org = _make_org(seeded, approval_policy="always")
        submitter = _make_user("sub@a.example", org, "submitter")
        invoice = _make_invoice(org, status=Invoice.Status.SUBMITTING)
        with pytest.raises(approvals.ApprovalError, match="Cannot request"):
            approvals.request_approval(invoice_id=invoice.id, actor_user_id=submitter.id)


@pytest.mark.django_db
class TestApprove:
    def test_approver_approves_and_unblocks(self, seeded) -> None:
        org = _make_org(seeded, approval_policy="always")
        submitter = _make_user("sub@a.example", org, "submitter")
        approver = _make_user("appr@a.example", org, "approver")
        invoice = _make_invoice(org)

        req = approvals.request_approval(invoice_id=invoice.id, actor_user_id=submitter.id)
        decided = approvals.approve(approval_id=req.id, actor_user_id=approver.id, note="ok")
        assert decided.status == ApprovalRequest.Status.APPROVED
        assert str(decided.decided_by_user_id) == str(approver.id)

        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.READY_FOR_REVIEW

        # has_active_approval flips to True after a successful approval.
        assert approvals.has_active_approval(invoice) is True

    def test_admin_cannot_approve_own(self, seeded) -> None:
        # An admin who happens to have submitted the request can
        # technically approve (role allows) — but the four-eyes
        # principle blocks it. Plain submitters are blocked one
        # layer up, by the role check.
        org = _make_org(seeded, approval_policy="always")
        admin = _make_user("admin@a.example", org, "admin")
        invoice = _make_invoice(org)
        req = approvals.request_approval(invoice_id=invoice.id, actor_user_id=admin.id)
        with pytest.raises(approvals.ApprovalError, match="own request"):
            approvals.approve(approval_id=req.id, actor_user_id=admin.id)

    def test_viewer_cannot_approve(self, seeded) -> None:
        org = _make_org(seeded, approval_policy="always")
        submitter = _make_user("sub@a.example", org, "submitter")
        viewer = _make_user("v@a.example", org, "viewer")
        invoice = _make_invoice(org)
        req = approvals.request_approval(invoice_id=invoice.id, actor_user_id=submitter.id)
        with pytest.raises(approvals.ApprovalError, match="permission"):
            approvals.approve(approval_id=req.id, actor_user_id=viewer.id)

    def test_already_decided_cannot_re_approve(self, seeded) -> None:
        org = _make_org(seeded, approval_policy="always")
        submitter = _make_user("sub@a.example", org, "submitter")
        approver = _make_user("appr@a.example", org, "approver")
        invoice = _make_invoice(org)
        req = approvals.request_approval(invoice_id=invoice.id, actor_user_id=submitter.id)
        approvals.approve(approval_id=req.id, actor_user_id=approver.id)
        with pytest.raises(approvals.ApprovalError, match="already in state"):
            approvals.approve(approval_id=req.id, actor_user_id=approver.id)


@pytest.mark.django_db
class TestReject:
    def test_approver_rejects_and_invoice_returns(self, seeded) -> None:
        org = _make_org(seeded, approval_policy="always")
        submitter = _make_user("sub@a.example", org, "submitter")
        approver = _make_user("appr@a.example", org, "approver")
        invoice = _make_invoice(org)
        req = approvals.request_approval(invoice_id=invoice.id, actor_user_id=submitter.id)
        approvals.reject(approval_id=req.id, actor_user_id=approver.id, reason="missing PO")
        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.READY_FOR_REVIEW

        # has_active_approval is False after rejection — re-requesting
        # will create a fresh row.
        assert approvals.has_active_approval(invoice) is False

    def test_re_request_creates_fresh_row(self, seeded) -> None:
        org = _make_org(seeded, approval_policy="always")
        submitter = _make_user("sub@a.example", org, "submitter")
        approver = _make_user("appr@a.example", org, "approver")
        invoice = _make_invoice(org)

        first = approvals.request_approval(invoice_id=invoice.id, actor_user_id=submitter.id)
        approvals.reject(approval_id=first.id, actor_user_id=approver.id, reason="x")
        # Re-request after rejection — different row.
        second = approvals.request_approval(invoice_id=invoice.id, actor_user_id=submitter.id)
        assert second.id != first.id
        assert ApprovalRequest.objects.filter(invoice=invoice).count() == 2


# =============================================================================
# Submit gate — invoice with policy=always cannot submit without approval
# =============================================================================


@pytest.mark.django_db
class TestSubmitGate:
    def test_submit_blocked_without_approval(self, seeded) -> None:
        org = _make_org(seeded, approval_policy="always")
        owner = _make_user("o@a.example", org, "owner")
        invoice = _make_invoice(org)

        client = Client()
        client.force_login(owner)
        session = client.session
        session["organization_id"] = str(org.id)
        session.save()

        response = client.post(
            f"/api/v1/invoices/{invoice.id}/submit-to-lhdn/",
            content_type="application/json",
        )
        assert response.status_code == 400
        body = response.json()
        assert body.get("needs_approval") is True

    def test_submit_proceeds_after_approval(self, seeded) -> None:
        # End-to-end: request → approve → submit attempt no longer
        # blocked at the approval gate (it'll fail later for missing
        # LHDN creds, which is fine — the approval gate has cleared).
        org = _make_org(seeded, approval_policy="always")
        submitter = _make_user("sub@a.example", org, "submitter")
        approver = _make_user("appr@a.example", org, "approver")
        invoice = _make_invoice(org)

        req = approvals.request_approval(invoice_id=invoice.id, actor_user_id=submitter.id)
        approvals.approve(approval_id=req.id, actor_user_id=approver.id)

        client = Client()
        client.force_login(approver)  # approver may submit (admin/approver/submitter all may)
        session = client.session
        session["organization_id"] = str(org.id)
        session.save()

        response = client.post(
            f"/api/v1/invoices/{invoice.id}/submit-to-lhdn/",
            content_type="application/json",
        )
        # Past the approval gate. Body may now report a creds /
        # signing failure, but it must NOT be the approval-needed
        # response.
        body = response.json()
        assert not (response.status_code == 400 and body.get("needs_approval"))


# =============================================================================
# Endpoints
# =============================================================================


@pytest.mark.django_db
class TestEndpoints:
    def test_request_approval_endpoint(self, seeded) -> None:
        org = _make_org(seeded, approval_policy="always")
        submitter = _make_user("sub@a.example", org, "submitter")
        invoice = _make_invoice(org)

        client = Client()
        client.force_login(submitter)
        session = client.session
        session["organization_id"] = str(org.id)
        session.save()

        response = client.post(
            f"/api/v1/invoices/{invoice.id}/request-approval/",
            data=json.dumps({"reason": "month-end"}),
            content_type="application/json",
        )
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "pending"

    def test_pending_endpoint_lists_open(self, seeded) -> None:
        org = _make_org(seeded, approval_policy="always")
        submitter = _make_user("sub@a.example", org, "submitter")
        approver = _make_user("appr@a.example", org, "approver")
        invoice = _make_invoice(org)
        approvals.request_approval(invoice_id=invoice.id, actor_user_id=submitter.id)

        client = Client()
        client.force_login(approver)
        session = client.session
        session["organization_id"] = str(org.id)
        session.save()

        response = client.get("/api/v1/invoices/approvals/pending/")
        assert response.status_code == 200
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["invoice_id"] == str(invoice.id)
        assert results[0]["invoice_number"] == "INV-001"

    def test_approve_endpoint_decides(self, seeded) -> None:
        org = _make_org(seeded, approval_policy="always")
        submitter = _make_user("sub@a.example", org, "submitter")
        approver = _make_user("appr@a.example", org, "approver")
        invoice = _make_invoice(org)
        req = approvals.request_approval(invoice_id=invoice.id, actor_user_id=submitter.id)

        client = Client()
        client.force_login(approver)
        session = client.session
        session["organization_id"] = str(org.id)
        session.save()

        response = client.post(
            f"/api/v1/invoices/approvals/{req.id}/approve/",
            data=json.dumps({"note": "ok"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["status"] == "approved"

    def test_other_orgs_approval_is_404(self, seeded) -> None:
        # Cross-tenant access to an approval row must 404.
        org_a = _make_org(seeded, approval_policy="always")
        org_b = _make_org(seeded, legal_name="Other", tin="C99999999999", contact_email="o@b")
        sub_a = _make_user("a@a.example", org_a, "submitter")
        appr_b = _make_user("b@b.example", org_b, "approver")
        inv_a = _make_invoice(org_a)
        req = approvals.request_approval(invoice_id=inv_a.id, actor_user_id=sub_a.id)

        client = Client()
        client.force_login(appr_b)
        session = client.session
        session["organization_id"] = str(org_b.id)
        session.save()

        response = client.post(
            f"/api/v1/invoices/approvals/{req.id}/approve/",
            content_type="application/json",
        )
        assert response.status_code == 404
