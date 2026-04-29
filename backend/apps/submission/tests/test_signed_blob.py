"""Tests for the signed-document at-rest envelope (Slice 84)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.audit.models import AuditEvent
from apps.identity.models import Organization, Role
from apps.submission import signed_blob
from apps.submission.models import Invoice


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
    return Invoice.objects.create(
        organization=org,
        ingestion_job_id="11111111-1111-1111-1111-111111111111",
        invoice_number="INV-2026-0001",
        issue_date=date(2026, 4, 15),
        currency_code="MYR",
        supplier_legal_name="Acme Sdn Bhd",
        supplier_tin="C1234567890",
        buyer_legal_name="Globex Bhd",
        buyer_tin="C9999999999",
        subtotal=Decimal("100.00"),
        total_tax=Decimal("8.00"),
        grand_total=Decimal("108.00"),
        status=Invoice.Status.SUBMITTING,
    )


# Lightweight S3 stub: in-memory dict keyed by (bucket, key).
class _FakeS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object_stub(self, *, bucket, key, body, content_type):
        from apps.integrations.storage import StoredObject

        if hasattr(body, "read"):
            data = body.read()
        else:
            data = body
        self.objects[(bucket, key)] = data
        return StoredObject(bucket=bucket, key=key, size=len(data), content_type=content_type)

    def get_object_bytes_stub(self, *, bucket, key):
        return self.objects[(bucket, key)]


@pytest.fixture
def fake_s3() -> _FakeS3:
    s3 = _FakeS3()
    with (
        patch("apps.integrations.storage.put_object", side_effect=s3.put_object_stub),
        patch(
            "apps.integrations.storage.get_object_bytes",
            side_effect=lambda *, bucket, key: s3.get_object_bytes_stub(bucket=bucket, key=key),
        ),
    ):
        yield s3


@pytest.mark.django_db
class TestPersist:
    def test_xml_path_persists_envelope(self, invoice, fake_s3) -> None:
        signed = b"<Invoice xmlns='ubl'><Sig>FAKE</Sig></Invoice>"
        key = signed_blob.persist_signed_bytes(
            invoice_id=invoice.id, signed_bytes=signed, format="xml"
        )
        assert key

        # Envelope is parseable JSON, NOT raw XML.
        envelope_bytes = next(iter(fake_s3.objects.values()))
        envelope = json.loads(envelope_bytes)
        assert envelope["v"] == 1
        assert envelope["format"] == "xml"
        assert envelope["digest_sha256"]
        assert envelope["encrypted_b64"].startswith("enc1:")
        # The plaintext bytes never appear in the envelope.
        assert b"FAKE" not in envelope_bytes

    def test_invoice_row_gets_key(self, invoice, fake_s3) -> None:
        signed_blob.persist_signed_bytes(invoice_id=invoice.id, signed_bytes=b"abc", format="json")
        invoice.refresh_from_db()
        assert invoice.signed_xml_s3_key

    def test_audit_event_records_digest(self, invoice, fake_s3) -> None:
        signed_blob.persist_signed_bytes(
            invoice_id=invoice.id, signed_bytes=b"hello world", format="json"
        )
        ev = AuditEvent.objects.filter(action_type="submission.signed_blob.persisted").first()
        assert ev is not None
        # Digest matches sha256 of the bytes.
        import hashlib

        assert ev.payload["digest_sha256"] == hashlib.sha256(b"hello world").hexdigest()
        assert ev.payload["format"] == "json"
        assert ev.payload["byte_length"] == len(b"hello world")

    def test_invalid_format_rejected(self, invoice) -> None:
        with pytest.raises(signed_blob.SignedBlobError, match="format must be"):
            signed_blob.persist_signed_bytes(invoice_id=invoice.id, signed_bytes=b"x", format="csv")

    def test_storage_failure_audits_and_returns_empty(self, invoice) -> None:
        from apps.integrations.storage import StorageError

        with patch(
            "apps.integrations.storage.put_object",
            side_effect=StorageError("simulated outage"),
        ):
            key = signed_blob.persist_signed_bytes(
                invoice_id=invoice.id, signed_bytes=b"x", format="xml"
            )
        assert key == ""
        # Failure was audited so an operator can backfill.
        ev = AuditEvent.objects.filter(action_type="submission.signed_blob.persist_failed").first()
        assert ev is not None


@pytest.mark.django_db
class TestFetch:
    def test_round_trip_xml(self, invoice, fake_s3) -> None:
        plaintext = b"<Invoice>signed payload</Invoice>"
        signed_blob.persist_signed_bytes(
            invoice_id=invoice.id, signed_bytes=plaintext, format="xml"
        )

        result = signed_blob.fetch_signed_bytes(invoice_id=invoice.id)
        assert result["signed_bytes"] == plaintext
        assert result["format"] == "xml"
        # The digest in the envelope matches the recomputed digest.
        import hashlib

        assert result["digest_sha256"] == hashlib.sha256(plaintext).hexdigest()

    def test_round_trip_json(self, invoice, fake_s3) -> None:
        plaintext = b'{"_D": "Invoice", "ID": "INV-001"}'
        signed_blob.persist_signed_bytes(
            invoice_id=invoice.id, signed_bytes=plaintext, format="json"
        )
        result = signed_blob.fetch_signed_bytes(invoice_id=invoice.id)
        assert result["signed_bytes"] == plaintext
        assert result["format"] == "json"

    def test_no_blob_on_file_raises(self, invoice) -> None:
        with pytest.raises(signed_blob.SignedBlobError, match="no signed-blob key"):
            signed_blob.fetch_signed_bytes(invoice_id=invoice.id)

    def test_digest_mismatch_audits_and_raises(self, invoice, fake_s3) -> None:
        # Persist normally, then corrupt the stored envelope so the
        # digest no longer matches the decrypted plaintext.
        plaintext = b"original"
        signed_blob.persist_signed_bytes(
            invoice_id=invoice.id, signed_bytes=plaintext, format="json"
        )
        bucket_key = next(iter(fake_s3.objects.keys()))
        envelope = json.loads(fake_s3.objects[bucket_key])
        envelope["digest_sha256"] = "00" * 32  # bogus digest
        fake_s3.objects[bucket_key] = json.dumps(envelope).encode("utf-8")

        with pytest.raises(signed_blob.SignedBlobError, match="digest mismatch"):
            signed_blob.fetch_signed_bytes(invoice_id=invoice.id)
        # The mismatch is audited so chain integrity is observable.
        assert AuditEvent.objects.filter(
            action_type="submission.signed_blob.digest_mismatch"
        ).exists()
