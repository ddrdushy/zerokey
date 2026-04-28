"""Audit log model.

Per AUDIT_LOG_SPEC.md the audit log is the immutable, hash-chained record of
every business-meaningful action. It is foundational — Phase 1 wires the chain
from the first authentication event so we never accumulate a backlog of
unaudited history.

Field-level notes:
  - ``sequence`` is global and gap-free. Inserts are serialized through an
    advisory lock (see ``services.record_event``) so concurrent writers do not
    interleave hashes.
  - ``organization`` is nullable: system-level events (e.g. nightly chain
    verification) belong to no tenant. Tenant queries filter on it; super-admin
    sees everything.
  - ``content_hash`` / ``chain_hash`` are 32-byte SHA-256 digests stored as raw
    bytes (BinaryField). Hex conversion is a presentation detail; the canonical
    math operates on bytes.
  - ``signature`` is reserved for Ed25519 signatures over ``chain_hash`` (KMS-
    backed). Phase 1 leaves it empty so wiring KMS later does not need a
    schema migration.
  - The table is append-only at the application layer (model.save / .delete
    refuse). At the database layer the RLS migration denies UPDATE and DELETE
    to the app role.
"""

from __future__ import annotations

import uuid
from typing import Any

from django.db import models
from django.utils import timezone


class AuditEvent(models.Model):
    """An immutable record of one auditable action."""

    class ActorType(models.TextChoices):
        USER = "user", "User"
        SERVICE = "service", "Service"
        STAFF = "staff", "Staff"
        EXTERNAL = "external", "External"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Globally monotonic sequence (gap-free). Populated under an advisory lock by
    # ``services.record_event`` so two concurrent inserts cannot share a number.
    sequence = models.BigIntegerField(unique=True, db_index=True)

    timestamp = models.DateTimeField(default=timezone.now, db_index=True)

    # Tenant scope. Nullable for system events that do not belong to a customer.
    organization = models.ForeignKey(
        "identity.Organization",
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
        db_index=True,
    )

    actor_type = models.CharField(max_length=16, choices=ActorType.choices)
    actor_id = models.CharField(max_length=128, blank=True)

    # Stable, namespaced action identifier. The catalog lives in code.
    action_type = models.CharField(max_length=128, db_index=True)

    affected_entity_type = models.CharField(max_length=64, blank=True)
    affected_entity_id = models.CharField(max_length=128, blank=True)

    payload = models.JSONField(default=dict, blank=True)
    payload_schema_version = models.IntegerField(default=1)

    content_hash = models.BinaryField(max_length=32)
    chain_hash = models.BinaryField(max_length=32, unique=True)
    signature = models.BinaryField(max_length=64, blank=True, default=bytes)

    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = "audit_event"
        ordering = ["sequence"]
        indexes = [
            models.Index(fields=["organization", "sequence"]),
            models.Index(fields=["action_type", "timestamp"]),
        ]

    def __str__(self) -> str:
        return f"#{self.sequence} {self.action_type} ({self.actor_type}:{self.actor_id})"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk and AuditEvent.objects.filter(pk=self.pk).exists():
            raise RuntimeError(
                "AuditEvent rows are immutable. Construct a new event for state changes."
            )
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise RuntimeError("AuditEvent rows cannot be deleted from application code.")


class ChainVerificationRun(models.Model):
    """One execution of the chain integrity check.

    Records both background (Celery beat) and customer-triggered runs in a
    single table so the "last verification" surface on the audit page can
    show a unified status regardless of who or what kicked off the check.

    System-level (no ``organization`` column): the chain itself is global,
    and verification reads every event under super-admin elevation. The
    table is read-only to the app role except for the audit task that
    writes it; UI access goes through a service that filters out
    operational fields (``error_detail``) before returning.
    """

    class Status(models.TextChoices):
        OK = "ok", "Ok"
        TAMPERED = "tampered", "Tampered"
        ERROR = "error", "Error"

    class Source(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        MANUAL = "manual", "Manual"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices)
    events_verified = models.IntegerField(default=0)
    source = models.CharField(max_length=16, choices=Source.choices)

    # Operational detail — never returned to customers. The customer-facing
    # contract is "ok / tampering detected; contact support" same as the
    # interactive verify call. The detail here is for the ops dashboard /
    # logs only.
    error_detail = models.TextField(blank=True, default="")

    class Meta:
        db_table = "chain_verification_run"
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.status} via {self.source} @ {self.started_at.isoformat()}"
