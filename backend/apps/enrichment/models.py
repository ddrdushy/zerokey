"""Enrichment domain models — customer + item master records.

Per DATA_MODEL.md these accumulate buyer and item patterns from invoices the
customer has issued, and drive the "every correction makes the system
smarter" promise: subsequent invoices with the same buyer auto-fill
identifying fields from this row rather than re-extracting them from
scratch (and re-paying for the LLM call). The records are also the
primary source of switching cost — a customer with three years of
master records on ZeroKey isn't trivially going to migrate to a
competitor that starts from zero.

Tenancy: both tables are tenant-scoped at the model level. Per-table
CREATE POLICY pattern matches the rest of the codebase; defensive
``organization`` FK so a JOIN bug can't leak a competitor's customer list.

Cross-context model imports are forbidden — call
``apps.enrichment.services`` from outside this app.
"""

from __future__ import annotations

import uuid

from django.db import models

from apps.identity.models import TenantScopedModel


class CustomerMaster(TenantScopedModel):
    """A known buyer for an issuing Organization.

    Matched on ``tin`` first (exact), then by ``legal_name`` against
    canonical name or any learned alias. New invoices that match an
    existing record copy any blank fields from this row and increment
    ``usage_count``; new invoices that don't match create a fresh row.

    The TIN-verification fields are populated by the LHDN TIN
    verification API when that wires in. Until then the state stays
    ``unverified`` for new records.
    """

    class TinVerificationState(models.TextChoices):
        # Default — never been checked against LHDN.
        UNVERIFIED = "unverified", "Unverified"
        # Slice 73 (connectors): synced from an external source
        # (CSV / AutoCount / Xero / etc.). Different from plain
        # `unverified` because the customer has more reason to trust
        # it (it came from their books, not the LLM extraction) but
        # LHDN hasn't confirmed the TIN exists yet. The pill is
        # rendered amber-ish, distinct from `verified` (green) and
        # plain `unverified` (grey).
        UNVERIFIED_EXTERNAL_SOURCE = (
            "unverified_external_source",
            "Unverified (from external source)",
        )
        # Slice 70 — LHDN's /taxpayer/validate said this TIN exists.
        VERIFIED = "verified", "Verified"
        # Slice 70 — LHDN's /taxpayer/validate returned 404.
        FAILED = "failed", "Failed verification"
        # Slice 74+: user picked the value in the conflict-queue UI.
        # Locks future syncs from quietly overwriting it (the lock
        # row is the actual mechanism; this state is the audit trail
        # that says "a human chose this").
        MANUALLY_RESOLVED = "manually_resolved", "Manually resolved"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Canonical name as we know the buyer today. ``aliases`` is a flat list
    # of every distinct name the LLM has emitted for this TIN over time.
    legal_name = models.CharField(max_length=255)
    aliases = models.JSONField(default=list, blank=True)

    tin = models.CharField(max_length=32, blank=True, db_index=True)
    tin_verification_state = models.CharField(
        max_length=32,
        choices=TinVerificationState.choices,
        default=TinVerificationState.UNVERIFIED,
    )
    tin_last_verified_at = models.DateTimeField(null=True, blank=True)

    registration_number = models.CharField(max_length=64, blank=True)
    msic_code = models.CharField(max_length=8, blank=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    sst_number = models.CharField(max_length=32, blank=True)
    country_code = models.CharField(max_length=2, blank=True)

    # Slice 73 — per-field provenance. Maps field_name → entry.
    # Entry shape (all keys optional except `source`):
    #   {
    #     "source": "extracted" | "manual" | "manually_resolved"
    #               | "synced_csv" | "synced_autocount" | "synced_xero"
    #               | "synced_quickbooks" | "synced_shopify"
    #               | "synced_woocommerce" | "synced_sql_accounting",
    #     "extracted_at": ISO8601,                   # for extracted
    #     "invoice_id": uuid,                        # for extracted
    #     "synced_at": ISO8601,                      # for synced_*
    #     "source_record_id": "string",              # for synced_*
    #     "applied_via_proposal_id": uuid,           # for synced_*
    #     "approved_by": user_uuid,                  # for synced_* / manually_resolved
    #     "entered_at": ISO8601,                     # for manual
    #     "edited_by": user_uuid,                    # for manual
    #   }
    # Per-record provenance was rejected — different fields
    # legitimately come from different sources, and audit needs the
    # granularity. JSON column instead of a separate provenance table
    # because every CustomerMaster read would otherwise need a join
    # and the field set is small.
    field_provenance = models.JSONField(default=dict, blank=True)

    # How many invoices have referenced this buyer. Drives the
    # "frequent customers" view and lets us de-prioritise stale records
    # in alias matching when two records compete.
    usage_count = models.PositiveIntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "customer_master"
        ordering = ["-usage_count", "legal_name"]
        constraints = [
            # Within an org a TIN identifies a unique buyer. Empty TINs
            # are common enough (B2C, foreign suppliers in transition)
            # that we don't enforce uniqueness on those rows; the alias
            # match handles dedup for them.
            models.UniqueConstraint(
                fields=["organization", "tin"],
                condition=models.Q(tin__gt=""),
                name="customer_master_uniq_org_tin",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "tin"]),
            models.Index(fields=["organization", "legal_name"]),
        ]

    def __str__(self) -> str:
        return f"{self.legal_name} ({self.tin or 'no TIN'})"


class ItemMaster(TenantScopedModel):
    """A known line-item description for an issuing Organization.

    Matched by exact (case-insensitive) match of the line item's
    description against ``canonical_name`` or any alias. On a match the
    invoice's line item inherits the master's default codes
    (MSIC / classification / tax type / UOM); on no match a new row is
    created with the description as canonical and the inherited fields
    blank, ready to learn from the next correction.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    canonical_name = models.CharField(max_length=512, db_index=True)
    aliases = models.JSONField(default=list, blank=True)

    default_msic_code = models.CharField(max_length=8, blank=True)
    default_classification_code = models.CharField(max_length=16, blank=True)
    default_tax_type_code = models.CharField(max_length=16, blank=True)
    default_unit_of_measurement = models.CharField(max_length=16, blank=True)

    # Advisory only — the LLM still extracts the price from the source.
    # We store it for "is this price unusual?" warnings in a later slice.
    default_unit_price_excl_tax = models.DecimalField(
        max_digits=19, decimal_places=2, null=True, blank=True
    )

    # Slice 73 — per-field provenance. Same shape as
    # CustomerMaster.field_provenance.
    field_provenance = models.JSONField(default=dict, blank=True)

    usage_count = models.PositiveIntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "item_master"
        ordering = ["-usage_count", "canonical_name"]
        indexes = [
            models.Index(fields=["organization", "canonical_name"]),
        ]

    def __str__(self) -> str:
        return self.canonical_name[:60]
