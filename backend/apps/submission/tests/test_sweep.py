"""Tests for the inflight-poll sweep (Slice 69).

The per-invoice poll chain in ``poll_invoice_status`` covers the
happy path. The sweep is the safety net for invoices the chain
missed (worker restart, retry budget exhausted, or LHDN slower
than the spec window).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.identity.models import Organization, Role
from apps.submission.models import Invoice
from apps.submission.tasks import (
    SWEEP_MAX_PER_RUN,
    SWEEP_STALE_AFTER_SECONDS,
    sweep_inflight_polls,
)


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org(seeded) -> Organization:
    return Organization.objects.create(
        legal_name="Sweep Co Sdn Bhd",
        tin="C1234567890",
        contact_email="sweep@example.com",
    )


def _make_invoice(
    *,
    org: Organization,
    status: str = Invoice.Status.SUBMITTING,
    submission_uid: str = "sub-stale-1",
    age_seconds: int = 600,
) -> Invoice:
    """Create an invoice + force its updated_at into the past."""
    inv = Invoice.objects.create(
        organization=org,
        ingestion_job_id=uuid.uuid4(),
        invoice_number=f"INV-{uuid.uuid4().hex[:8]}",
        issue_date=date(2026, 4, 15),
        due_date=date(2026, 5, 15),
        currency_code="MYR",
        supplier_legal_name=org.legal_name,
        supplier_tin=org.tin,
        buyer_legal_name="Buyer",
        buyer_tin="C9999999999",
        subtotal=Decimal("100.00"),
        total_tax=Decimal("8.00"),
        grand_total=Decimal("108.00"),
        status=status,
        submission_uid=submission_uid,
    )
    # Force the timestamp into the past — Django auto_now overwrites
    # on save, so we use a raw UPDATE.
    Invoice.objects.filter(pk=inv.pk).update(
        updated_at=timezone.now() - timedelta(seconds=age_seconds)
    )
    inv.refresh_from_db()
    return inv


@pytest.mark.django_db
class TestSweepInflightPolls:
    def test_requeues_stale_submitting(self, org) -> None:
        invoice = _make_invoice(
            org=org, age_seconds=SWEEP_STALE_AFTER_SECONDS + 60
        )
        with patch(
            "apps.submission.tasks.poll_invoice_status.delay"
        ) as mock_delay:
            result = sweep_inflight_polls()
        assert result["requeued"] == 1
        mock_delay.assert_called_once_with(str(invoice.id))

    def test_skips_fresh_submitting(self, org) -> None:
        # Updated 10 seconds ago — well inside the per-invoice
        # poll's window. Sweep mustn't double-queue.
        _make_invoice(org=org, age_seconds=10)
        with patch(
            "apps.submission.tasks.poll_invoice_status.delay"
        ) as mock_delay:
            result = sweep_inflight_polls()
        assert result["requeued"] == 0
        mock_delay.assert_not_called()

    def test_skips_invoices_without_submission_uid(self, org) -> None:
        # SUBMITTING but never reached LHDN (no submission_uid yet).
        # Polling without a UID is meaningless — skip.
        _make_invoice(
            org=org,
            submission_uid="",
            age_seconds=SWEEP_STALE_AFTER_SECONDS + 60,
        )
        with patch(
            "apps.submission.tasks.poll_invoice_status.delay"
        ) as mock_delay:
            result = sweep_inflight_polls()
        assert result["requeued"] == 0
        mock_delay.assert_not_called()

    def test_skips_terminal_states(self, org) -> None:
        for terminal in (
            Invoice.Status.VALIDATED,
            Invoice.Status.REJECTED,
            Invoice.Status.CANCELLED,
            Invoice.Status.READY_FOR_REVIEW,
        ):
            _make_invoice(
                org=org,
                status=terminal,
                age_seconds=SWEEP_STALE_AFTER_SECONDS + 60,
            )
        with patch(
            "apps.submission.tasks.poll_invoice_status.delay"
        ) as mock_delay:
            result = sweep_inflight_polls()
        assert result["requeued"] == 0
        mock_delay.assert_not_called()

    def test_caps_at_max_per_run(self, org) -> None:
        # Create more than the cap; sweep must batch.
        for i in range(SWEEP_MAX_PER_RUN + 5):
            _make_invoice(
                org=org,
                submission_uid=f"sub-{i}",
                age_seconds=SWEEP_STALE_AFTER_SECONDS + 60,
            )
        with patch(
            "apps.submission.tasks.poll_invoice_status.delay"
        ) as mock_delay:
            result = sweep_inflight_polls()
        assert result["requeued"] == SWEEP_MAX_PER_RUN
        assert mock_delay.call_count == SWEEP_MAX_PER_RUN
