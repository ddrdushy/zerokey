"""Tests for the customer-facing LHDN lifecycle endpoints (Slice 59B)."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import httpx
import pytest
from django.test import Client
from django.utils import timezone

from apps.identity.integrations import upsert_credentials
from apps.identity.models import (
    Organization,
    OrganizationMembership,
    Role,
    User,
)
from apps.submission import lhdn_client
from apps.submission.models import Invoice, LineItem


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org_owner(seeded) -> tuple[Organization, User]:
    org = Organization.objects.create(
        legal_name="Acme",
        tin="C1234567890",
        contact_email="o@a",
    )
    user = User.objects.create_user(email="owner@a", password="long-enough-password")
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
    return org, user


@pytest.fixture
def viewer_member(seeded) -> tuple[Organization, User]:
    org = Organization.objects.create(legal_name="X", tin="C2222222222", contact_email="o@x")
    user = User.objects.create_user(email="viewer@x", password="long-enough-password")
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name="viewer")
    )
    return org, user


@pytest.fixture
def authed(org_owner) -> tuple[Client, Organization, User]:
    org, user = org_owner
    client = Client()
    client.force_login(user)
    session = client.session
    session["organization_id"] = str(org.id)
    session.save()
    return client, org, user


@pytest.fixture
def ready_invoice(org_owner) -> Invoice:
    org, _ = org_owner
    inv = Invoice.objects.create(
        organization=org,
        ingestion_job_id="44444444-4444-4444-4444-444444444444",
        invoice_number="INV-2026-009",
        currency_code="MYR",
        supplier_legal_name="Acme",
        supplier_tin="C1234567890",
        buyer_legal_name="Globex",
        buyer_tin="C9999999999",
        subtotal=Decimal("100.00"),
        total_tax=Decimal("8.00"),
        grand_total=Decimal("108.00"),
        status=Invoice.Status.READY_FOR_REVIEW,
    )
    LineItem.objects.create(
        organization=org,
        invoice=inv,
        line_number=1,
        line_subtotal_excl_tax=Decimal("100.00"),
    )
    return inv


def _resp(status_code: int, body: dict | None = None, headers: dict | None = None) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.json = MagicMock(return_value=body or {})
    resp.text = json.dumps(body or {})
    return resp


# =============================================================================
# Submit endpoint
# =============================================================================


@pytest.mark.django_db
class TestSubmitEndpoint:
    def test_unauthenticated_rejected(self, ready_invoice) -> None:
        response = Client().post(f"/api/v1/invoices/{ready_invoice.id}/submit-to-lhdn/")
        assert response.status_code in (401, 403)

    def test_viewer_role_blocked(self, viewer_member) -> None:
        org, viewer = viewer_member
        inv = Invoice.objects.create(
            organization=org,
            ingestion_job_id="55555555-5555-5555-5555-555555555555",
            invoice_number="INV-X",
            status=Invoice.Status.READY_FOR_REVIEW,
        )
        client = Client()
        client.force_login(viewer)
        session = client.session
        session["organization_id"] = str(org.id)
        session.save()
        response = client.post(f"/api/v1/invoices/{inv.id}/submit-to-lhdn/")
        assert response.status_code == 403

    def test_pre_flight_rejects_blank_invoice_number(self, authed, org_owner) -> None:
        client, org, _ = authed
        inv = Invoice.objects.create(
            organization=org,
            ingestion_job_id="66666666-6666-6666-6666-666666666666",
            invoice_number="",
            status=Invoice.Status.READY_FOR_REVIEW,
        )
        response = client.post(f"/api/v1/invoices/{inv.id}/submit-to-lhdn/")
        assert response.status_code == 400
        assert "Invoice number" in response.json()["detail"]

    def test_pre_flight_rejects_already_validated(self, authed, ready_invoice) -> None:
        ready_invoice.status = Invoice.Status.VALIDATED
        ready_invoice.lhdn_uuid = "doc-xyz"
        ready_invoice.save()
        client, _, _ = authed
        response = client.post(f"/api/v1/invoices/{ready_invoice.id}/submit-to-lhdn/")
        assert response.status_code == 400

    def test_happy_path_returns_invoice(self, authed, ready_invoice) -> None:
        client, _, _ = authed
        lhdn_client._token_cache.clear()
        with patch(
            "apps.submission.lhdn_client.httpx.post",
            side_effect=[
                _resp(200, {"access_token": "tok", "expires_in": 3600}),
                _resp(
                    202,
                    {
                        "submissionUid": "sub-1",
                        "acceptedDocuments": [{"uuid": "u-1", "invoiceCodeNumber": "INV-2026-009"}],
                        "rejectedDocuments": [],
                    },
                ),
            ],
        ):
            response = client.post(f"/api/v1/invoices/{ready_invoice.id}/submit-to-lhdn/")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["submission_uid"] == "sub-1"
        assert body["invoice"]["status"] == "submitting"
        assert body["invoice"]["lhdn_uuid"] == "u-1"


# =============================================================================
# Cancel endpoint
# =============================================================================


@pytest.fixture
def submitted_invoice(org_owner) -> Invoice:
    org, _ = org_owner
    inv = Invoice.objects.create(
        organization=org,
        ingestion_job_id="77777777-7777-7777-7777-777777777777",
        invoice_number="INV-CXL-001",
        status=Invoice.Status.VALIDATED,
        lhdn_uuid="doc-uuid-001",
        validation_timestamp=timezone.now() - timedelta(hours=2),
    )
    return inv


@pytest.mark.django_db
class TestCancelEndpoint:
    def test_requires_reason(self, authed, submitted_invoice) -> None:
        client, _, _ = authed
        response = client.post(
            f"/api/v1/invoices/{submitted_invoice.id}/cancel-lhdn/",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["ok"] is False
        assert "reason" in response.json()["reason"].lower()

    def test_happy_path(self, authed, submitted_invoice) -> None:
        client, _, _ = authed
        lhdn_client._token_cache.clear()
        with (
            patch(
                "apps.submission.lhdn_client.httpx.post",
                return_value=_resp(200, {"access_token": "tok", "expires_in": 3600}),
            ),
            patch(
                "apps.submission.lhdn_client.httpx.put",
                return_value=_resp(200, {"status": "cancelled"}),
            ),
        ):
            response = client.post(
                f"/api/v1/invoices/{submitted_invoice.id}/cancel-lhdn/",
                data=json.dumps({"reason": "customer changed order"}),
                content_type="application/json",
            )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["invoice"]["status"] == "cancelled"

    def test_outside_72h_returns_credit_note_message(self, authed, submitted_invoice) -> None:
        submitted_invoice.validation_timestamp = timezone.now() - timedelta(hours=80)
        submitted_invoice.save()
        client, _, _ = authed
        response = client.post(
            f"/api/v1/invoices/{submitted_invoice.id}/cancel-lhdn/",
            data=json.dumps({"reason": "too late"}),
            content_type="application/json",
        )
        body = response.json()
        assert body["ok"] is False
        assert "credit note" in body["reason"]


# =============================================================================
# Poll endpoint
# =============================================================================


@pytest.mark.django_db
class TestPollEndpoint:
    def test_poll_no_submission_uid(self, authed, ready_invoice) -> None:
        client, _, _ = authed
        response = client.post(f"/api/v1/invoices/{ready_invoice.id}/poll-lhdn/")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False

    def test_poll_terminal_validated(self, authed, submitted_invoice) -> None:
        # Park a submission_uid on the row so poll has something to look up.
        submitted_invoice.submission_uid = "sub-xyz"
        submitted_invoice.status = Invoice.Status.SUBMITTING
        submitted_invoice.save()
        client, _, _ = authed
        lhdn_client._token_cache.clear()
        with (
            patch(
                "apps.submission.lhdn_client.httpx.post",
                return_value=_resp(200, {"access_token": "tok", "expires_in": 3600}),
            ),
            patch(
                "apps.submission.lhdn_client.httpx.get",
                side_effect=[
                    _resp(
                        200,
                        {
                            "submissionUid": "sub-xyz",
                            "overallStatus": "Valid",
                            "documentSummary": [
                                {
                                    "uuid": "doc-uuid-001",
                                    "status": "Valid",
                                    "invoiceCodeNumber": "INV-CXL-001",
                                }
                            ],
                        },
                    ),
                    _resp(200, {"longId": "longid-abc"}),
                ],
            ),
        ):
            response = client.post(f"/api/v1/invoices/{submitted_invoice.id}/poll-lhdn/")
        body = response.json()
        assert body["ok"] is True
        assert body["document_status"] == "Valid"
        assert body["invoice"]["status"] == "validated"
        assert "preprod.myinvois.hasil.gov.my" in body["invoice"]["lhdn_qr_code_url"]


# =============================================================================
# Cert endpoint
# =============================================================================


@pytest.mark.django_db
class TestCertificateEndpoint:
    def test_get_returns_state(self, authed) -> None:
        client, _, _ = authed
        response = client.get("/api/v1/identity/organization/certificate/")
        assert response.status_code == 200
        body = response.json()
        assert body["uploaded"] is False

    def test_post_rejects_invalid_pem(self, authed) -> None:
        client, _, _ = authed
        response = client.post(
            "/api/v1/identity/organization/certificate/",
            data=json.dumps({"cert_pem": "not-a-pem", "private_key_pem": "also-not"}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_post_rejects_mismatched_pair(self, authed) -> None:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        # Generate two distinct RSA keys → cert from one, key from the other.
        key_a = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        key_b = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key_a.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(timezone.now())
            .not_valid_after(timezone.now() + timedelta(days=30))
            .sign(key_a, hashes.SHA256())
        )
        cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
        # Use key_b — mismatched.
        wrong_key_pem = key_b.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()

        client, _, _ = authed
        response = client.post(
            "/api/v1/identity/organization/certificate/",
            data=json.dumps({"cert_pem": cert_pem, "private_key_pem": wrong_key_pem}),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "matched pair" in response.json()["detail"]

    def test_post_happy_path(self, authed) -> None:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Acme Sdn Bhd")])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(timezone.now())
            .not_valid_after(timezone.now() + timedelta(days=365))
            .sign(key, hashes.SHA256())
        )
        cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
        key_pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()

        client, _, _ = authed
        response = client.post(
            "/api/v1/identity/organization/certificate/",
            data=json.dumps({"cert_pem": cert_pem, "private_key_pem": key_pem}),
            content_type="application/json",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["uploaded"] is True
        assert body["kind"] == "uploaded"
        assert body["subject_common_name"] == "Acme Sdn Bhd"

    def _build_pfx_bundle(self, *, password: str, common_name: str = "PFX Co") -> bytes:
        """Build a real PFX/P12 bundle for the test cases below."""

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives.serialization import pkcs12
        from cryptography.x509.oid import NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(timezone.now())
            .not_valid_after(timezone.now() + timedelta(days=365))
            .sign(key, hashes.SHA256())
        )
        encryption = (
            serialization.BestAvailableEncryption(password.encode("utf-8"))
            if password
            else serialization.NoEncryption()
        )
        return pkcs12.serialize_key_and_certificates(
            name=common_name.encode("utf-8"),
            key=key,
            cert=cert,
            cas=None,
            encryption_algorithm=encryption,
        )

    def test_post_pfx_happy_path(self, authed) -> None:
        import base64

        client, _, _ = authed
        pfx_bytes = self._build_pfx_bundle(password="test-pass", common_name="PFX Co")
        response = client.post(
            "/api/v1/identity/organization/certificate/",
            data=json.dumps(
                {
                    "pfx_b64": base64.b64encode(pfx_bytes).decode("ascii"),
                    "pfx_password": "test-pass",
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["uploaded"] is True
        assert body["kind"] == "uploaded"
        assert body["subject_common_name"] == "PFX Co"

    def test_post_pfx_wrong_password(self, authed) -> None:
        import base64

        client, _, _ = authed
        pfx_bytes = self._build_pfx_bundle(password="real-pass")
        response = client.post(
            "/api/v1/identity/organization/certificate/",
            data=json.dumps(
                {
                    "pfx_b64": base64.b64encode(pfx_bytes).decode("ascii"),
                    "pfx_password": "wrong-pass",
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 400
        # Error message hints at the most likely cause without
        # falsely confirming the file is corrupt.
        assert "password" in response.json()["detail"].lower()

    def test_post_pfx_bad_base64(self, authed) -> None:
        client, _, _ = authed
        response = client.post(
            "/api/v1/identity/organization/certificate/",
            data=json.dumps({"pfx_b64": "not!base64!", "pfx_password": "x"}),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "base64" in response.json()["detail"].lower()

    def test_post_neither_pfx_nor_pem(self, authed) -> None:
        client, _, _ = authed
        response = client.post(
            "/api/v1/identity/organization/certificate/",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 400
