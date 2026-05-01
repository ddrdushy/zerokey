"""Integrations domain models — webhooks, sync jobs.

Per DATA_MODEL.md §"Integrations domain" + PRD Domain 12 the platform
exposes outbound webhooks for customers to receive event notifications.
Customers register an endpoint URL + a list of event types they care
about; we POST to that URL with a signed payload and record each
delivery.

This slice ships the data model + management UI. The actual delivery
worker (HMAC signing, exponential-backoff retries, dead-letter
handling) is a follow-up; today the rows persist and the UI surface
is in place. ``WebhookDelivery`` rows are created by the future
worker; the "send test" button creates a synthetic delivery for
visibility.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid

from django.db import models
from django.utils import timezone

from apps.identity.models import TenantScopedModel


class WebhookEndpoint(TenantScopedModel):
    """A customer-registered HTTP endpoint that receives event payloads.

    The signing secret is generated at creation and shown ONCE — same
    write-only contract as APIKey. Receivers verify deliveries via
    HMAC-SHA256(secret, payload).

    ``event_types`` is a JSON list of event keys this endpoint
    subscribes to. The recognised list lives in
    ``apps.integrations.services.WEBHOOK_EVENT_KEYS``.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    label = models.CharField(max_length=64)
    url = models.URLField(max_length=2048)
    event_types = models.JSONField(default=list, blank=True)
    # Slice 96 — payload versioning per API_DESIGN.md §184. New
    # endpoints default to the current version; older endpoints
    # stay pinned to the version they were created against until
    # the customer migrates. Today only "v1" exists; "v2" will
    # land alongside the first breaking change to a payload shape.
    api_version = models.CharField(max_length=8, default="v1")

    secret_prefix = models.CharField(max_length=16, db_index=True)
    secret_hash = models.CharField(max_length=128)
    # Fernet-encrypted plaintext of the signing secret. Required so
    # the outbound delivery worker (Slice 53) can HMAC payloads with
    # the literal secret the customer was shown at create time —
    # otherwise receivers can't verify our signatures. Older rows
    # created before Slice 53 land have this empty; deliveries from
    # them go out unsigned and the test surface flags them so the
    # customer regenerates.
    secret_encrypted = models.TextField(blank=True, default="")

    created_by_user_id = models.UUIDField(null=True, blank=True)

    is_active = models.BooleanField(default=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by_user_id = models.UUIDField(null=True, blank=True)

    last_succeeded_at = models.DateTimeField(null=True, blank=True)
    last_failed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "integrations_webhook_endpoint"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.label} ({self.url[:50]})"


class WebhookDelivery(TenantScopedModel):
    """One delivery attempt against a WebhookEndpoint.

    Append-only. Retries of the same logical event share ``event_id``
    so the per-event view aggregates correctly. The future delivery
    worker fills in HTTP-level fields (status, body excerpt,
    error_class, duration_ms); today the row exists for the test-
    delivery button + the data model.
    """

    class Outcome(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        FAILURE = "failure", "Failure"
        RETRYING = "retrying", "Retrying"
        ABANDONED = "abandoned", "Abandoned"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    endpoint = models.ForeignKey(
        WebhookEndpoint, on_delete=models.CASCADE, related_name="deliveries"
    )

    event_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    event_type = models.CharField(max_length=64, db_index=True)
    payload = models.JSONField(default=dict, blank=True)

    attempt = models.IntegerField(default=1)
    outcome = models.CharField(max_length=16, choices=Outcome.choices, default=Outcome.PENDING)

    response_status = models.IntegerField(null=True, blank=True)
    response_body_excerpt = models.CharField(max_length=512, blank=True)
    error_class = models.CharField(max_length=128, blank=True)
    duration_ms = models.IntegerField(null=True, blank=True)

    queued_at = models.DateTimeField(default=timezone.now)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "integrations_webhook_delivery"
        ordering = ["-queued_at"]
        indexes = [
            models.Index(fields=["organization", "endpoint", "-queued_at"]),
            models.Index(fields=["event_id"]),
            models.Index(fields=["outcome", "-queued_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} #{self.attempt} → {self.endpoint_id} ({self.outcome})"


def generate_secret() -> tuple[str, str, str]:
    """Mint a fresh webhook signing secret.

    Returns ``(plaintext, prefix, sha256_hex)``. Same shape as the
    APIKey helper so callers handle them uniformly.
    """
    plaintext = "whsec_" + secrets.token_urlsafe(36)[:36]
    prefix = plaintext[:12]
    sha = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    return plaintext, prefix, sha
