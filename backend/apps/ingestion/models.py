"""Ingestion domain models.

Per DATA_MODEL.md, an ``IngestionJob`` is the wrapper around every file that
enters the system, regardless of channel. One uploaded PDF, one emailed
attachment, one WhatsApp media message → one IngestionJob row. ZIP archives
unpack into N IngestionJobs.

The job's status is the state machine that drives the Phase 2 / Phase 3
extraction and submission pipeline. Phase 1 only creates jobs in the
``received`` state; the next slice plugs in extraction.

State machine
-------------
    received → classifying → extracting → enriching → validating →
    ready_for_review → awaiting_approval → signing → submitting → validated

Terminal failure states branch off any non-terminal state:
    rejected | cancelled | error

Transitions are recorded in ``state_transitions`` (a JSON list of
``{status, timestamp}`` tuples) and emit ``ingestion.job.state_changed``
audit events. Reading the audit log is authoritative; the column is a
denormalized convenience for the review UI.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone

from apps.identity.models import TenantScopedModel


class IngestionJob(TenantScopedModel):
    """A single file in flight from ingestion to LHDN submission."""

    class SourceChannel(models.TextChoices):
        WEB_UPLOAD = "web_upload", "Web upload"
        EMAIL_FORWARD = "email_forward", "Email forward"
        WHATSAPP = "whatsapp", "WhatsApp"
        API = "api", "API"
        DATABASE_CONNECTOR = "database_connector", "Database connector"

    class Status(models.TextChoices):
        # Non-terminal pipeline states. Order matters for state-machine validation.
        RECEIVED = "received", "Received"
        CLASSIFYING = "classifying", "Classifying"
        EXTRACTING = "extracting", "Extracting"
        ENRICHING = "enriching", "Enriching"
        VALIDATING = "validating", "Validating"
        READY_FOR_REVIEW = "ready_for_review", "Ready for review"
        AWAITING_APPROVAL = "awaiting_approval", "Awaiting approval"
        SIGNING = "signing", "Signing"
        SUBMITTING = "submitting", "Submitting"
        # Terminal states.
        VALIDATED = "validated", "Validated by LHDN"
        REJECTED = "rejected", "Rejected by LHDN"
        CANCELLED = "cancelled", "Cancelled"
        ERROR = "error", "Error"

    TERMINAL_STATUSES = frozenset(
        {Status.VALIDATED, Status.REJECTED, Status.CANCELLED, Status.ERROR}
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    source_channel = models.CharField(max_length=24, choices=SourceChannel.choices)
    # Stable upstream identifier (email message id, WhatsApp media id, API request id).
    # Indexed so we can dedupe re-deliveries from the same channel.
    source_identifier = models.CharField(max_length=255, blank=True, db_index=True)

    original_filename = models.CharField(max_length=512)
    file_size = models.BigIntegerField()
    file_mime_type = models.CharField(max_length=128)

    # Where the original lives in object storage. The bucket is implicit
    # (S3_BUCKET_UPLOADS); the key carries the tenant prefix per
    # apps.integrations.storage.ingestion_object_key.
    s3_object_key = models.CharField(max_length=1024)

    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.RECEIVED, db_index=True
    )
    state_transitions = models.JSONField(default=list, blank=True)

    # If this job ends up producing an Invoice, the back-link is set on the Invoice
    # (Invoice.ingestion_job_id). We do not store the forward link here to avoid
    # circular FKs; reverse-lookup via select_related on the invoice context.

    error_message = models.TextField(blank=True)

    upload_timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ingestion_job"
        ordering = ["-upload_timestamp"]
        indexes = [
            models.Index(fields=["organization", "-upload_timestamp"]),
            models.Index(fields=["organization", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.original_filename} ({self.status})"

    @property
    def is_terminal(self) -> bool:
        return self.status in self.TERMINAL_STATUSES
