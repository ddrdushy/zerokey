"""Engine registry + per-call observability.

Per ENGINE_REGISTRY.md, every OCR/LLM call produces an EngineCall row so we
have real per-engine quality and cost data over time. Adapters live in code;
the registry lives in the database so the super-admin can edit routing rules
without a deploy.

Phase 2 surface
---------------
- ``Engine`` — registered adapter with status, capability, vendor metadata.
  Seeded by a data migration; super-admin console will edit later.
- ``EngineCall`` — per-call telemetry. Latency, cost, confidence, success.
  System-scoped (no organization FK on the table) so cross-tenant analytics
  are straightforward; payload digests reference the originating IngestionJob
  rather than embedding tenant data.
- ``EngineRoutingRule`` — priority-ordered rules with a condition expression
  (Phase 2 keeps this simple: just file_mime → engine). Real expression
  evaluation lands in a follow-up.

Engines are not tenant-scoped (every customer routes through the same
adapters); calls are not tenant-scoped either, but every call records a
``request_id`` (the IngestionJob.id) that links back to a tenant via the
ingestion table.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


class Engine(models.Model):
    """Registered adapter — one row per (vendor, model, adapter version)."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DEGRADED = "degraded", "Degraded"
        ARCHIVED = "archived", "Archived"

    class Capability(models.TextChoices):
        TEXT_EXTRACT = "text_extract", "Text extract"
        VISION_EXTRACT = "vision_extract", "Vision extract"
        FIELD_STRUCTURE = "field_structure", "Field structure"
        EMBED = "embed", "Embed"
        CLASSIFY = "classify", "Classify"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Stable identifier the adapter registers under (e.g. "pdfplumber",
    # "anthropic-claude-sonnet-4-6", "azure-doc-intelligence-v3").
    name = models.SlugField(max_length=128, unique=True)

    vendor = models.CharField(max_length=64)
    model_identifier = models.CharField(max_length=128, blank=True)
    adapter_version = models.CharField(max_length=32, default="1")

    capability = models.CharField(max_length=24, choices=Capability.choices, db_index=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)

    # Cents-per-call baseline (rough). Calibrated against actual EngineCall rows.
    cost_per_call_micros = models.IntegerField(default=0)

    # Per-engine vendor credentials (api keys, endpoint URLs, project ids).
    # Resolved by ``apps.extraction.credentials.engine_credential`` with an
    # env-var fallback so first boot still works before the super-admin has
    # populated the row. Plaintext for now; KMS-backed envelope encryption
    # lands when the signing service brings KMS online (BUILD_LOG deferred
    # item #6). DO NOT log this field — the redaction allowlist excludes it.
    credentials = models.JSONField(default=dict, blank=True)

    description = models.TextField(blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "engine"
        ordering = ["capability", "name"]
        indexes = [
            models.Index(fields=["capability", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.capability})"


class EngineCall(models.Model):
    """Per-call telemetry. Append-only at the application layer."""

    class Outcome(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILURE = "failure", "Failure"
        TIMEOUT = "timeout", "Timeout"
        UNAVAILABLE = "unavailable", "Unavailable"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    engine = models.ForeignKey(Engine, on_delete=models.PROTECT, related_name="calls")

    # The IngestionJob (or other entity) that triggered this call. Soft FK
    # by uuid so cross-app coupling stays minimal.
    request_id = models.UUIDField(db_index=True, null=True, blank=True)
    organization_id = models.UUIDField(db_index=True, null=True, blank=True)

    started_at = models.DateTimeField(default=timezone.now)
    duration_ms = models.IntegerField()

    outcome = models.CharField(max_length=16, choices=Outcome.choices)
    error_class = models.CharField(max_length=128, blank=True)

    cost_micros = models.IntegerField(default=0)
    confidence = models.FloatField(null=True, blank=True)

    # Vendor diagnostics, with sensitive payload values stripped out at the
    # adapter layer. Never include raw PII.
    diagnostics = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "engine_call"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["engine", "-started_at"]),
            models.Index(fields=["request_id"]),
            models.Index(fields=["organization_id", "-started_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.engine.name} {self.outcome} ({self.duration_ms}ms)"


class EngineRoutingRule(models.Model):
    """Priority-ordered rule that picks an engine for a job.

    Phase 2 keeps the condition simple: a comma-separated list of mime types
    plus an optional plan tier. A future slice replaces this with a full
    expression evaluator (the spec calls out condition_expression DSL).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    capability = models.CharField(max_length=24, choices=Engine.Capability.choices, db_index=True)
    priority = models.IntegerField(default=100)
    description = models.CharField(max_length=255, blank=True)

    # Comma-separated list; "*" matches anything. Empty == no constraint.
    match_mime_types = models.CharField(max_length=512, default="*")

    engine = models.ForeignKey(Engine, on_delete=models.PROTECT, related_name="routing_rules")
    fallback_engine = models.ForeignKey(
        Engine, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "engine_routing_rule"
        ordering = ["capability", "priority"]
        indexes = [
            models.Index(fields=["capability", "is_active", "priority"]),
        ]

    def __str__(self) -> str:
        return f"{self.capability} @ {self.priority} → {self.engine.name}"
