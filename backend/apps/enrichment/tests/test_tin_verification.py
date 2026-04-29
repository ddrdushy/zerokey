"""Tests for live LHDN TIN verification (Slice 70)."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.enrichment import tin_verification
from apps.enrichment.models import CustomerMaster
from apps.identity.models import Organization, OrganizationMembership, Role, User
from apps.submission import lhdn_client


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org(seeded) -> Organization:
    return Organization.objects.create(
        legal_name="VerifyTest Sdn Bhd",
        tin="C1234567890",
        contact_email="ops@verifytest.example",
    )


@pytest.fixture
def org_with_lhdn_creds(org) -> Organization:
    user = User.objects.create_user(
        email="o@verifytest.example", password="long-enough-password"
    )
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name="owner")
    )
    from apps.identity.integrations import upsert_credentials

    upsert_credentials(
        organization_id=org.id,
        integration_key="lhdn_myinvois",
        environment="sandbox",
        field_updates={
            "client_id": "demo-client",
            "client_secret": "demo-secret",
            "tin": "C1234567890",
            "base_url": "https://preprod-api.myinvois.hasil.gov.my",
        },
        actor_user_id=user.id,
    )
    return org


def _make_master(
    *,
    org: Organization,
    tin: str = "C9999999999",
    state: str = CustomerMaster.TinVerificationState.UNVERIFIED,
    last_verified_at=None,
) -> CustomerMaster:
    return CustomerMaster.objects.create(
        organization=org,
        legal_name="Acme Customer",
        tin=tin,
        tin_verification_state=state,
        tin_last_verified_at=last_verified_at,
    )


# =============================================================================
# needs_verification
# =============================================================================


@pytest.mark.django_db
class TestNeedsVerification:
    def test_unverified_with_tin_yes(self, org) -> None:
        master = _make_master(org=org)
        assert tin_verification.needs_verification(master) is True

    def test_unverified_no_tin_no(self, org) -> None:
        master = _make_master(org=org, tin="")
        assert tin_verification.needs_verification(master) is False

    def test_freshly_verified_no(self, org) -> None:
        master = _make_master(
            org=org,
            state=CustomerMaster.TinVerificationState.VERIFIED,
            last_verified_at=timezone.now() - timedelta(days=5),
        )
        assert tin_verification.needs_verification(master) is False

    def test_stale_verified_yes(self, org) -> None:
        master = _make_master(
            org=org,
            state=CustomerMaster.TinVerificationState.VERIFIED,
            last_verified_at=timezone.now()
            - timedelta(days=tin_verification.VERIFY_REFRESH_DAYS + 1),
        )
        assert tin_verification.needs_verification(master) is True

    def test_failed_recent_no(self, org) -> None:
        master = _make_master(
            org=org,
            state=CustomerMaster.TinVerificationState.FAILED,
            last_verified_at=timezone.now() - timedelta(days=1),
        )
        # Recently failed — back off, don't hammer LHDN.
        assert tin_verification.needs_verification(master) is False

    def test_failed_stale_yes(self, org) -> None:
        # Old "failed" gets retried in case the customer corrected
        # the TIN since.
        master = _make_master(
            org=org,
            state=CustomerMaster.TinVerificationState.FAILED,
            last_verified_at=timezone.now()
            - timedelta(days=tin_verification.VERIFY_REFRESH_DAYS + 1),
        )
        assert tin_verification.needs_verification(master) is True


# =============================================================================
# verify_master_tin
# =============================================================================


@pytest.mark.django_db
class TestVerifyMasterTin:
    def test_recognized_tin_marks_verified(self, org_with_lhdn_creds) -> None:
        master = _make_master(org=org_with_lhdn_creds)
        with patch(
            "apps.submission.lhdn_client.validate_tin", return_value=True
        ):
            result = tin_verification.verify_master_tin(master.id)
        assert result["state"] == CustomerMaster.TinVerificationState.VERIFIED
        master.refresh_from_db()
        assert (
            master.tin_verification_state
            == CustomerMaster.TinVerificationState.VERIFIED
        )
        assert master.tin_last_verified_at is not None

    def test_unrecognized_tin_marks_failed(self, org_with_lhdn_creds) -> None:
        master = _make_master(org=org_with_lhdn_creds)
        with patch(
            "apps.submission.lhdn_client.validate_tin", return_value=False
        ):
            result = tin_verification.verify_master_tin(master.id)
        assert result["state"] == CustomerMaster.TinVerificationState.FAILED
        master.refresh_from_db()
        assert (
            master.tin_verification_state
            == CustomerMaster.TinVerificationState.FAILED
        )

    def test_no_creds_leaves_unverified(self, org) -> None:
        # Org has no LHDN integration row. Master stays unverified.
        master = _make_master(org=org)
        result = tin_verification.verify_master_tin(master.id)
        assert result == {"state": "skipped", "reason": "no_creds"}
        master.refresh_from_db()
        assert (
            master.tin_verification_state
            == CustomerMaster.TinVerificationState.UNVERIFIED
        )

    def test_no_tin_skipped(self, org_with_lhdn_creds) -> None:
        master = _make_master(org=org_with_lhdn_creds, tin="")
        result = tin_verification.verify_master_tin(master.id)
        assert result == {"state": "skipped", "reason": "no_tin"}

    def test_lhdn_rate_limit_keeps_state(self, org_with_lhdn_creds) -> None:
        master = _make_master(org=org_with_lhdn_creds)
        with patch(
            "apps.submission.lhdn_client.validate_tin",
            side_effect=lhdn_client.LHDNRateLimitError(
                "rate limited", retry_after_seconds=60
            ),
        ):
            result = tin_verification.verify_master_tin(master.id)
        assert result == {"state": "skipped", "reason": "lhdn_rate_limit"}
        master.refresh_from_db()
        # Transient — state must NOT flip to failed.
        assert (
            master.tin_verification_state
            == CustomerMaster.TinVerificationState.UNVERIFIED
        )

    def test_lhdn_transient_keeps_state(self, org_with_lhdn_creds) -> None:
        master = _make_master(
            org=org_with_lhdn_creds,
            state=CustomerMaster.TinVerificationState.VERIFIED,
            last_verified_at=timezone.now() - timedelta(days=200),
        )
        with patch(
            "apps.submission.lhdn_client.validate_tin",
            side_effect=lhdn_client.LHDNError("connectivity"),
        ):
            result = tin_verification.verify_master_tin(master.id)
        assert result["reason"] == "lhdn_transient"
        master.refresh_from_db()
        # Don't flip a previously-verified row to failed on transient.
        assert (
            master.tin_verification_state
            == CustomerMaster.TinVerificationState.VERIFIED
        )

    def test_audit_omits_tin_value(self, org_with_lhdn_creds) -> None:
        from apps.audit.models import AuditEvent

        master = _make_master(org=org_with_lhdn_creds, tin="C-VERY-SECRET")
        with patch(
            "apps.submission.lhdn_client.validate_tin", return_value=True
        ):
            tin_verification.verify_master_tin(master.id)
        ev = AuditEvent.objects.filter(
            action_type="enrichment.tin_verified"
        ).first()
        assert ev is not None
        # The TIN string itself must NOT appear in payload.
        assert "C-VERY-SECRET" not in str(ev.payload)
        assert ev.payload["from_state"] == "unverified"
        assert ev.payload["to_state"] == "verified"
