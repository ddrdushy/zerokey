"""Tests for TOTP 2FA (Slice 89)."""

from __future__ import annotations

import json
import time

import pytest
from django.test import Client

from apps.identity import totp
from apps.identity.models import (
    Organization,
    OrganizationMembership,
    Role,
    User,
)


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def authed(seeded) -> tuple[Client, User]:
    org = Organization.objects.create(
        legal_name="Acme", tin="C1234567890", contact_email="o@a.example"
    )
    user = User.objects.create_user(email="o@a.example", password="long-enough-password")
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name="owner")
    )
    client = Client()
    client.force_login(user)
    return client, user


# =============================================================================
# Pure crypto: HOTP / TOTP / recovery codes
# =============================================================================


class TestTotpPrimitives:
    def test_hotp_known_vector(self) -> None:
        # RFC-4226 Appendix D test vectors. Secret: ASCII
        # "12345678901234567890" — base32 = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ".
        secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
        # The well-known counter=0..9 expected codes.
        expected = [
            "755224",
            "287082",
            "359152",
            "969429",
            "338314",
            "254676",
            "287922",
            "162583",
            "399871",
            "520489",
        ]
        for counter, code in enumerate(expected):
            assert totp._hotp(secret, counter) == code

    def test_verify_accepts_current_code(self) -> None:
        secret = totp._generate_secret()
        now = time.time()
        code = totp._hotp(secret, int(now // totp.TIME_STEP_SECONDS))
        assert totp.verify_code(secret_b32=secret, code=code, at=now) is True

    def test_verify_within_drift_tolerance(self) -> None:
        secret = totp._generate_secret()
        now = time.time()
        # Code from 30s ago — still inside the ±1 step tolerance.
        old_counter = int(now // totp.TIME_STEP_SECONDS) - 1
        code = totp._hotp(secret, old_counter)
        assert totp.verify_code(secret_b32=secret, code=code, at=now) is True

    def test_verify_rejects_outside_drift(self) -> None:
        secret = totp._generate_secret()
        now = time.time()
        # 60s+ ago: outside the tolerance window.
        ancient = int(now // totp.TIME_STEP_SECONDS) - 5
        code = totp._hotp(secret, ancient)
        assert totp.verify_code(secret_b32=secret, code=code, at=now) is False

    def test_verify_rejects_wrong_code(self) -> None:
        secret = totp._generate_secret()
        assert totp.verify_code(secret_b32=secret, code="000000") is False

    def test_verify_strips_separator(self) -> None:
        secret = totp._generate_secret()
        now = time.time()
        code = totp._hotp(secret, int(now // totp.TIME_STEP_SECONDS))
        # User-formatted "123 456" or "123-456" — both must work.
        formatted = f"{code[:3]} {code[3:]}"
        assert totp.verify_code(secret_b32=secret, code=formatted, at=now) is True

    def test_provisioning_uri_format(self) -> None:
        uri = totp.provisioning_uri(account_email="x@y", secret_b32="ABC123")
        assert uri.startswith("otpauth://totp/ZeroKey%3Ax%40y?")
        assert "secret=ABC123" in uri
        assert "issuer=ZeroKey" in uri


class TestRecoveryCodes:
    def test_generates_eight_unique_codes(self) -> None:
        codes = totp.generate_recovery_codes()
        assert len(codes) == 8
        assert len(set(codes)) == 8
        for c in codes:
            assert len(c) == 17  # "xxxxxxxx-xxxxxxxx"
            assert c.count("-") == 1

    def test_hash_is_stable(self) -> None:
        c = "abcdefab-12345678"
        assert totp.hash_recovery_code(c) == totp.hash_recovery_code(c)
        # Whitespace + case insensitive normalisation.
        assert totp.hash_recovery_code(c) == totp.hash_recovery_code(" ABCDEFAB-12345678 ")


# =============================================================================
# Endpoints — enroll / confirm / disable / login challenge
# =============================================================================


@pytest.mark.django_db
class TestEnrollFlow:
    def test_enroll_returns_secret_and_uri(self, authed) -> None:
        client, user = authed
        response = client.post("/api/v1/identity/me/2fa/enroll/")
        assert response.status_code == 200
        body = response.json()
        assert body["secret"]
        assert body["provisioning_uri"].startswith("otpauth://totp/")
        # User row carries the encrypted secret but is NOT enabled yet.
        user.refresh_from_db()
        assert user.totp_secret_encrypted
        assert user.two_factor_enabled is False

    def test_confirm_with_valid_code_enables_and_returns_recovery(self, authed) -> None:
        client, user = authed
        client.post("/api/v1/identity/me/2fa/enroll/")
        user.refresh_from_db()
        secret = totp.decrypt_secret(user.totp_secret_encrypted)
        code = totp._hotp(secret, int(time.time() // totp.TIME_STEP_SECONDS))

        response = client.post(
            "/api/v1/identity/me/2fa/confirm/",
            data=json.dumps({"code": code}),
            content_type="application/json",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert len(body["recovery_codes"]) == 8

        user.refresh_from_db()
        assert user.two_factor_enabled is True
        assert len(user.totp_recovery_hashes) == 8

    def test_confirm_with_invalid_code_rejects(self, authed) -> None:
        client, _ = authed
        client.post("/api/v1/identity/me/2fa/enroll/")
        response = client.post(
            "/api/v1/identity/me/2fa/confirm/",
            data=json.dumps({"code": "000000"}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_confirm_without_enroll_rejects(self, authed) -> None:
        client, _ = authed
        response = client.post(
            "/api/v1/identity/me/2fa/confirm/",
            data=json.dumps({"code": "123456"}),
            content_type="application/json",
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestDisable:
    def test_disable_with_valid_code(self, authed) -> None:
        client, user = authed
        # Get into the 2FA-on state.
        client.post("/api/v1/identity/me/2fa/enroll/")
        user.refresh_from_db()
        secret = totp.decrypt_secret(user.totp_secret_encrypted)
        code = totp._hotp(secret, int(time.time() // totp.TIME_STEP_SECONDS))
        client.post(
            "/api/v1/identity/me/2fa/confirm/",
            data=json.dumps({"code": code}),
            content_type="application/json",
        )

        # Disable using a fresh code (still inside the same time step).
        code2 = totp._hotp(secret, int(time.time() // totp.TIME_STEP_SECONDS))
        response = client.post(
            "/api/v1/identity/me/2fa/disable/",
            data=json.dumps({"code": code2}),
            content_type="application/json",
        )
        assert response.status_code == 200
        user.refresh_from_db()
        assert user.two_factor_enabled is False
        assert user.totp_secret_encrypted == ""

    def test_disable_with_invalid_code_rejects(self, authed) -> None:
        client, user = authed
        client.post("/api/v1/identity/me/2fa/enroll/")
        user.refresh_from_db()
        secret = totp.decrypt_secret(user.totp_secret_encrypted)
        code = totp._hotp(secret, int(time.time() // totp.TIME_STEP_SECONDS))
        client.post(
            "/api/v1/identity/me/2fa/confirm/",
            data=json.dumps({"code": code}),
            content_type="application/json",
        )

        response = client.post(
            "/api/v1/identity/me/2fa/disable/",
            data=json.dumps({"code": "000000"}),
            content_type="application/json",
        )
        assert response.status_code == 401
        user.refresh_from_db()
        assert user.two_factor_enabled is True


@pytest.mark.django_db
class TestLoginChallenge:
    def _enable_2fa_for(self, user: User) -> str:
        plain, encrypted = totp.generate_secret_encrypted()
        user.totp_secret_encrypted = encrypted
        user.two_factor_enabled = True
        user.save(update_fields=["totp_secret_encrypted", "two_factor_enabled"])
        return plain

    def test_login_returns_needs_2fa_when_enabled(self, seeded) -> None:
        org = Organization.objects.create(legal_name="A", tin="C1", contact_email="o@a.example")
        user = User.objects.create_user(email="x@a.example", password="long-enough-password")
        OrganizationMembership.objects.create(
            user=user, organization=org, role=Role.objects.get(name="owner")
        )
        self._enable_2fa_for(user)

        client = Client()
        response = client.post(
            "/api/v1/identity/login/",
            data=json.dumps({"email": "x@a.example", "password": "long-enough-password"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["needs_2fa"] is True

        # User is NOT yet logged in — /me/ should redirect / 403.
        me = client.get("/api/v1/identity/me/")
        assert me.status_code in (401, 403)

    def test_complete_with_valid_code(self, seeded) -> None:
        org = Organization.objects.create(legal_name="A", tin="C2", contact_email="o2@a.example")
        user = User.objects.create_user(email="y@a.example", password="long-enough-password")
        OrganizationMembership.objects.create(
            user=user, organization=org, role=Role.objects.get(name="owner")
        )
        secret = self._enable_2fa_for(user)

        client = Client()
        client.post(
            "/api/v1/identity/login/",
            data=json.dumps({"email": "y@a.example", "password": "long-enough-password"}),
            content_type="application/json",
        )
        code = totp._hotp(secret, int(time.time() // totp.TIME_STEP_SECONDS))
        response = client.post(
            "/api/v1/identity/login/2fa/",
            data=json.dumps({"code": code}),
            content_type="application/json",
        )
        assert response.status_code == 200
        # /me/ now succeeds.
        me = client.get("/api/v1/identity/me/")
        assert me.status_code == 200

    def test_recovery_code_consumed_on_use(self, seeded) -> None:
        org = Organization.objects.create(legal_name="A", tin="C3", contact_email="o3@a.example")
        user = User.objects.create_user(email="z@a.example", password="long-enough-password")
        OrganizationMembership.objects.create(
            user=user, organization=org, role=Role.objects.get(name="owner")
        )
        self._enable_2fa_for(user)

        # Mint a recovery code on the user directly.
        plain_codes = totp.generate_recovery_codes()
        user.totp_recovery_hashes = [totp.hash_recovery_code(c) for c in plain_codes]
        user.save(update_fields=["totp_recovery_hashes"])

        client = Client()
        client.post(
            "/api/v1/identity/login/",
            data=json.dumps({"email": "z@a.example", "password": "long-enough-password"}),
            content_type="application/json",
        )
        first_code = plain_codes[0]
        response = client.post(
            "/api/v1/identity/login/2fa/",
            data=json.dumps({"code": first_code}),
            content_type="application/json",
        )
        assert response.status_code == 200

        # The same recovery code can't be reused.
        user.refresh_from_db()
        assert len(user.totp_recovery_hashes) == 7
