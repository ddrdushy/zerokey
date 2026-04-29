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
