"""Reference-data connector models (Slice 73).

This app is the home of the *inbound* reference-data connectors —
the systems customers already maintain (accounting suites,
e-commerce platforms, CSV exports) that pre-populate their
CustomerMaster + ItemMaster rows so they don't start cold.

Distinct from ``apps.integrations`` (outbound webhook delivery)
and ``apps.identity.OrganizationIntegration`` (per-tenant
sandbox/prod credentials for outbound APIs like LHDN). Naming
note: ``OrganizationIntegration`` lives in identity because it
predates this app and was tightly coupled to the LHDN credential
flow; the new connector world stays here.

What's in this slice (73): the IntegrationConfig row + RLS.
SyncProposal / MasterFieldConflict / MasterFieldLock and the
classify_merge matrix land in Slice 74; concrete connectors
land in Slice 77 onwards.
"""

from __future__ import annotations

import uuid

from django.db import models

from apps.identity.models import TenantScopedModel


class IntegrationConfig(TenantScopedModel):
    """Per-tenant reference-data connector configuration.

    One row per (Organization, connector_type). Holds whatever auth
    material the connector needs (KMS-encrypted), the sync cadence
    the customer chose, and the latest run's outcome.

    ``auto_apply`` defaults False and the API gates flipping it to
    True until a manual sync has applied at least once — too easy
    to silently corrupt a master record otherwise. The orchestrator
    refuses to chain into ``apply_sync_proposal`` while
    ``auto_apply=False``.
    """

    class ConnectorType(models.TextChoices):
        # CSV is the universal escape hatch — ships first (Slice 77).
        CSV = "csv", "CSV upload"
        # Malaysian SME accounting majority — ODBC-based.
        SQL_ACCOUNTING = "sql_accounting", "SQL Accounting"
        AUTOCOUNT = "autocount", "AutoCount"
        # Cloud accounting — OAuth2.
        XERO = "xero", "Xero"
        QUICKBOOKS = "quickbooks", "QuickBooks Online"
        # E-commerce — alias-only matching path validates here.
        SHOPIFY = "shopify", "Shopify"
        WOOCOMMERCE = "woocommerce", "WooCommerce"

    class SyncCadence(models.TextChoices):
        MANUAL = "manual", "Manual only"
        HOURLY = "hourly", "Hourly"
        DAILY = "daily", "Daily"

    class LastSyncStatus(models.TextChoices):
        NEVER = "never", "Never run"
        PROPOSED = "proposed", "Proposed (awaiting review)"
        APPLIED = "applied", "Applied"
        FAILED = "failed", "Failed"
        REVERTED = "reverted", "Reverted"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    connector_type = models.CharField(
        max_length=32, choices=ConnectorType.choices, db_index=True
    )

    # KMS-encrypted JSON. Each connector defines its own credential
    # field set (e.g. CSV: {} since the upload is the auth; Xero:
    # {client_id, refresh_token, ...}). Fernet at-rest encryption
    # via apps.administration.crypto, same as
    # OrganizationIntegration.{sandbox,production}_credentials.
    credentials = models.JSONField(default=dict, blank=True)

    sync_cadence = models.CharField(
        max_length=16,
        choices=SyncCadence.choices,
        default=SyncCadence.MANUAL,
    )

    # Off by default, can only be flipped on after one manual sync
    # has reached `applied` state. Service layer enforces this — the
    # column itself is just a flag.
    auto_apply = models.BooleanField(default=False)

    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(
        max_length=16,
        choices=LastSyncStatus.choices,
        default=LastSyncStatus.NEVER,
    )
    # Truncated to 1KB at the service layer — full stack traces go
    # to the audit log + worker logs, not this column.
    last_sync_error = models.TextField(blank=True)

    # Soft delete. Disabling a connector keeps the row + audit
    # history but stops cadence-triggered runs.
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "connectors_integration_config"
        ordering = ["connector_type"]
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "connector_type"),
                condition=models.Q(deleted_at__isnull=True),
                name="connectors_integration_config_uniq_org_type_active",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "connector_type"],
                name="connectors_org_type_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.connector_type} ({self.organization_id})"

    @property
    def is_active(self) -> bool:
        return self.deleted_at is None


# --- Master discriminator -----------------------------------------------------
#
# SyncProposal results, per-field locks, and conflicts apply to either a
# CustomerMaster row or an ItemMaster row. We use a (master_type, master_id)
# tuple as a soft discriminator instead of Django's GenericForeignKey because
# GFK makes RLS policies + cross-app migrations awkward, and we only have
# two master types so the discriminator stays small.


class MasterType(models.TextChoices):
    CUSTOMER = "customer", "Customer master"
    ITEM = "item", "Item master"


class SyncProposal(TenantScopedModel):
    """A durable sync run, classified but not yet applied (Slice 74).

    Two-phase syncs are non-negotiable in this initiative: every
    connector run produces a SyncProposal first, the user reviews
    the diff, and only on approval does ``apply_sync_proposal``
    write to the master records. Even with ``auto_apply=True`` on
    the IntegrationConfig, the proposal is durable and the apply
    is a separate audited operation — there is NO path where a
    sync writes to the master without a SyncProposal row.

    The ``diff`` JSON carries the full proposed changes. Per-master
    layout:

        {
          "customers": {
            "would_add":   [...full CustomerMaster shape...],
            "would_update": [{
                "existing_id": uuid,
                "changes": {"field": {"current": ..., "proposed": ...}, ...}
            }],
            "conflicts":   [{"existing_id": uuid, "field": "tin", ...}],
            "skipped_locked": [...],
            "skipped_verified": [...]
          },
          "items": { ... same shape ... }
        }

    The diff is reversible: ``apply_sync_proposal`` records the
    pre-apply value of every field it touches in
    ``applied_changes`` (set when applied), and
    ``revert_sync_proposal`` walks that map in reverse to restore
    prior state within ``expires_at``.
    """

    REVERT_WINDOW_DAYS = 14

    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed (awaiting review)"
        APPLIED = "applied", "Applied"
        REVERTED = "reverted", "Reverted"
        EXPIRED = "expired", "Expired (revert window closed)"
        CANCELLED = "cancelled", "Cancelled by operator"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    integration_config = models.ForeignKey(
        IntegrationConfig,
        on_delete=models.PROTECT,
        related_name="sync_proposals",
    )

    # Soft FKs to identity.User per the cross-context-imports-forbidden
    # rule — the actor + applier + reverter are surfaced via the audit
    # log and joined at read time.
    actor_user_id = models.UUIDField()

    proposed_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PROPOSED
    )

    applied_at = models.DateTimeField(null=True, blank=True)
    applied_by_user_id = models.UUIDField(null=True, blank=True)
    reverted_at = models.DateTimeField(null=True, blank=True)
    reverted_by_user_id = models.UUIDField(null=True, blank=True)

    # The classified-but-not-applied diff. See module docstring for shape.
    diff = models.JSONField(default=dict)

    # Populated on apply. Each entry records the pre-apply value so
    # revert can restore it; format mirrors ``diff.would_update``.
    applied_changes = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "connectors_sync_proposal"
        ordering = ["-proposed_at"]
        indexes = [
            models.Index(
                fields=["integration_config", "-proposed_at"],
                name="conn_proposal_cfg_idx",
            ),
            models.Index(
                fields=["organization", "status"],
                name="conn_proposal_org_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"SyncProposal({self.integration_config_id}, {self.status})"


class MasterFieldLock(TenantScopedModel):
    """A pin on one field of one master record (Slice 74).

    Once locked, future syncs that would change the field always
    route to the conflict queue regardless of source — even from
    the same connector that originally populated it. Locks are
    stronger than provenance trust ranks: they're how a user makes
    a correction stick against a noisy source.

    Toggled via the lock-icon UI (Slice 77+); the model is
    foundational so the merge classifier can read it now.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Polymorphic reference: which master + which row. See the
    # MasterType note at module top.
    master_type = models.CharField(
        max_length=16, choices=MasterType.choices, db_index=True
    )
    master_id = models.UUIDField(db_index=True)

    field_name = models.CharField(max_length=64)

    locked_by_user_id = models.UUIDField()
    locked_at = models.DateTimeField(auto_now_add=True)

    # Optional human-supplied reason. Limited to 255 chars; longer
    # reasons go into the audit event payload.
    reason = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        db_table = "connectors_master_field_lock"
        ordering = ["-locked_at"]
        constraints = [
            # One active lock per (org, master row, field). Recreating
            # a lock after unlocking is allowed (we hard-delete on
            # unlock — locks aren't soft-deletable like
            # IntegrationConfigs because their semantics are "is this
            # field currently pinned").
            models.UniqueConstraint(
                fields=("organization", "master_type", "master_id", "field_name"),
                name="connectors_lock_uniq_org_master_field",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "master_type", "master_id"],
                name="connectors_lock_master_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Lock({self.master_type}:{self.master_id}.{self.field_name})"


class MasterFieldConflict(TenantScopedModel):
    """A field the merge classifier didn't auto-resolve (Slice 74).

    Created during ``propose_sync`` when the classifier returns
    ``conflict`` for a field. Persists the existing + incoming
    values + their provenance so the conflict-queue UI can render
    the diff without re-fetching anything. Resolved one at a time
    in v1 (bulk resolution is deferred); each resolution writes
    one audit event + closes the row.

    Resolution semantics:
      - ``keep_existing``: master row is unchanged; provenance updated
        to ``manually_resolved``.
      - ``take_incoming``: master row gets the incoming value;
        provenance updated to the source's tag.
      - ``keep_both_as_aliases``: only valid for the ``legal_name``
        field (CustomerMaster) and ``canonical_name`` (ItemMaster).
        Existing canonical name is preserved + the incoming value
        is appended to ``aliases``.
      - ``enter_custom_value``: master row gets ``custom_value``;
        provenance updated to ``manually_resolved``.
    """

    class Resolution(models.TextChoices):
        KEEP_EXISTING = "keep_existing", "Keep existing value"
        TAKE_INCOMING = "take_incoming", "Take incoming value"
        KEEP_BOTH_AS_ALIASES = "keep_both_as_aliases", "Keep both (alias)"
        ENTER_CUSTOM_VALUE = "enter_custom_value", "Enter custom value"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    sync_proposal = models.ForeignKey(
        SyncProposal,
        on_delete=models.CASCADE,
        related_name="conflicts",
    )

    master_type = models.CharField(
        max_length=16, choices=MasterType.choices, db_index=True
    )
    master_id = models.UUIDField(db_index=True)
    field_name = models.CharField(max_length=64)

    # Both values stored as text. For decimal / structured fields the
    # caller is responsible for the canonical string representation
    # (the diff JSON carries the same string so the UI renders
    # identically to the proposal preview).
    existing_value = models.TextField(blank=True, default="")
    existing_provenance = models.JSONField(default=dict, blank=True)
    incoming_value = models.TextField(blank=True, default="")
    incoming_provenance = models.JSONField(default=dict, blank=True)

    resolution = models.CharField(
        max_length=32,
        choices=Resolution.choices,
        blank=True,
        default="",
    )
    custom_value = models.TextField(blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by_user_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "connectors_master_field_conflict"
        ordering = ["-id"]
        indexes = [
            models.Index(
                fields=["organization", "resolved_at"],
                name="conn_conflict_org_unres_idx",
            ),
            models.Index(
                fields=["sync_proposal"],
                name="conn_conflict_proposal_idx",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"Conflict({self.master_type}:{self.master_id}.{self.field_name})"
        )

    @property
    def is_open(self) -> bool:
        return self.resolved_at is None
