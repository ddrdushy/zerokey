"""Spec-conformance tests for the LHDN client (Slice 59A).

Each test maps to a specific clause in
``docs/LHDN MyInvois API Integration Specification.md``:
batch limits, Retry-After honouring, /raw endpoint, typed
error codes, TIN cache, cancel + 72h window.
"""

from __future__ import annotations

import json
import time
from datetime import timedelta
from unittest.mock import MagicMock, patch

import httpx
import pytest
from django.utils import timezone

from apps.identity.integrations import upsert_credentials
from apps.identity.models import (
    Organization,
    OrganizationMembership,
    Role,
    User,
)
from apps.submission import lhdn_client, lhdn_submission, tin_validation
from apps.submission.models import Invoice, LineItem
from decimal import Decimal


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org_with_creds(seeded) -> Organization:
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
    upsert_credentials(
        organization_id=org.id,
        integration_key="lhdn_myinvois",
        environment="sandbox",
        field_updates={
            "client_id": "abc",
            "client_secret": "xyz",
            "tin": "C1234567890",
            "base_url": "https://preprod-api.myinvois.hasil.gov.my",
        },
        actor_user_id=user.id,
    )
    return org


def _resp(
    status_code: int,
    body: dict | None = None,
    headers: dict | None = None,
) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.headers = headers or {}
    if body is None:
        body = {}
    resp.json = MagicMock(return_value=body)
    resp.text = json.dumps(body)
    return resp


# =============================================================================
# §3.2 Token cache — TTL must include 5min buffer
# =============================================================================


@pytest.mark.django_db
class TestTokenCacheBuffer:
    def test_cache_ttl_subtracts_300s_buffer(self, org_with_creds) -> None:
        """Per spec §3.2: cache TTL = expires_in - 300."""
        creds = lhdn_client.credentials_for_org(
            organization_id=org_with_creds.id
        )
        lhdn_client._token_cache.clear()
        with patch(
            "apps.submission.lhdn_client.httpx.post",
            return_value=_resp(
                200, {"access_token": "tok", "expires_in": 3600}
            ),
        ):
            before = time.time()
            lhdn_client.get_access_token(creds)
            after = time.time()

        cache_key = (creds.client_id, creds.base_url)
        _, expires_at = lhdn_client._token_cache[cache_key]
        # expires_at should be roughly: now + 3600 - 300 = now + 3300.
        # Allow a generous fudge for clock movement during the test.
        assert before + 3300 - 5 <= expires_at <= after + 3300 + 5


# =============================================================================
# §4.1 Submit Documents — batch limits + Retry-After
# =============================================================================


@pytest.mark.django_db
class TestBatchLimits:
    def test_too_many_documents_rejected_before_http(
        self, org_with_creds
    ) -> None:
        creds = lhdn_client.credentials_for_org(
            organization_id=org_with_creds.id
        )
        lhdn_client._token_cache.clear()
        oversized = [
            {"format": "XML", "documentHash": "h", "codeNumber": str(i),
             "document": "x"}
            for i in range(101)
        ]
        with patch(
            "apps.submission.lhdn_client.httpx.post"
        ) as posted:
            with pytest.raises(lhdn_client.LHDNError, match="100 max"):
                lhdn_client.submit_documents(
                    creds=creds, signed_xml_documents=oversized
                )
        # Request never went on the wire.
        posted.assert_not_called()

    def test_per_document_size_limit(self, org_with_creds) -> None:
        creds = lhdn_client.credentials_for_org(
            organization_id=org_with_creds.id
        )
        lhdn_client._token_cache.clear()
        # 301 KB single document — over the 300 KB / doc limit.
        big_doc = {
            "format": "XML",
            "documentHash": "h",
            "codeNumber": "1",
            "document": "x" * (301 * 1024),
        }
        with patch("apps.submission.lhdn_client.httpx.post") as posted:
            with pytest.raises(lhdn_client.LHDNError, match="300 KB|307200"):
                lhdn_client.submit_documents(
                    creds=creds, signed_xml_documents=[big_doc]
                )
        posted.assert_not_called()

    def test_total_submission_size_limit(self, org_with_creds) -> None:
        creds = lhdn_client.credentials_for_org(
            organization_id=org_with_creds.id
        )
        lhdn_client._token_cache.clear()
        # 30 docs × 200 KB = 6 MB > 5 MB cap
        docs = [
            {"format": "XML", "documentHash": "h", "codeNumber": str(i),
             "document": "x" * (200 * 1024)}
            for i in range(30)
        ]
        with patch("apps.submission.lhdn_client.httpx.post") as posted:
            with pytest.raises(lhdn_client.LHDNError, match="5"):
                lhdn_client.submit_documents(
                    creds=creds, signed_xml_documents=docs
                )
        posted.assert_not_called()


@pytest.mark.django_db
class TestRateLimit:
    def test_429_raises_with_retry_after(self, org_with_creds) -> None:
        creds = lhdn_client.credentials_for_org(
            organization_id=org_with_creds.id
        )
        lhdn_client._token_cache.clear()
        with patch(
            "apps.submission.lhdn_client.httpx.post",
            side_effect=[
                _resp(200, {"access_token": "tok", "expires_in": 3600}),
                _resp(429, {}, headers={"Retry-After": "45"}),
            ],
        ):
            with pytest.raises(lhdn_client.LHDNRateLimitError) as exc_info:
                lhdn_client.submit_documents(
                    creds=creds,
                    signed_xml_documents=[
                        {
                            "format": "XML",
                            "documentHash": "h",
                            "codeNumber": "1",
                            "document": "ZGF0YQ==",
                        }
                    ],
                )
        assert exc_info.value.retry_after_seconds == 45

    def test_429_without_retry_after_returns_minus_one(
        self, org_with_creds
    ) -> None:
        creds = lhdn_client.credentials_for_org(
            organization_id=org_with_creds.id
        )
        lhdn_client._token_cache.clear()
        with patch(
            "apps.submission.lhdn_client.httpx.post",
            side_effect=[
                _resp(200, {"access_token": "tok", "expires_in": 3600}),
                _resp(429, {}, headers={}),
            ],
        ):
            with pytest.raises(lhdn_client.LHDNRateLimitError) as exc_info:
                lhdn_client.submit_documents(
                    creds=creds,
                    signed_xml_documents=[
                        {
                            "format": "XML",
                            "documentHash": "h",
                            "codeNumber": "1",
                            "document": "ZGF0YQ==",
                        }
                    ],
                )
        assert exc_info.value.retry_after_seconds == -1


# =============================================================================
# §7 — typed error codes
# =============================================================================


@pytest.mark.django_db
class TestTypedErrors:
    def test_duplicate_submission_typed(self, org_with_creds) -> None:
        creds = lhdn_client.credentials_for_org(
            organization_id=org_with_creds.id
        )
        lhdn_client._token_cache.clear()
        with patch(
            "apps.submission.lhdn_client.httpx.post",
            side_effect=[
                _resp(200, {"access_token": "tok", "expires_in": 3600}),
                _resp(
                    422,
                    {
                        "code": "DuplicateSubmission",
                        "message": "Same hash within 10min",
                    },
                    headers={"Retry-After": "600"},
                ),
            ],
        ):
            with pytest.raises(lhdn_client.LHDNDuplicateError) as exc_info:
                lhdn_client.submit_documents(
                    creds=creds,
                    signed_xml_documents=[
                        {
                            "format": "XML",
                            "documentHash": "h",
                            "codeNumber": "1",
                            "document": "ZGF0YQ==",
                        }
                    ],
                )
        assert exc_info.value.retry_after_seconds == 600

    def test_operation_period_over_typed(self, org_with_creds) -> None:
        creds = lhdn_client.credentials_for_org(
            organization_id=org_with_creds.id
        )
        lhdn_client._token_cache.clear()
        with patch(
            "apps.submission.lhdn_client.httpx.post",
            side_effect=[
                _resp(200, {"access_token": "tok", "expires_in": 3600}),
                _resp(
                    400,
                    {"code": "OperationPeriodOver", "message": "72h passed"},
                ),
            ],
        ):
            with pytest.raises(lhdn_client.LHDNCancellationWindowError):
                lhdn_client.submit_documents(
                    creds=creds,
                    signed_xml_documents=[
                        {
                            "format": "XML",
                            "documentHash": "h",
                            "codeNumber": "1",
                            "document": "ZGF0YQ==",
                        }
                    ],
                )


# =============================================================================
# §4.4 — get_document_raw uses /raw, not /details
# =============================================================================


@pytest.mark.django_db
class TestGetDocumentRaw:
    def test_uses_raw_endpoint(self, org_with_creds) -> None:
        creds = lhdn_client.credentials_for_org(
            organization_id=org_with_creds.id
        )
        lhdn_client._token_cache.clear()
        with patch(
            "apps.submission.lhdn_client.httpx.post",
            return_value=_resp(
                200, {"access_token": "tok", "expires_in": 3600}
            ),
        ), patch(
            "apps.submission.lhdn_client.httpx.get",
            return_value=_resp(200, {"longId": "abc123"}),
        ) as got:
            lhdn_client.get_document_raw(
                creds=creds, document_uuid="doc-xyz"
            )
        called_url = got.call_args[0][0]
        assert called_url.endswith("/api/v1.0/documents/doc-xyz/raw")
        assert "/details" not in called_url

    def test_back_compat_alias_get_document_qr(
        self, org_with_creds
    ) -> None:
        # Slice 58 callers used get_document_qr; alias must still work.
        assert lhdn_client.get_document_qr is lhdn_client.get_document_raw


# =============================================================================
# §4.5 — TIN validation + 24h cache
# =============================================================================


@pytest.mark.django_db
class TestTinValidation:
    def test_valid_tin_returns_true(self, org_with_creds) -> None:
        from django.core.cache import cache as django_cache

        django_cache.clear()
        lhdn_client._token_cache.clear()
        with patch(
            "apps.submission.lhdn_client.httpx.post",
            return_value=_resp(
                200, {"access_token": "tok", "expires_in": 3600}
            ),
        ), patch(
            "apps.submission.lhdn_client.httpx.get",
            return_value=_resp(200, {}),
        ):
            ok = tin_validation.is_tin_valid(
                organization_id=org_with_creds.id, tin="C1234567890"
            )
        assert ok is True

    def test_invalid_tin_returns_false(self, org_with_creds) -> None:
        from django.core.cache import cache as django_cache

        django_cache.clear()
        lhdn_client._token_cache.clear()
        with patch(
            "apps.submission.lhdn_client.httpx.post",
            return_value=_resp(
                200, {"access_token": "tok", "expires_in": 3600}
            ),
        ), patch(
            "apps.submission.lhdn_client.httpx.get",
            return_value=_resp(404, {}),
        ):
            ok = tin_validation.is_tin_valid(
                organization_id=org_with_creds.id, tin="C0000000000"
            )
        assert ok is False

    def test_cache_short_circuits_second_call(
        self, org_with_creds
    ) -> None:
        from django.core.cache import cache as django_cache

        django_cache.clear()
        lhdn_client._token_cache.clear()
        with patch(
            "apps.submission.lhdn_client.httpx.post",
            return_value=_resp(
                200, {"access_token": "tok", "expires_in": 3600}
            ),
        ), patch(
            "apps.submission.lhdn_client.httpx.get",
            return_value=_resp(200, {}),
        ) as got:
            tin_validation.is_tin_valid(
                organization_id=org_with_creds.id, tin="C9999999999"
            )
            tin_validation.is_tin_valid(
                organization_id=org_with_creds.id, tin="C9999999999"
            )
        # Second call hit the cache, not the network.
        assert got.call_count == 1

    def test_invalidate_drops_entry(self, org_with_creds) -> None:
        from django.core.cache import cache as django_cache

        django_cache.clear()
        lhdn_client._token_cache.clear()
        with patch(
            "apps.submission.lhdn_client.httpx.post",
            return_value=_resp(
                200, {"access_token": "tok", "expires_in": 3600}
            ),
        ), patch(
            "apps.submission.lhdn_client.httpx.get",
            return_value=_resp(200, {}),
        ) as got:
            tin_validation.is_tin_valid(
                organization_id=org_with_creds.id, tin="C7777777777"
            )
            tin_validation.invalidate_cached_tin(tin="C7777777777")
            tin_validation.is_tin_valid(
                organization_id=org_with_creds.id, tin="C7777777777"
            )
        # Second call re-hit LHDN because we invalidated.
        assert got.call_count == 2


# =============================================================================
# §4.3 — cancel document + 72-hour window
# =============================================================================


@pytest.fixture
def submitted_invoice(org_with_creds) -> Invoice:
    """Invoice that already has lhdn_uuid + a recent validation_timestamp."""
    inv = Invoice.objects.create(
        organization=org_with_creds,
        ingestion_job_id="22222222-2222-2222-2222-222222222222",
        invoice_number="INV-CXL-001",
        currency_code="MYR",
        supplier_legal_name="Acme",
        supplier_tin="C1234567890",
        buyer_legal_name="Globex",
        buyer_tin="C9999999999",
        subtotal=Decimal("100.00"),
        total_tax=Decimal("8.00"),
        grand_total=Decimal("108.00"),
        status=Invoice.Status.VALIDATED,
        lhdn_uuid="doc-uuid-001",
        validation_timestamp=timezone.now() - timedelta(hours=2),
    )
    LineItem.objects.create(
        organization=org_with_creds,
        invoice=inv,
        line_number=1,
        line_subtotal_excl_tax=Decimal("100.00"),
    )
    return inv


@pytest.mark.django_db
class TestCancel:
    def test_cancel_within_window_succeeds(
        self, org_with_creds, submitted_invoice
    ) -> None:
        lhdn_client._token_cache.clear()
        with patch(
            "apps.submission.lhdn_client.httpx.post",
            return_value=_resp(
                200, {"access_token": "tok", "expires_in": 3600}
            ),
        ), patch(
            "apps.submission.lhdn_client.httpx.put",
            return_value=_resp(200, {"status": "cancelled"}),
        ):
            result = lhdn_submission.cancel_invoice(
                invoice_id=submitted_invoice.id,
                reason="customer changed their order",
                actor_user_id="00000000-0000-0000-0000-000000000000",
            )
        assert result["ok"] is True
        submitted_invoice.refresh_from_db()
        assert submitted_invoice.status == Invoice.Status.CANCELLED
        assert submitted_invoice.cancellation_timestamp is not None

    def test_cancel_outside_window_blocked_locally(
        self, org_with_creds, submitted_invoice
    ) -> None:
        # Push validation_timestamp back beyond 72 hours.
        submitted_invoice.validation_timestamp = (
            timezone.now() - timedelta(hours=80)
        )
        submitted_invoice.save()
        lhdn_client._token_cache.clear()
        # No HTTP call should be made.
        with patch("apps.submission.lhdn_client.httpx.put") as putted:
            result = lhdn_submission.cancel_invoice(
                invoice_id=submitted_invoice.id,
                reason="too late",
                actor_user_id="00000000-0000-0000-0000-000000000000",
            )
        assert result["ok"] is False
        assert "credit note" in result["reason"]
        putted.assert_not_called()

    def test_cancel_lhdn_period_over_falls_back_to_credit_note_message(
        self, org_with_creds, submitted_invoice
    ) -> None:
        # Local clock thinks we're inside the window, but LHDN says no.
        lhdn_client._token_cache.clear()
        with patch(
            "apps.submission.lhdn_client.httpx.post",
            return_value=_resp(
                200, {"access_token": "tok", "expires_in": 3600}
            ),
        ), patch(
            "apps.submission.lhdn_client.httpx.put",
            return_value=_resp(
                400, {"code": "OperationPeriodOver", "message": "72h"}
            ),
        ):
            result = lhdn_submission.cancel_invoice(
                invoice_id=submitted_invoice.id,
                reason="late by their clock",
                actor_user_id="00000000-0000-0000-0000-000000000000",
            )
        assert result["ok"] is False
        assert "credit note" in result["reason"]

    def test_cancel_requires_reason(
        self, org_with_creds, submitted_invoice
    ) -> None:
        result = lhdn_submission.cancel_invoice(
            invoice_id=submitted_invoice.id,
            reason="",
            actor_user_id="00000000-0000-0000-0000-000000000000",
        )
        assert result["ok"] is False
        assert "reason" in result["reason"].lower()

    def test_cancel_unsubmitted_invoice_refused(
        self, org_with_creds
    ) -> None:
        # Invoice exists but has no lhdn_uuid yet.
        inv = Invoice.objects.create(
            organization=org_with_creds,
            ingestion_job_id="33333333-3333-3333-3333-333333333333",
            status=Invoice.Status.READY_FOR_REVIEW,
        )
        result = lhdn_submission.cancel_invoice(
            invoice_id=inv.id,
            reason="cancelling early",
            actor_user_id="00000000-0000-0000-0000-000000000000",
        )
        assert result["ok"] is False
        assert "not been submitted" in result["reason"]
