"""Tests for the LHDN signing + submission pipeline (Slice 58).

Covers four layers:
  1. Self-signed cert generation + encrypted storage.
  2. UBL XML invoice generation.
  3. XML-DSig signing + verification round-trip.
  4. End-to-end orchestration with mocked LHDN HTTP.
"""

from __future__ import annotations

import base64
import json
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch
from xml.etree import ElementTree as ET

import httpx
import pytest

from apps.identity.models import (
    Organization,
    OrganizationMembership,
    Role,
    User,
)
from apps.submission import (
    certificates,
    lhdn_client,
    lhdn_submission,
    ubl_xml,
    xml_signature,
)
from apps.submission.models import Invoice, LineItem


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org(seeded) -> Organization:
    return Organization.objects.create(
        legal_name="Acme Sdn Bhd",
        tin="C1234567890",
        contact_email="ops@acme.example",
    )


@pytest.fixture
def invoice(org) -> Invoice:
    inv = Invoice.objects.create(
        organization=org,
        ingestion_job_id="11111111-1111-1111-1111-111111111111",
        invoice_number="INV-2026-0001",
        issue_date=date(2026, 4, 15),
        due_date=date(2026, 5, 15),
        currency_code="MYR",
        supplier_legal_name="Acme Sdn Bhd",
        supplier_tin="C1234567890",
        supplier_address="Level 5, KL Sentral, Kuala Lumpur",
        buyer_legal_name="Globex Bhd",
        buyer_tin="C9999999999",
        buyer_address="Level 10, Mid Valley, KL",
        buyer_country_code="MY",
        subtotal=Decimal("100.00"),
        total_tax=Decimal("8.00"),
        grand_total=Decimal("108.00"),
        status=Invoice.Status.READY_FOR_REVIEW,
    )
    LineItem.objects.create(
        organization=org,
        invoice=inv,
        line_number=1,
        description="Widget A",
        quantity=Decimal("10"),
        unit_price_excl_tax=Decimal("10.00"),
        line_subtotal_excl_tax=Decimal("100.00"),
        tax_amount=Decimal("8.00"),
        tax_rate=Decimal("8.00"),
        tax_type_code="01",
        line_total_incl_tax=Decimal("108.00"),
    )
    return inv


@pytest.fixture
def org_with_lhdn_creds(org, seeded) -> Organization:
    """Org + a populated LHDN integration."""
    user = User.objects.create_user(email="o@a", password="x")
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


# =============================================================================
# Layer 1: Certificate generation + storage
# =============================================================================


@pytest.mark.django_db
class TestCertificates:
    def test_first_call_mints_self_signed(self, org) -> None:
        loaded = certificates.ensure_certificate(organization_id=org.id)
        assert loaded.kind == "self_signed_dev"
        assert loaded.cert is not None
        # Org row was updated.
        org.refresh_from_db()
        assert org.certificate_uploaded is True
        assert org.certificate_kind == "self_signed_dev"
        assert org.certificate_pem.startswith("-----BEGIN CERTIFICATE-----")
        assert org.certificate_serial_hex
        assert org.certificate_expiry_date is not None

    def test_idempotent_reload(self, org) -> None:
        first = certificates.ensure_certificate(organization_id=org.id)
        second = certificates.ensure_certificate(organization_id=org.id)
        assert first.cert.serial_number == second.cert.serial_number

    def test_private_key_encrypted_at_rest(self, org) -> None:
        certificates.ensure_certificate(organization_id=org.id)
        org.refresh_from_db()
        # Stored value must be ciphertext, not raw PEM.
        assert "-----BEGIN PRIVATE KEY-----" not in (
            org.certificate_private_key_pem_encrypted or ""
        )
        assert org.certificate_private_key_pem_encrypted.startswith("enc1:")

    def test_audit_event_recorded(self, org) -> None:
        from apps.audit.models import AuditEvent

        certificates.ensure_certificate(organization_id=org.id)
        event = (
            AuditEvent.objects.filter(action_type="submission.cert.self_signed_minted")
            .order_by("-sequence")
            .first()
        )
        assert event is not None
        assert event.payload["kind"] == "self_signed_dev"
        # The PEM must NEVER appear in the audit chain.
        assert "BEGIN CERTIFICATE" not in json.dumps(event.payload)
        assert "BEGIN PRIVATE KEY" not in json.dumps(event.payload)


# =============================================================================
# Layer 2: UBL XML generation
# =============================================================================


@pytest.mark.django_db
class TestUblXml:
    def test_produces_valid_xml(self, invoice) -> None:
        xml_bytes = ubl_xml.build_invoice_xml(invoice)
        assert xml_bytes.startswith(b"<")
        # Parses cleanly.
        root = ET.fromstring(xml_bytes)
        assert root.tag.endswith("Invoice")

    def test_carries_invoice_number_and_dates(self, invoice) -> None:
        xml = ubl_xml.build_invoice_xml(invoice).decode("utf-8")
        assert "INV-2026-0001" in xml
        assert "2026-04-15" in xml
        assert "2026-05-15" in xml

    def test_carries_supplier_and_buyer_tin(self, invoice) -> None:
        xml = ubl_xml.build_invoice_xml(invoice).decode("utf-8")
        assert "C1234567890" in xml
        assert "C9999999999" in xml

    def test_carries_line_item_amounts(self, invoice) -> None:
        xml = ubl_xml.build_invoice_xml(invoice).decode("utf-8")
        assert "100.00" in xml
        assert "108.00" in xml
        assert "Widget A" in xml

    def test_currency_id_attribute_on_amounts(self, invoice) -> None:
        xml = ubl_xml.build_invoice_xml(invoice).decode("utf-8")
        assert 'currencyID="MYR"' in xml


# =============================================================================
# Layer 3: XML-DSig signing + verification
# =============================================================================


@pytest.mark.django_db
class TestXmlSignature:
    def test_signed_xml_includes_signature_element(self, org, invoice) -> None:
        cert = certificates.ensure_certificate(organization_id=org.id)
        unsigned = ubl_xml.build_invoice_xml(invoice)
        signed = xml_signature.sign_invoice_xml(xml_bytes=unsigned, certificate=cert)
        text = signed.decode("utf-8")
        assert "Signature" in text
        assert "SignatureValue" in text
        assert "X509Certificate" in text

    def test_signature_round_trips(self, org, invoice) -> None:
        cert = certificates.ensure_certificate(organization_id=org.id)
        unsigned = ubl_xml.build_invoice_xml(invoice)
        signed = xml_signature.sign_invoice_xml(xml_bytes=unsigned, certificate=cert)
        # The verifier reads the embedded cert from KeyInfo + checks
        # the RSA signature against the canonicalised SignedInfo.
        assert xml_signature.verify_invoice_signature(signed_xml_bytes=signed)

    def test_tampered_signature_fails_verification(self, org, invoice) -> None:
        cert = certificates.ensure_certificate(organization_id=org.id)
        unsigned = ubl_xml.build_invoice_xml(invoice)
        signed = xml_signature.sign_invoice_xml(xml_bytes=unsigned, certificate=cert)
        # Flip a byte INSIDE the SignatureValue base64 — tampering.
        text = signed.decode("utf-8")
        idx = text.find("<ds:SignatureValue>") + len("<ds:SignatureValue>")
        tampered = (text[:idx] + ("A" if text[idx] != "A" else "B") + text[idx + 1 :]).encode(
            "utf-8"
        )
        assert not xml_signature.verify_invoice_signature(signed_xml_bytes=tampered)


# =============================================================================
# Layer 4: LHDN client (mocked HTTP)
# =============================================================================


def _mock_response(status_code: int, body: dict | str | None = None) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    if isinstance(body, dict):
        resp.json = MagicMock(return_value=body)
        resp.text = json.dumps(body)
    else:
        resp.json = MagicMock(side_effect=ValueError("not json"))
        resp.text = body or ""
    return resp


@pytest.mark.django_db
class TestLhdnClient:
    def test_credentials_for_org(self, org_with_lhdn_creds) -> None:
        creds = lhdn_client.credentials_for_org(organization_id=org_with_lhdn_creds.id)
        assert creds.client_id == "demo-client"
        assert creds.client_secret == "demo-secret"
        assert creds.environment == "sandbox"

    def test_credentials_missing_raises(self, org) -> None:
        with pytest.raises(lhdn_client.LHDNError, match="not configured"):
            lhdn_client.credentials_for_org(organization_id=org.id)

    def test_get_access_token_caches(self, org_with_lhdn_creds) -> None:
        creds = lhdn_client.credentials_for_org(organization_id=org_with_lhdn_creds.id)
        # Reset cache for test isolation.
        lhdn_client._token_cache.clear()
        with patch(
            "apps.submission.lhdn_client.httpx.post",
            return_value=_mock_response(200, {"access_token": "abc123", "expires_in": 3600}),
        ) as posted:
            t1 = lhdn_client.get_access_token(creds)
            t2 = lhdn_client.get_access_token(creds)
        assert t1 == "abc123"
        assert t2 == "abc123"
        # Second call hit the cache, not the network.
        assert posted.call_count == 1

    def test_get_access_token_401_raises(self, org_with_lhdn_creds) -> None:
        creds = lhdn_client.credentials_for_org(organization_id=org_with_lhdn_creds.id)
        lhdn_client._token_cache.clear()
        with patch(
            "apps.submission.lhdn_client.httpx.post",
            return_value=_mock_response(401, {"error": "invalid_client"}),
        ):
            with pytest.raises(lhdn_client.LHDNAuthError):
                lhdn_client.get_access_token(creds)

    def test_submit_documents_validation_error(self, org_with_lhdn_creds) -> None:
        creds = lhdn_client.credentials_for_org(organization_id=org_with_lhdn_creds.id)
        lhdn_client._token_cache.clear()
        # Mock token + then a 400 on submit.
        with patch(
            "apps.submission.lhdn_client.httpx.post",
            side_effect=[
                _mock_response(200, {"access_token": "abc", "expires_in": 3600}),
                _mock_response(400, {"error": "schema_invalid"}),
            ],
        ):
            with pytest.raises(lhdn_client.LHDNValidationError):
                lhdn_client.submit_documents(
                    creds=creds,
                    signed_xml_documents=[{"document": "x"}],
                )


# =============================================================================
# Layer 5: End-to-end orchestration (mocked LHDN)
# =============================================================================


@pytest.mark.django_db
class TestLhdnSubmission:
    def test_sign_invoice_produces_signed_xml(self, org_with_lhdn_creds, invoice) -> None:
        result = lhdn_submission.sign_invoice(invoice.id)
        assert result["ok"] is True
        assert result["digest_hex"]
        signed = base64.b64decode(result["signed_xml_b64"])
        # Round-trip the signature.
        assert xml_signature.verify_invoice_signature(signed_xml_bytes=signed)

    def test_submit_invoice_flips_to_submitting_on_success(
        self, org_with_lhdn_creds, invoice
    ) -> None:
        lhdn_client._token_cache.clear()
        with patch(
            "apps.submission.lhdn_client.httpx.post",
            side_effect=[
                _mock_response(200, {"access_token": "tok", "expires_in": 3600}),
                _mock_response(
                    202,
                    {
                        "submissionUid": "submission-abc-123",
                        "acceptedDocuments": [
                            {"uuid": "lhdn-uuid-xyz", "invoiceCodeNumber": "INV-2026-0001"}
                        ],
                        "rejectedDocuments": [],
                    },
                ),
            ],
        ):
            result = lhdn_submission.submit_invoice_to_lhdn(invoice.id)
        assert result["ok"] is True
        assert result["submission_uid"] == "submission-abc-123"

        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.SUBMITTING
        assert invoice.submission_uid == "submission-abc-123"
        assert invoice.lhdn_uuid == "lhdn-uuid-xyz"

    def test_submit_invoice_lhdn_validation_rejection(self, org_with_lhdn_creds, invoice) -> None:
        lhdn_client._token_cache.clear()
        with patch(
            "apps.submission.lhdn_client.httpx.post",
            side_effect=[
                _mock_response(200, {"access_token": "tok", "expires_in": 3600}),
                _mock_response(
                    400,
                    {"errors": [{"code": "BadStructure", "message": "missing TaxAmount"}]},
                ),
            ],
        ):
            result = lhdn_submission.submit_invoice_to_lhdn(invoice.id)
        assert result["ok"] is False
        assert result["reason"] == "lhdn_rejected"

        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.REJECTED
        assert "rejected" in invoice.error_message.lower()

    def test_poll_invoice_status_marks_validated(self, org_with_lhdn_creds, invoice) -> None:
        # Simulate a prior submission that captured the submission UID.
        invoice.submission_uid = "sub-xyz"
        invoice.status = Invoice.Status.SUBMITTING
        invoice.save()

        lhdn_client._token_cache.clear()
        with (
            patch(
                "apps.submission.lhdn_client.httpx.post",
                return_value=_mock_response(200, {"access_token": "tok", "expires_in": 3600}),
            ),
            patch(
                "apps.submission.lhdn_client.httpx.get",
                side_effect=[
                    _mock_response(
                        200,
                        {
                            "submissionUid": "sub-xyz",
                            "overallStatus": "Valid",
                            "documentSummary": [
                                {
                                    "uuid": "doc-uuid-001",
                                    "status": "Valid",
                                    "invoiceCodeNumber": "INV-2026-0001",
                                }
                            ],
                        },
                    ),
                    _mock_response(
                        200,
                        {"longId": "lookup/doc-uuid-001"},
                    ),
                ],
            ),
        ):
            result = lhdn_submission.poll_invoice_status(invoice.id)

        assert result["ok"] is True
        assert result["document_status"] == "Valid"

        invoice.refresh_from_db()
        assert invoice.status == Invoice.Status.VALIDATED
        assert invoice.lhdn_uuid == "doc-uuid-001"
        # QR URL points at the PORTAL host, not the API host (Slice
        # 58 follow-up — LHDN's longId is a portal verification slug).
        assert invoice.lhdn_qr_code_url
        assert "preprod.myinvois.hasil.gov.my" in invoice.lhdn_qr_code_url
        assert "preprod-api.myinvois.hasil.gov.my" not in invoice.lhdn_qr_code_url
        assert "lookup/doc-uuid-001" in invoice.lhdn_qr_code_url


# =============================================================================
# Test that the OAuth2 tester (Slice 57 swap) actually authenticates
# =============================================================================


@pytest.mark.django_db
class TestOauthTester:
    def test_real_oauth_call_on_test_connection(self, org_with_lhdn_creds) -> None:
        from apps.identity.integrations import test_connection

        with patch(
            "apps.identity.integrations.httpx.post",
            return_value=_mock_response(200, {"access_token": "fresh-token", "expires_in": 3600}),
        ) as posted:
            outcome = test_connection(
                organization_id=org_with_lhdn_creds.id,
                integration_key="lhdn_myinvois",
                environment="sandbox",
                actor_user_id="00000000-0000-0000-0000-000000000000",
            )
        assert outcome.ok is True
        # The tester actually hit /connect/token (not just a HEAD).
        called_url = posted.call_args[0][0]
        assert "/connect/token" in called_url

    def test_oauth_failure_surfaces_error_code(self, org_with_lhdn_creds) -> None:
        from apps.identity.integrations import test_connection

        with patch(
            "apps.identity.integrations.httpx.post",
            return_value=_mock_response(401, {"error": "invalid_client"}),
        ):
            outcome = test_connection(
                organization_id=org_with_lhdn_creds.id,
                integration_key="lhdn_myinvois",
                environment="sandbox",
                actor_user_id="00000000-0000-0000-0000-000000000000",
            )
        assert outcome.ok is False
        assert "invalid_client" in outcome.detail
