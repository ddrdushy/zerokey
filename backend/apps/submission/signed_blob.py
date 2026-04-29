"""Signed-document at-rest persistence (Slice 84).

What this is for
----------------

Once LHDN accepts a submission, the signed bytes ZeroKey put on the
wire are the canonical artefact for that invoice. Auditors,
disputes, and the customer's own records all want to be able to
re-fetch them later. We persist them to S3 — encrypted at rest with
the platform's envelope encryption — and stash the key on
``Invoice.signed_xml_s3_key`` (yes, the column name says XML — it
also stores JSON-path bytes; see the wrapper format below).

Storage shape
-------------

The stored object is a small JSON envelope, NOT the raw signed
bytes. The envelope carries:

  - ``v``: schema version (currently ``1``).
  - ``format``: ``"xml"`` (enveloped XML-DSig) or ``"json"`` (UBL
    JSON the JSON-path submitted to LHDN).
  - ``digest_sha256``: the SHA-256 of the *plaintext* signed
    bytes, hex-encoded. The same digest LHDN saw on
    ``documentHash``. Stored separately so a chain reader can
    verify integrity without decrypting.
  - ``encrypted_b64``: Fernet ciphertext (AES-128-CBC + HMAC-
    SHA-256), base64-encoded, of the signed bytes. The same
    ``apps.administration.crypto`` envelope used elsewhere; a
    KMS swap would replace ``crypto._dek()`` and this module
    would not change.
  - ``written_at``: ISO-8601 timestamp.

The envelope is small (a few KB max for typical invoices) so we
write it as a single S3 object. Larger documents would justify
splitting the ciphertext into a sibling key and only storing the
envelope metadata; not needed today.

Why JSON envelope instead of raw ciphertext
-------------------------------------------

  - The plaintext digest and the format tag are operational
    metadata an audit reader needs without decrypting (e.g. "is
    this still valid against the LHDN documentHash?"). Putting
    them next to the ciphertext keeps the round-trip atomic.
  - Schema versioning at the file level means we can rotate the
    envelope without a database migration.
  - The mime type stays ``application/json`` regardless of
    document format so the bucket policy doesn't need a
    per-format rule.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import uuid
from io import BytesIO

from django.conf import settings
from django.utils import timezone

from apps.administration.crypto import decrypt_value, encrypt_value
from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.integrations import storage

from .models import Invoice

logger = logging.getLogger(__name__)


CURRENT_SCHEMA_VERSION = 1


class SignedBlobError(Exception):
    """Raised when a signed blob can't be persisted or retrieved."""


def _envelope_bytes(*, signed_bytes: bytes, format: str) -> tuple[bytes, str]:
    """Build the envelope JSON for the given plaintext signed bytes.

    Returns ``(envelope_bytes, plaintext_digest_hex)``.
    """
    digest_hex = hashlib.sha256(signed_bytes).hexdigest()
    # Encrypt as base64 ASCII so the envelope is JSON-safe.
    plaintext_b64 = base64.b64encode(signed_bytes).decode("ascii")
    encrypted_marker = encrypt_value(plaintext_b64)
    envelope = {
        "v": CURRENT_SCHEMA_VERSION,
        "format": format,
        "digest_sha256": digest_hex,
        "encrypted_b64": encrypted_marker,
        "written_at": timezone.now().isoformat(),
    }
    return json.dumps(envelope, separators=(",", ":")).encode("utf-8"), digest_hex


def persist_signed_bytes(
    *,
    invoice_id: uuid.UUID | str,
    signed_bytes: bytes,
    format: str,
) -> str:
    """Encrypt + store the signed bytes for an invoice; return the S3 key.

    Idempotent within a submission: re-persisting overwrites the
    object at the same key. The audit chain still records every
    write, so a re-submission shows up as a second
    ``submission.signed_blob.persisted`` event.

    ``format`` must be ``"xml"`` or ``"json"`` — the document
    format that was put on the wire to LHDN.
    """
    if format not in ("xml", "json"):
        raise SignedBlobError(f"format must be 'xml' or 'json', got {format!r}")

    invoice = Invoice.objects.filter(id=invoice_id).first()
    if invoice is None:
        raise SignedBlobError(f"Invoice {invoice_id} not found.")

    envelope_bytes, digest_hex = _envelope_bytes(signed_bytes=signed_bytes, format=format)

    object_key = storage.signed_invoice_key(
        organization_id=invoice.organization_id,
        invoice_id=invoice.id,
    )
    try:
        storage.put_object(
            bucket=settings.S3_BUCKET_SIGNED,
            key=object_key,
            body=BytesIO(envelope_bytes),
            content_type="application/json",
        )
    except storage.StorageError as exc:
        # We don't want a storage failure to fail the submission —
        # LHDN already accepted the document. Log + audit the miss
        # so an operator can backfill from the LHDN copy if needed.
        logger.exception("submission.signed_blob.persist_failed")
        record_event(
            action_type="submission.signed_blob.persist_failed",
            actor_type=AuditEvent.ActorType.SERVICE,
            actor_id="submission.signed_blob",
            organization_id=str(invoice.organization_id),
            affected_entity_type="Invoice",
            affected_entity_id=str(invoice.id),
            payload={
                "format": format,
                "digest_sha256": digest_hex,
                "error_class": type(exc).__name__,
            },
        )
        return ""

    # Stash the key on the Invoice so future reads find it.
    invoice.signed_xml_s3_key = object_key
    invoice.save(update_fields=["signed_xml_s3_key", "updated_at"])

    record_event(
        action_type="submission.signed_blob.persisted",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="submission.signed_blob",
        organization_id=str(invoice.organization_id),
        affected_entity_type="Invoice",
        affected_entity_id=str(invoice.id),
        payload={
            "format": format,
            # Plaintext digest only — the ciphertext is opaque to
            # the audit chain by design.
            "digest_sha256": digest_hex,
            "byte_length": len(signed_bytes),
            "s3_object_key": object_key,
        },
    )
    return object_key


def fetch_signed_bytes(*, invoice_id: uuid.UUID | str) -> dict:
    """Re-read + decrypt the signed bytes for an invoice.

    Returns a dict::

        {
            "format": "xml" | "json",
            "digest_sha256": "<hex>",
            "signed_bytes": <bytes>,
            "written_at": "<iso8601>",
        }

    Raises ``SignedBlobError`` if the invoice has no stored blob,
    or if the envelope is unreadable. The decrypt itself fails
    closed — a corrupted envelope returns the error rather than
    silent garbage.
    """
    invoice = Invoice.objects.filter(id=invoice_id).first()
    if invoice is None:
        raise SignedBlobError(f"Invoice {invoice_id} not found.")
    key = invoice.signed_xml_s3_key
    if not key:
        raise SignedBlobError(f"Invoice {invoice.id} has no signed-blob key on file.")

    try:
        envelope_bytes = storage.get_object_bytes(
            bucket=settings.S3_BUCKET_SIGNED,
            key=key,
        )
    except storage.StorageError as exc:
        raise SignedBlobError(f"failed to read signed blob: {exc}") from exc

    try:
        envelope = json.loads(envelope_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SignedBlobError(f"signed-blob envelope is malformed: {exc}") from exc

    if envelope.get("v") != CURRENT_SCHEMA_VERSION:
        raise SignedBlobError(f"unknown envelope schema {envelope.get('v')!r}")

    plaintext_b64 = decrypt_value(envelope.get("encrypted_b64") or "")
    if not plaintext_b64:
        raise SignedBlobError("signed-blob ciphertext could not be decrypted.")

    try:
        signed_bytes = base64.b64decode(plaintext_b64.encode("ascii"))
    except (ValueError, base64.binascii.Error) as exc:
        raise SignedBlobError(f"signed-blob plaintext base64 invalid: {exc}") from exc

    expected_digest = envelope.get("digest_sha256") or ""
    actual_digest = hashlib.sha256(signed_bytes).hexdigest()
    if expected_digest and expected_digest != actual_digest:
        # Tamper / corruption signal. Don't return the bytes —
        # audit + raise so the caller knows the chain is broken.
        record_event(
            action_type="submission.signed_blob.digest_mismatch",
            actor_type=AuditEvent.ActorType.SERVICE,
            actor_id="submission.signed_blob",
            organization_id=str(invoice.organization_id),
            affected_entity_type="Invoice",
            affected_entity_id=str(invoice.id),
            payload={
                "expected_digest": expected_digest,
                "actual_digest": actual_digest,
                "s3_object_key": key,
            },
        )
        raise SignedBlobError(
            f"signed-blob digest mismatch — stored {expected_digest!r}, recomputed {actual_digest!r}"
        )

    return {
        "format": envelope.get("format") or "",
        "digest_sha256": actual_digest,
        "signed_bytes": signed_bytes,
        "written_at": envelope.get("written_at") or "",
    }
