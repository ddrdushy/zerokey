"""WhatsApp ingestion (Slice 82).

Customers send invoice PDFs and images to a WhatsApp Business number
ZeroKey hosts on their behalf. Meta's Cloud API POSTs each inbound
message to our webhook; we:

  1. Verify the inbound webhook (GET subscribe challenge + POST
     ``X-Hub-Signature-256`` HMAC, both gated on platform-level
     SystemSetting secrets).
  2. Look up the tenant by ``phone_number_id`` (the per-customer
     business-number identifier carried on every inbound event).
  3. For each media message (document/image), fetch the bytes from
     Meta's media API + create one IngestionJob — exactly the same
     downstream pipeline as web upload + email forward.
  4. Audit the inbound + the per-attachment jobs.

This module is *intentionally* shaped like ``email_forward``: a
provider-agnostic core (``InboundWhatsAppMessage`` →
``process_inbound_whatsapp_message``) plus a thin Meta-Cloud-API
adapter that parses the webhook JSON. The two channels share the
same ``IngestionJob`` shape, so the review UI doesn't need to
care which channel a job came from.

Configuration (set by super-admin once the WhatsApp Business App
is provisioned):
  - ``Organization.whatsapp_phone_number_id`` — the per-tenant
    routing key (the customer's Cloud API phone-number id).
  - SystemSetting ``whatsapp.verify_token`` — the random string
    Meta echoes during the subscription handshake.
  - SystemSetting ``whatsapp.app_secret`` — the App Secret used
    to verify ``X-Hub-Signature-256`` on inbound POSTs.
  - SystemSetting ``whatsapp.access_token`` — the Cloud API
    bearer token used to fetch media bytes by id.

Until the super-admin completes that configuration, the webhook
returns 401 (verify) / 503 (events) so the platform fails closed
instead of silently dropping messages.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from io import BytesIO

from django.conf import settings

from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.identity.models import Organization
from apps.identity.tenancy import super_admin_context
from apps.integrations import storage

from .models import IngestionJob

logger = logging.getLogger(__name__)


# Allowed inbound media types — invoice channels only. WhatsApp also
# delivers audio/video/sticker types we explicitly drop.
ALLOWED_INBOUND_MIMES = frozenset(
    {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/webp",
    }
)

MAX_INBOUND_MEDIA_BYTES = 25 * 1024 * 1024  # 25 MB / media — matches web upload + email
MAX_INBOUND_ATTACHMENTS = 10  # per webhook payload (Meta batches)


class WhatsAppForwardError(Exception):
    """Raised when an inbound WhatsApp message can't be processed."""


class PhoneNumberNotFoundError(WhatsAppForwardError):
    """``phone_number_id`` didn't match any known organization."""


class WhatsAppNotConfiguredError(WhatsAppForwardError):
    """Platform-level WhatsApp secret is not configured yet."""


@dataclass
class InboundWhatsAppAttachment:
    """One media item pulled out of an inbound WhatsApp message."""

    filename: str
    mime_type: str
    body: bytes
    media_id: str = ""  # Meta's media id (for audit + dedup)


@dataclass
class InboundWhatsAppMessage:
    """Provider-agnostic shape after the Meta adapter parses the POST."""

    sender: str  # the sender's E.164 phone (no '+')
    message_id: str  # Meta's ``wamid.*`` id, for dedup + audit
    phone_number_id: str  # tenant routing key
    timestamp: str = ""  # Meta sends a unix-seconds string
    attachments: list[InboundWhatsAppAttachment] = field(default_factory=list)


# --- Tenant resolution -----------------------------------------------------


def resolve_tenant_from_phone_number_id(phone_number_id: str) -> uuid.UUID:
    """Map a Cloud-API ``phone_number_id`` to an Organization id."""
    if not phone_number_id:
        raise PhoneNumberNotFoundError("No phone_number_id on inbound message.")
    with super_admin_context(reason="ingestion.whatsapp.resolve"):
        org = Organization.objects.filter(whatsapp_phone_number_id=phone_number_id).first()
    if org is None:
        raise PhoneNumberNotFoundError(
            f"No organization registered for phone_number_id {phone_number_id!r}."
        )
    return org.id


# --- Inbound processing -----------------------------------------------------


def process_inbound_whatsapp_message(message: InboundWhatsAppMessage) -> dict:
    """Receive an inbound WhatsApp message + create one IngestionJob per media item.

    Mirrors ``email_forward.process_inbound_email`` so the two
    channels share the audit + job-creation shape.
    """
    if not message.attachments:
        # Plain text or unsupported type — ack so Meta doesn't retry.
        # Audit the empty so operators see the no-media forwards
        # (often "thanks!" replies after an invoice was processed).
        record_event(
            action_type="ingestion.whatsapp.empty",
            actor_type=AuditEvent.ActorType.SERVICE,
            actor_id="ingestion.whatsapp",
            organization_id=None,
            affected_entity_type="WhatsAppMessage",
            affected_entity_id=message.message_id[:64] or "",
            payload={
                "phone_number_id": message.phone_number_id,
                "sender": _redact_phone(message.sender),
            },
        )
        return {
            "organization_id": None,
            "jobs_created": 0,
            "skipped": 0,
            "message_id": message.message_id,
            "reason": "no-media",
        }

    organization_id = resolve_tenant_from_phone_number_id(message.phone_number_id)

    if len(message.attachments) > MAX_INBOUND_ATTACHMENTS:
        raise WhatsAppForwardError(
            f"Too many attachments: {len(message.attachments)} (max {MAX_INBOUND_ATTACHMENTS})."
        )

    jobs_created: list[uuid.UUID] = []
    skipped: list[dict] = []

    for attachment in message.attachments:
        if len(attachment.body) > MAX_INBOUND_MEDIA_BYTES:
            skipped.append({"filename": attachment.filename, "reason": "too_large"})
            continue
        if attachment.mime_type not in ALLOWED_INBOUND_MIMES:
            skipped.append(
                {
                    "filename": attachment.filename,
                    "reason": f"mime_type:{attachment.mime_type}",
                }
            )
            continue
        try:
            job = _create_whatsapp_job(
                organization_id=organization_id,
                attachment=attachment,
                message=message,
            )
            jobs_created.append(job.id)
        except Exception as exc:
            logger.exception(
                "ingestion.whatsapp.attachment_failed",
                extra={
                    "filename": attachment.filename,
                    "error_class": type(exc).__name__,
                },
            )
            skipped.append(
                {
                    "filename": attachment.filename,
                    "reason": f"error:{type(exc).__name__}",
                }
            )

    record_event(
        action_type="ingestion.whatsapp.processed",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="ingestion.whatsapp",
        organization_id=str(organization_id),
        affected_entity_type="WhatsAppMessage",
        affected_entity_id=message.message_id[:64] or "",
        payload={
            "phone_number_id": message.phone_number_id,
            "sender": _redact_phone(message.sender),
            "attachments_received": len(message.attachments),
            "jobs_created": len(jobs_created),
            "skipped": skipped,
        },
    )

    return {
        "organization_id": str(organization_id),
        "jobs_created": [str(j) for j in jobs_created],
        "skipped": skipped,
        "message_id": message.message_id,
    }


def _create_whatsapp_job(
    *,
    organization_id: uuid.UUID,
    attachment: InboundWhatsAppAttachment,
    message: InboundWhatsAppMessage,
) -> IngestionJob:
    """Persist one media item to S3 + create the IngestionJob row."""
    job_id = uuid.uuid4()
    object_key = storage.ingestion_object_key(
        organization_id=organization_id,
        job_id=job_id,
        filename=attachment.filename,
    )
    stored = storage.put_object(
        bucket=settings.S3_BUCKET_UPLOADS,
        key=object_key,
        body=BytesIO(attachment.body),
        content_type=attachment.mime_type,
    )

    from django.utils import timezone as _tz

    with super_admin_context(reason="ingestion.whatsapp.create_job"):
        job = IngestionJob.objects.create(
            id=job_id,
            organization_id=organization_id,
            source_channel=IngestionJob.SourceChannel.WHATSAPP,
            # Carry the wamid so duplicate webhooks (Meta retries
            # aggressively if we 5xx) collapse on the indexed
            # source_identifier column.
            source_identifier=message.message_id[:255],
            original_filename=attachment.filename,
            file_size=stored.size,
            file_mime_type=stored.content_type,
            s3_object_key=object_key,
            status=IngestionJob.Status.RECEIVED,
            state_transitions=[
                {
                    "status": IngestionJob.Status.RECEIVED.value,
                    "at": _tz.now().isoformat(),
                }
            ],
        )

    record_event(
        action_type="ingestion.job.received",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="ingestion.whatsapp",
        organization_id=str(organization_id),
        affected_entity_type="IngestionJob",
        affected_entity_id=str(job.id),
        payload={
            "source_channel": IngestionJob.SourceChannel.WHATSAPP.value,
            "original_filename": attachment.filename,
            "file_size": stored.size,
            "file_mime_type": stored.content_type,
            "s3_object_key": object_key,
            "sender": _redact_phone(message.sender),
            "message_id": message.message_id[:64],
            "media_id": attachment.media_id[:64],
        },
    )

    from django.db import transaction as _txn

    from apps.extraction.tasks import extract_invoice

    _txn.on_commit(lambda: extract_invoice.delay(str(job.id)))
    return job


# --- Meta Cloud API adapter -------------------------------------------------


# Type alias: the function the webhook layer injects to fetch media
# bytes from Meta. Keeping it injectable makes the adapter unit-
# testable without touching the network.
MediaFetcher = Callable[[str], tuple[bytes, str, str]]
"""Callable ``(media_id) -> (body_bytes, mime_type, filename_hint)``.

Implementations call Meta's media endpoint
(``GET /v17.0/{media_id}`` → URL → GET URL with bearer auth).
Tests pass a stub returning canned bytes.
"""


# Meta delivers messages with these top-level types. Anything else
# (text/audio/video/sticker/location/contacts/...) is dropped at the
# parser layer with a "skipped" reason so the audit chain shows it.
_MEDIA_TYPES = frozenset({"document", "image"})


def parse_meta_webhook_payload(
    body: dict, *, media_fetcher: MediaFetcher
) -> list[InboundWhatsAppMessage]:
    """Parse Meta Cloud API's webhook JSON into ``InboundWhatsAppMessage``s.

    Meta batches multiple messages per POST, nested under
    ``entry[].changes[].value.messages[]``. Each entry can carry
    a different ``phone_number_id`` (the platform may host more
    than one customer number on the same App), so we surface one
    ``InboundWhatsAppMessage`` per top-level message.

    For media messages we call ``media_fetcher(media_id)`` to pull
    the bytes; for unsupported types we yield the message with an
    empty attachments list so ``process_inbound_whatsapp_message``
    audits the no-media outcome consistently.
    """
    messages: list[InboundWhatsAppMessage] = []
    for entry in body.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value") or {}
            if not isinstance(value, dict):
                continue
            metadata = value.get("metadata") or {}
            phone_number_id = str(metadata.get("phone_number_id") or "")
            for raw in value.get("messages") or []:
                if not isinstance(raw, dict):
                    continue
                attachments: list[InboundWhatsAppAttachment] = []
                msg_type = str(raw.get("type") or "")
                if msg_type in _MEDIA_TYPES:
                    media = raw.get(msg_type) or {}
                    if isinstance(media, dict) and media.get("id"):
                        media_id = str(media.get("id"))
                        declared_mime = str(media.get("mime_type") or "")
                        declared_name = str(media.get("filename") or "")
                        try:
                            body_bytes, fetched_mime, name_hint = media_fetcher(media_id)
                        except Exception:
                            # Fetch failed — emit the message with no
                            # attachments so the audit chain shows
                            # the empty outcome. Don't drop the
                            # message entirely (Meta won't retry).
                            logger.exception(
                                "ingestion.whatsapp.media_fetch_failed",
                                extra={"media_id": media_id[:64]},
                            )
                        else:
                            attachments.append(
                                InboundWhatsAppAttachment(
                                    filename=declared_name or name_hint or f"{media_id}.bin",
                                    mime_type=declared_mime
                                    or fetched_mime
                                    or "application/octet-stream",
                                    body=body_bytes,
                                    media_id=media_id,
                                )
                            )
                messages.append(
                    InboundWhatsAppMessage(
                        sender=str(raw.get("from") or ""),
                        message_id=str(raw.get("id") or ""),
                        phone_number_id=phone_number_id,
                        timestamp=str(raw.get("timestamp") or ""),
                        attachments=attachments,
                    )
                )
    return messages


# --- Webhook signature verification ----------------------------------------


def verify_meta_signature(*, app_secret: str, body: bytes, signature_header: str) -> bool:
    """Verify Meta's ``X-Hub-Signature-256`` header.

    Header format: ``sha256=<hexdigest>``. Empty secret or empty
    header fails closed.
    """
    if not app_secret or not signature_header:
        return False
    if not signature_header.startswith("sha256="):
        return False
    presented = signature_header.removeprefix("sha256=").strip()
    expected = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, presented)


# --- Helpers ----------------------------------------------------------------


def _redact_phone(phone: str) -> str:
    """Mask the trailing digits of a phone number for audit safety.

    Keeps country/area-code shape (first 4 chars) so an operator
    can spot duplicates / regional patterns without seeing the
    full subscriber number.
    """
    if not phone:
        return "***"
    if len(phone) <= 4:
        return "*" * len(phone)
    return f"{phone[:4]}{'*' * (len(phone) - 4)}"
