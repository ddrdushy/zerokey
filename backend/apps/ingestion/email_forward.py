"""Email-forward ingestion (Slice 64).

Customers forward invoice emails to a magic per-tenant address
``invoices+<tenant-token>@inbox.zerokey.symprio.com``. The email
provider (AWS SES, Mailgun, Postmark, SendGrid — they all
support inbound parse) POSTs the parsed message to our webhook
with attachments base64-encoded. We:

  1. Verify the inbound webhook (HMAC signature OR shared
     bearer secret, depending on provider).
  2. Look up the tenant by the recipient address's per-tenant
     token (``invoices+<token>@inbox....``).
  3. For each PDF/image attachment, create one IngestionJob
     just like a web upload, kicking off the same extraction
     pipeline.
  4. Audit the inbound + the per-attachment jobs.

This module is provider-agnostic — the view just receives a
parsed dict + attachments list. ``MailgunInbound`` is a thin
adapter from Mailgun's POST format; other providers get
their own adapter as we add them.

Address shape:
  invoices+<INBOX_TOKEN>@inbox.zerokey.symprio.com

The INBOX_TOKEN is a 16-char URL-safe slug stored on the
Organization (added in the migration shipped with this slice).
Owners can rotate it from Settings — the old token stops
working immediately + emails to the old address bounce with a
"forwarded too late, please use your current address" reply
(future polish).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import uuid
from dataclasses import dataclass
from io import BytesIO

from django.conf import settings

from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.identity.models import Organization
from apps.identity.tenancy import super_admin_context
from apps.integrations import storage

from .models import IngestionJob

logger = logging.getLogger(__name__)


INBOX_DOMAIN = "inbox.zerokey.symprio.com"

# Allowed inbound attachment types — same allowlist the web
# upload path uses + a couple of email-specific oddities (some
# scanners send PDF as application/octet-stream).
ALLOWED_INBOUND_MIMES = frozenset(
    {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/tiff",
        "image/webp",
        "application/octet-stream",
    }
)

MAX_INBOUND_ATTACHMENT_BYTES = 25 * 1024 * 1024  # 25 MB / attachment
MAX_INBOUND_ATTACHMENTS = 10  # per email


class EmailForwardError(Exception):
    """Raised when an inbound email can't be processed."""


class InboxNotFoundError(EmailForwardError):
    """Recipient address didn't match any known organization."""


@dataclass
class InboundAttachment:
    """One file pulled out of an inbound email."""

    filename: str
    mime_type: str
    body: bytes


@dataclass
class InboundEmail:
    """Provider-agnostic shape after the adapter parses the POST."""

    to: str  # full recipient address
    sender: str  # the From: address
    subject: str
    message_id: str  # for dedup + audit correlation
    attachments: list[InboundAttachment]


# --- Tenant resolution -----------------------------------------------------


_TOKEN_RE = re.compile(r"^invoices\+([A-Za-z0-9_-]{8,32})@", re.IGNORECASE)


def resolve_tenant_from_address(address: str) -> uuid.UUID:
    """Map an inbound ``To:`` address to an Organization id.

    Format: ``invoices+<token>@inbox.zerokey.symprio.com``. The
    token is matched against ``Organization.inbox_token``.
    """
    if not address:
        raise InboxNotFoundError("No recipient address.")
    match = _TOKEN_RE.match(address.strip())
    if not match:
        raise InboxNotFoundError(f"Recipient {address!r} doesn't match the inbox-address pattern.")
    token = match.group(1)
    with super_admin_context(reason="ingestion.email_forward.resolve"):
        org = Organization.objects.filter(inbox_token=token).first()
    if org is None:
        raise InboxNotFoundError(f"No organization registered for inbox token {token!r}.")
    return org.id


# --- Inbound processing -----------------------------------------------------


def process_inbound_email(email: InboundEmail) -> dict:
    """Receive an inbound email + create one IngestionJob per attachment.

    Returns ``{"organization_id", "jobs_created", "skipped",
    "message_id"}``. The view caller returns this body to the
    email provider for log enrichment.
    """
    if not email.attachments:
        # No attachments — nothing to ingest, but we ack so the
        # provider doesn't retry. Audit so operators see the empty
        # forwards (often spam or replies to system mail).
        record_event(
            action_type="ingestion.email_forward.empty",
            actor_type=AuditEvent.ActorType.SERVICE,
            actor_id="ingestion.email_forward",
            organization_id=None,
            affected_entity_type="EmailForward",
            affected_entity_id=email.message_id[:64] or "",
            payload={
                "to": email.to,
                "sender": _redact_email(email.sender),
                "subject": email.subject[:120],
            },
        )
        return {
            "organization_id": None,
            "jobs_created": 0,
            "skipped": 0,
            "message_id": email.message_id,
            "reason": "no-attachments",
        }

    organization_id = resolve_tenant_from_address(email.to)

    if len(email.attachments) > MAX_INBOUND_ATTACHMENTS:
        raise EmailForwardError(
            f"Too many attachments: {len(email.attachments)} (max "
            f"{MAX_INBOUND_ATTACHMENTS}). Forward fewer per email."
        )

    jobs_created: list[uuid.UUID] = []
    skipped: list[dict] = []

    for attachment in email.attachments:
        if len(attachment.body) > MAX_INBOUND_ATTACHMENT_BYTES:
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
        # Fix up "octet-stream" PDFs by sniffing the magic bytes.
        # Some accounting software sends PDFs without the proper
        # Content-Type header; we don't want to lose those.
        mime = attachment.mime_type
        if mime == "application/octet-stream" and attachment.body[:4] == b"%PDF":
            mime = "application/pdf"
        try:
            job = _create_email_forward_job(
                organization_id=organization_id,
                attachment=attachment,
                mime_type=mime,
                email=email,
            )
            jobs_created.append(job.id)
        except Exception as exc:
            logger.exception(
                "ingestion.email_forward.attachment_failed",
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
        action_type="ingestion.email_forward.processed",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="ingestion.email_forward",
        organization_id=str(organization_id),
        affected_entity_type="EmailForward",
        affected_entity_id=email.message_id[:64] or "",
        payload={
            "to": email.to,
            "sender": _redact_email(email.sender),
            "subject": email.subject[:120],
            "attachments_received": len(email.attachments),
            "jobs_created": len(jobs_created),
            "skipped": skipped,
        },
    )

    return {
        "organization_id": str(organization_id),
        "jobs_created": [str(j) for j in jobs_created],
        "skipped": skipped,
        "message_id": email.message_id,
    }


def _create_email_forward_job(
    *,
    organization_id: uuid.UUID,
    attachment: InboundAttachment,
    mime_type: str,
    email: InboundEmail,
) -> IngestionJob:
    """Persist one attachment to S3 + create the IngestionJob row.

    Mirrors ``upload_web_file`` minus the user-facing actor — the
    actor on the audit event is the service identity.
    """
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
        content_type=mime_type,
    )

    from django.utils import timezone as _tz

    with super_admin_context(reason="ingestion.email_forward.create_job"):
        job = IngestionJob.objects.create(
            id=job_id,
            organization_id=organization_id,
            source_channel=IngestionJob.SourceChannel.EMAIL_FORWARD,
            # Carry the message_id as the source identifier so
            # duplicate forwards can be detected later (the column
            # is db-indexed for dedup lookups).
            source_identifier=email.message_id[:255],
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
        actor_id="ingestion.email_forward",
        organization_id=str(organization_id),
        affected_entity_type="IngestionJob",
        affected_entity_id=str(job.id),
        payload={
            "source_channel": IngestionJob.SourceChannel.EMAIL_FORWARD.value,
            "original_filename": attachment.filename,
            "file_size": stored.size,
            "file_mime_type": stored.content_type,
            "s3_object_key": object_key,
            "sender": _redact_email(email.sender),
            "message_id": email.message_id[:64],
        },
    )

    # Fire extraction asynchronously, post-commit (matches web-upload).
    from django.db import transaction as _txn

    from apps.extraction.tasks import extract_invoice

    _txn.on_commit(lambda: extract_invoice.delay(str(job.id)))
    return job


# --- Inbox token management ------------------------------------------------


def generate_inbox_token() -> str:
    """Mint a fresh 16-char URL-safe token for an org's inbox address."""
    return secrets.token_urlsafe(12)[:16]


def ensure_inbox_token(organization_id: uuid.UUID | str) -> str:
    """Return the org's inbox token, generating one on first call."""
    with super_admin_context(reason="ingestion.email_forward.token"):
        org = Organization.objects.filter(id=organization_id).first()
        if org is None:
            raise EmailForwardError(f"Organization {organization_id} not found.")
        if not org.inbox_token:
            org.inbox_token = generate_inbox_token()
            org.save(update_fields=["inbox_token", "updated_at"])
    return org.inbox_token


def inbox_address_for_org(organization_id: uuid.UUID | str) -> str:
    """Build the full magic-address string for the customer's UI."""
    token = ensure_inbox_token(organization_id)
    return f"invoices+{token}@{INBOX_DOMAIN}"


def rotate_inbox_token(
    *,
    organization_id: uuid.UUID | str,
    actor_user_id: uuid.UUID | str,
    reason: str = "",
) -> str:
    """Mint a fresh inbox token, replacing the current one (Slice 80).

    The old token stops resolving immediately. Mail forwarded to the
    old address from this point on will hit ``InboxNotFoundError``
    in ``resolve_tenant_from_address`` + bounce at the email
    provider's webhook layer (the provider gets a 404 from us).

    Returns the full new address so the caller can render it
    immediately without a follow-up GET.

    Audit: ``ingestion.inbox_token.rotated`` records the actor +
    reason + a 4-char prefix of each token (so a chain reader can
    correlate with provider-side logs without seeing the secret).
    The full token never enters the audit chain.
    """
    with super_admin_context(reason="ingestion.email_forward.rotate"):
        org = Organization.objects.filter(id=organization_id).first()
        if org is None:
            raise EmailForwardError(f"Organization {organization_id} not found.")
        previous_token = org.inbox_token or ""
        org.inbox_token = generate_inbox_token()
        org.save(update_fields=["inbox_token", "updated_at"])
        new_token = org.inbox_token

    record_event(
        action_type="ingestion.inbox_token.rotated",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(organization_id),
        affected_entity_type="Organization",
        affected_entity_id=str(organization_id),
        payload={
            # Prefix-only — full token is a credential, never logged.
            "from_token_prefix": previous_token[:4],
            "to_token_prefix": new_token[:4],
            "reason": (reason or "")[:255],
        },
    )
    return f"invoices+{new_token}@{INBOX_DOMAIN}"


# --- Helpers ----------------------------------------------------------------


def _redact_email(address: str) -> str:
    """Mask all but the first char of the local part for audit safety."""
    if not address or "@" not in address:
        return "***"
    local, domain = address.split("@", 1)
    if not local:
        return f"@{domain}"
    return f"{local[0]}{'*' * max(len(local) - 1, 1)}@{domain}"


def verify_provider_signature(*, secret: str, body: bytes, signature_hex: str) -> bool:
    """Verify an inbound webhook signature.

    Generic HMAC-SHA256 check — works for Mailgun (``signature``
    in their POST body), SendGrid (``X-Twilio-Email-Event-Webhook-
    Signature``), and most others. Adapters compose the message
    bytes per provider docs.
    """
    if not secret or not signature_hex:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_hex)
