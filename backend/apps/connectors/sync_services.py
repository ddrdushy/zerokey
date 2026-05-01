"""Sync orchestration services for reference-data connectors (Slice 75).

The two-phase orchestration sitting on top of the Slice 74
classifier:

  1. ``propose_sync(*, config_id, customer_records, item_records,
     actor_user_id)`` — walks every (record × field), classifies it
     via ``classify_merge``, writes a ``SyncProposal`` + any
     ``MasterFieldConflict`` rows. Emits ``integration.sync_proposed``.
  2. ``apply_sync_proposal(*, proposal_id, actor_user_id)`` —
     writes the auto-resolvable changes + records pre-apply state
     in ``applied_changes`` so revert can walk it back. Emits
     ``integration.sync_applied``.
  3. ``revert_sync_proposal(*, proposal_id, actor_user_id, reason)``
     — within the 14-day window, restores prior state from
     ``applied_changes``. Emits ``integration.sync_reverted``.
  4. ``resolve_field_conflict(*, conflict_id, resolution, ...)`` —
     applies the user's choice from the conflict-queue UI; emits
     ``master_record.conflict_resolved``.
  5. ``lock_field`` / ``unlock_field`` — pin or release a
     specific field on a master record; emits
     ``master_record.field_{locked,unlocked}``.

Re-match pass (Slice 76) is wired as a stub callback —
``_trigger_rematch_after_apply`` is called on every successful
apply / revert; today it logs + audits + does nothing else.
Filling that out closes the loop where invoices in
``ready_for_review`` get lifted into ``ready_for_submission``
because a sync filled in the buyer the LLM missed.

Connector record shape (input to ``propose_sync``):

  customer_records = [
    {
      "source_record_id": "DEBT-00482",
      "fields": {
        "legal_name": "Acme Sdn Bhd",
        "tin": "C9999999999",
        "address": "Level 5, KL Sentral",
        ...
      },
    },
    ...
  ]

Each connector's adapter (Slice 77+) is responsible for emitting
this shape. The orchestration here is connector-agnostic.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.enrichment.models import CustomerMaster, ItemMaster

from .merge_classifier import ClassifyInputs, Verdict, classify_merge
from .models import (
    IntegrationConfig,
    MasterFieldConflict,
    MasterFieldLock,
    MasterType,
    SyncProposal,
)

logger = logging.getLogger(__name__)


# Field set per master that participates in classify_merge. Names
# match attributes on CustomerMaster / ItemMaster respectively.
# Adding a new master field = one entry here.
CUSTOMER_SYNCED_FIELDS: tuple[str, ...] = (
    "legal_name",
    "tin",
    "registration_number",
    "msic_code",
    "address",
    "phone",
    "sst_number",
    "country_code",
)

ITEM_SYNCED_FIELDS: tuple[str, ...] = (
    "canonical_name",
    "default_msic_code",
    "default_classification_code",
    "default_tax_type_code",
    "default_unit_of_measurement",
)


# Connector-type → provenance source string. Used both when
# tagging applied fields' provenance and in classify_merge as
# ``incoming_source``.
CONNECTOR_SOURCE_MAP: dict[str, str] = {
    IntegrationConfig.ConnectorType.CSV: "synced_csv",
    IntegrationConfig.ConnectorType.SQL_ACCOUNTING: "synced_sql_accounting",
    IntegrationConfig.ConnectorType.AUTOCOUNT: "synced_autocount",
    IntegrationConfig.ConnectorType.SQL_ACCOUNT: "synced_sql_account",
    IntegrationConfig.ConnectorType.SAGE_UBS: "synced_sage_ubs",
    IntegrationConfig.ConnectorType.XERO: "synced_xero",
    IntegrationConfig.ConnectorType.QUICKBOOKS: "synced_quickbooks",
    IntegrationConfig.ConnectorType.SHOPIFY: "synced_shopify",
    IntegrationConfig.ConnectorType.WOOCOMMERCE: "synced_woocommerce",
}


class SyncError(Exception):
    """Raised when the orchestration can't proceed (config missing,
    proposal already applied/reverted, revert window expired, etc.)."""


class RevertWindowExpired(SyncError):
    """Raised by ``revert_sync_proposal`` past the 14-day window."""


# --- Input shapes -----------------------------------------------------------


@dataclass(frozen=True)
class ConnectorRecord:
    """One record fetched from a connector.

    Each connector adapter (Slice 77+) maps its source-system rows
    into this shape. The ``source_record_id`` is whatever the
    source uses as a row identifier — used in audit trails + as
    the key for "did we sync this record before?".
    """

    source_record_id: str
    fields: dict[str, str]


# --- propose_sync -----------------------------------------------------------


@dataclass
class _ProposalBucket:
    """Per-master accumulator. Mirrors the diff JSON layout."""

    would_add: list[dict] = field(default_factory=list)
    would_update: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    skipped_locked: list[dict] = field(default_factory=list)
    skipped_verified: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "would_add": self.would_add,
            "would_update": self.would_update,
            "conflicts": self.conflicts,
            "skipped_locked": self.skipped_locked,
            "skipped_verified": self.skipped_verified,
        }


def propose_sync(
    *,
    integration_config_id: uuid.UUID | str,
    customer_records: list[ConnectorRecord] | None = None,
    item_records: list[ConnectorRecord] | None = None,
    actor_user_id: uuid.UUID | str,
) -> SyncProposal:
    """Build a SyncProposal from connector-fetched records.

    Pure-data: this function reads the masters but never writes to
    them. The output is durable (the SyncProposal row + any
    conflict rows). Apply is a separate, audited operation.
    """
    config = _load_integration_config(integration_config_id)
    incoming_source = CONNECTOR_SOURCE_MAP.get(config.connector_type, "")
    if not incoming_source:
        raise SyncError(f"Unknown connector type for source mapping: {config.connector_type}")

    customer_bucket = _classify_master_batch(
        organization_id=config.organization_id,
        master_type=MasterType.CUSTOMER,
        records=customer_records or [],
        synced_fields=CUSTOMER_SYNCED_FIELDS,
        incoming_source=incoming_source,
    )
    item_bucket = _classify_master_batch(
        organization_id=config.organization_id,
        master_type=MasterType.ITEM,
        records=item_records or [],
        synced_fields=ITEM_SYNCED_FIELDS,
        incoming_source=incoming_source,
    )

    diff = {
        "customers": customer_bucket.to_dict(),
        "items": item_bucket.to_dict(),
    }

    with transaction.atomic():
        proposal = SyncProposal.objects.create(
            organization_id=config.organization_id,
            integration_config=config,
            actor_user_id=actor_user_id,
            expires_at=timezone.now() + timedelta(days=SyncProposal.REVERT_WINDOW_DAYS),
            diff=diff,
        )
        # Materialise conflict rows so the conflict-queue UI has
        # something durable to query (the diff JSON also carries
        # them, but rows are the operational truth).
        for entry in customer_bucket.conflicts:
            MasterFieldConflict.objects.create(
                organization_id=config.organization_id,
                sync_proposal=proposal,
                master_type=MasterType.CUSTOMER,
                master_id=entry["existing_id"],
                field_name=entry["field"],
                existing_value=entry["existing_value"],
                existing_provenance=entry["existing_provenance"],
                incoming_value=entry["incoming_value"],
                incoming_provenance=entry["incoming_provenance"],
            )
        for entry in item_bucket.conflicts:
            MasterFieldConflict.objects.create(
                organization_id=config.organization_id,
                sync_proposal=proposal,
                master_type=MasterType.ITEM,
                master_id=entry["existing_id"],
                field_name=entry["field"],
                existing_value=entry["existing_value"],
                existing_provenance=entry["existing_provenance"],
                incoming_value=entry["incoming_value"],
                incoming_provenance=entry["incoming_provenance"],
            )

        config.last_sync_at = timezone.now()
        config.last_sync_status = IntegrationConfig.LastSyncStatus.PROPOSED
        config.last_sync_error = ""
        config.save(
            update_fields=[
                "last_sync_at",
                "last_sync_status",
                "last_sync_error",
                "updated_at",
            ]
        )

    record_event(
        action_type="integration.sync_proposed",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(config.organization_id),
        affected_entity_type="SyncProposal",
        affected_entity_id=str(proposal.id),
        payload={
            "connector_type": config.connector_type,
            "customers": _bucket_counts(customer_bucket),
            "items": _bucket_counts(item_bucket),
        },
    )
    return proposal


def _bucket_counts(bucket: _ProposalBucket) -> dict[str, int]:
    return {
        "would_add": len(bucket.would_add),
        "would_update": len(bucket.would_update),
        "conflicts": len(bucket.conflicts),
        "skipped_locked": len(bucket.skipped_locked),
        "skipped_verified": len(bucket.skipped_verified),
    }


def _classify_master_batch(
    *,
    organization_id: uuid.UUID,
    master_type: str,
    records: list[ConnectorRecord],
    synced_fields: tuple[str, ...],
    incoming_source: str,
) -> _ProposalBucket:
    bucket = _ProposalBucket()
    if not records:
        return bucket

    # Pre-fetch existing masters + their locks once. Cheaper than
    # one query per record + the typical sync touches a few hundred
    # records max.
    existing_masters = _list_masters(organization_id, master_type)
    locks_by_master = _list_locks_by_master(organization_id, master_type)

    for raw in records:
        record_fields = raw.fields or {}
        match = _match_master(master_type, record_fields, existing_masters)
        if match is None:
            bucket.would_add.append(
                {
                    "source_record_id": raw.source_record_id,
                    "fields": dict(record_fields),
                }
            )
            continue

        existing_id = str(match.id)
        locked_fields = locks_by_master.get(existing_id, set())
        provenance = match.field_provenance or {}
        per_field_changes: dict[str, dict] = {}

        for fname in synced_fields:
            incoming = (record_fields.get(fname) or "").strip()
            existing_value = (getattr(match, fname, "") or "").strip()
            existing_prov = provenance.get(fname)
            is_authority = (
                master_type == MasterType.CUSTOMER
                and fname == "tin"
                and getattr(match, "tin_verification_state", "")
                == CustomerMaster.TinVerificationState.VERIFIED
            )

            verdict = classify_merge(
                ClassifyInputs(
                    existing_value=existing_value,
                    existing_provenance=existing_prov,
                    incoming_value=incoming,
                    incoming_source=incoming_source,
                    is_locked=fname in locked_fields,
                    is_authority_verified=is_authority,
                )
            )
            if verdict is Verdict.NOOP:
                continue
            if verdict in (Verdict.AUTO_POPULATE, Verdict.AUTO_OVERWRITE):
                per_field_changes[fname] = {
                    "current": existing_value,
                    "proposed": incoming,
                    "verdict": verdict.value,
                }
                continue
            if verdict is Verdict.CONFLICT:
                bucket.conflicts.append(
                    {
                        "existing_id": existing_id,
                        "source_record_id": raw.source_record_id,
                        "field": fname,
                        "existing_value": existing_value,
                        "existing_provenance": existing_prov or {},
                        "incoming_value": incoming,
                        "incoming_provenance": {
                            "source": incoming_source,
                            "source_record_id": raw.source_record_id,
                        },
                    }
                )
                continue
            if verdict is Verdict.SKIPPED_LOCKED:
                bucket.skipped_locked.append(
                    {
                        "existing_id": existing_id,
                        "field": fname,
                        "incoming_value": incoming,
                    }
                )
                continue
            if verdict is Verdict.SKIPPED_VERIFIED:
                bucket.skipped_verified.append(
                    {
                        "existing_id": existing_id,
                        "field": fname,
                        "incoming_value": incoming,
                    }
                )
                continue

        if per_field_changes:
            bucket.would_update.append(
                {
                    "existing_id": existing_id,
                    "source_record_id": raw.source_record_id,
                    "changes": per_field_changes,
                }
            )

    return bucket


def _list_masters(organization_id: uuid.UUID, master_type: str) -> list[Any]:
    if master_type == MasterType.CUSTOMER:
        return list(CustomerMaster.objects.filter(organization_id=organization_id))
    return list(ItemMaster.objects.filter(organization_id=organization_id))


def _list_locks_by_master(organization_id: uuid.UUID, master_type: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    qs = MasterFieldLock.objects.filter(
        organization_id=organization_id, master_type=master_type
    ).values_list("master_id", "field_name")
    for master_id, field_name in qs:
        out.setdefault(str(master_id), set()).add(field_name)
    return out


def _match_master(
    master_type: str,
    record_fields: dict[str, str],
    existing_masters: list[Any],
):
    """Match an incoming record against the loaded master set.

    Customers: TIN exact match first (only when both sides have a
    TIN); fall back to canonical-name + alias case-insensitive
    match. Items: canonical-name + alias match (no TIN
    equivalent).
    """
    if master_type == MasterType.CUSTOMER:
        tin = (record_fields.get("tin") or "").strip()
        if tin:
            for m in existing_masters:
                if (m.tin or "").strip() == tin:
                    return m
        name = (record_fields.get("legal_name") or "").strip().lower()
        if not name:
            return None
        for m in existing_masters:
            if (m.legal_name or "").strip().lower() == name:
                return m
            for alias in m.aliases or []:
                if (alias or "").strip().lower() == name:
                    return m
        return None

    # Items
    name = (record_fields.get("canonical_name") or "").strip().lower()
    if not name:
        return None
    for m in existing_masters:
        if (m.canonical_name or "").strip().lower() == name:
            return m
        for alias in m.aliases or []:
            if (alias or "").strip().lower() == name:
                return m
    return None


# --- apply_sync_proposal ----------------------------------------------------


def apply_sync_proposal(
    *,
    proposal_id: uuid.UUID | str,
    actor_user_id: uuid.UUID | str,
) -> SyncProposal:
    """Write the auto-resolvable + would-add changes from a proposal.

    Records the pre-apply value of every changed field in
    ``applied_changes`` so ``revert_sync_proposal`` can walk it
    back. Does NOT touch the conflict rows — those wait on
    ``resolve_field_conflict``.
    """
    proposal = _load_proposal_for_write(proposal_id)
    if proposal.status != SyncProposal.Status.PROPOSED:
        raise SyncError(f"Cannot apply: proposal is in state '{proposal.status}', not 'proposed'.")

    config = proposal.integration_config
    source = CONNECTOR_SOURCE_MAP.get(config.connector_type, "")
    now_iso = timezone.now().isoformat()

    applied_changes: dict[str, list[dict]] = {
        "customers": {"created": [], "updated": []},
        "items": {"created": [], "updated": []},
    }

    with transaction.atomic():
        diff = proposal.diff or {}
        applied_changes["customers"]["created"] = _apply_would_add(
            organization_id=proposal.organization_id,
            master_type=MasterType.CUSTOMER,
            entries=diff.get("customers", {}).get("would_add", []),
            source=source,
            actor_user_id=actor_user_id,
            now_iso=now_iso,
            proposal_id=proposal.id,
        )
        applied_changes["customers"]["updated"] = _apply_would_update(
            organization_id=proposal.organization_id,
            master_type=MasterType.CUSTOMER,
            entries=diff.get("customers", {}).get("would_update", []),
            source=source,
            actor_user_id=actor_user_id,
            now_iso=now_iso,
            proposal_id=proposal.id,
        )
        applied_changes["items"]["created"] = _apply_would_add(
            organization_id=proposal.organization_id,
            master_type=MasterType.ITEM,
            entries=diff.get("items", {}).get("would_add", []),
            source=source,
            actor_user_id=actor_user_id,
            now_iso=now_iso,
            proposal_id=proposal.id,
        )
        applied_changes["items"]["updated"] = _apply_would_update(
            organization_id=proposal.organization_id,
            master_type=MasterType.ITEM,
            entries=diff.get("items", {}).get("would_update", []),
            source=source,
            actor_user_id=actor_user_id,
            now_iso=now_iso,
            proposal_id=proposal.id,
        )

        proposal.applied_changes = applied_changes
        proposal.applied_at = timezone.now()
        proposal.applied_by_user_id = actor_user_id
        proposal.status = SyncProposal.Status.APPLIED
        proposal.save(
            update_fields=[
                "applied_changes",
                "applied_at",
                "applied_by_user_id",
                "status",
            ]
        )
        config.last_sync_status = IntegrationConfig.LastSyncStatus.APPLIED
        config.save(update_fields=["last_sync_status", "updated_at"])

    record_event(
        action_type="integration.sync_applied",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(proposal.organization_id),
        affected_entity_type="SyncProposal",
        affected_entity_id=str(proposal.id),
        payload={
            "customers_created": len(applied_changes["customers"]["created"]),
            "customers_updated": len(applied_changes["customers"]["updated"]),
            "items_created": len(applied_changes["items"]["created"]),
            "items_updated": len(applied_changes["items"]["updated"]),
        },
    )

    _trigger_rematch_after_apply(
        organization_id=proposal.organization_id,
        proposal_id=proposal.id,
    )
    return proposal


def _apply_would_add(
    *,
    organization_id: uuid.UUID,
    master_type: str,
    entries: list[dict],
    source: str,
    actor_user_id: uuid.UUID | str,
    now_iso: str,
    proposal_id: uuid.UUID,
) -> list[dict]:
    """Create master rows for the would_add bucket."""
    created: list[dict] = []
    for entry in entries:
        fields = dict(entry.get("fields") or {})
        provenance = {
            fname: {
                "source": source,
                "synced_at": now_iso,
                "source_record_id": entry.get("source_record_id", ""),
                "applied_via_proposal_id": str(proposal_id),
                "approved_by": str(actor_user_id),
            }
            for fname, value in fields.items()
            if value
        }
        if master_type == MasterType.CUSTOMER:
            tin = fields.get("tin", "")
            tin_state = (
                CustomerMaster.TinVerificationState.UNVERIFIED_EXTERNAL_SOURCE
                if tin
                else CustomerMaster.TinVerificationState.UNVERIFIED
            )
            row = CustomerMaster.objects.create(
                organization_id=organization_id,
                legal_name=fields.get("legal_name") or "(no name)",
                tin=tin,
                tin_verification_state=tin_state,
                registration_number=fields.get("registration_number", ""),
                msic_code=fields.get("msic_code", ""),
                address=fields.get("address", ""),
                phone=fields.get("phone", ""),
                sst_number=fields.get("sst_number", ""),
                country_code=fields.get("country_code", ""),
                field_provenance=provenance,
            )
            created.append({"id": str(row.id)})
        else:
            row = ItemMaster.objects.create(
                organization_id=organization_id,
                canonical_name=fields.get("canonical_name") or "(no name)",
                default_msic_code=fields.get("default_msic_code", ""),
                default_classification_code=fields.get("default_classification_code", ""),
                default_tax_type_code=fields.get("default_tax_type_code", ""),
                default_unit_of_measurement=fields.get("default_unit_of_measurement", ""),
                field_provenance=provenance,
            )
            created.append({"id": str(row.id)})
    return created


def _apply_would_update(
    *,
    organization_id: uuid.UUID,
    master_type: str,
    entries: list[dict],
    source: str,
    actor_user_id: uuid.UUID | str,
    now_iso: str,
    proposal_id: uuid.UUID,
) -> list[dict]:
    """Apply per-field updates + capture pre-apply values for revert."""
    updated: list[dict] = []
    Model = CustomerMaster if master_type == MasterType.CUSTOMER else ItemMaster
    for entry in entries:
        existing_id = entry.get("existing_id")
        if not existing_id:
            continue
        try:
            row = Model.objects.get(id=existing_id)
        except Model.DoesNotExist:
            # Master was deleted between propose + apply. Skip;
            # don't fail the whole apply.
            logger.warning(
                "connectors.apply.master_missing",
                extra={
                    "master_id": existing_id,
                    "master_type": master_type,
                    "proposal_id": str(proposal_id),
                },
            )
            continue
        provenance = dict(row.field_provenance or {})
        prior_field_state: dict[str, dict[str, str]] = {}
        for fname, change in (entry.get("changes") or {}).items():
            prior = getattr(row, fname, "") or ""
            prior_provenance = provenance.get(fname, {}) or {}
            prior_field_state[fname] = {
                "value": prior,
                "provenance": prior_provenance,
            }
            setattr(row, fname, change.get("proposed", ""))
            provenance[fname] = {
                "source": source,
                "synced_at": now_iso,
                "source_record_id": entry.get("source_record_id", ""),
                "applied_via_proposal_id": str(proposal_id),
                "approved_by": str(actor_user_id),
            }
        row.field_provenance = provenance
        row.save()
        updated.append({"id": str(row.id), "prior": prior_field_state})
    return updated


# --- revert_sync_proposal --------------------------------------------------


def revert_sync_proposal(
    *,
    proposal_id: uuid.UUID | str,
    actor_user_id: uuid.UUID | str,
    reason: str,
) -> SyncProposal:
    """Walk applied_changes in reverse + restore prior state."""
    proposal = _load_proposal_for_write(proposal_id)
    if proposal.status != SyncProposal.Status.APPLIED:
        raise SyncError(f"Cannot revert: proposal is in state '{proposal.status}', not 'applied'.")
    if timezone.now() > proposal.expires_at:
        proposal.status = SyncProposal.Status.EXPIRED
        proposal.save(update_fields=["status"])
        raise RevertWindowExpired(
            f"Revert window expired (proposal applied "
            f"{proposal.applied_at.isoformat()}, expired "
            f"{proposal.expires_at.isoformat()})."
        )

    applied = proposal.applied_changes or {}
    with transaction.atomic():
        # Delete rows we created (in reverse order so cascading
        # cleanup is well-defined; today no cascades exist on
        # master rows).
        for kind, Model in (
            ("customers", CustomerMaster),
            ("items", ItemMaster),
        ):
            for created in applied.get(kind, {}).get("created", []):
                Model.objects.filter(id=created["id"]).delete()
            for updated in applied.get(kind, {}).get("updated", []):
                try:
                    row = Model.objects.get(id=updated["id"])
                except Model.DoesNotExist:
                    continue
                provenance = dict(row.field_provenance or {})
                for fname, prior in (updated.get("prior") or {}).items():
                    setattr(row, fname, prior.get("value", ""))
                    if prior.get("provenance"):
                        provenance[fname] = prior["provenance"]
                    else:
                        provenance.pop(fname, None)
                row.field_provenance = provenance
                row.save()

        proposal.reverted_at = timezone.now()
        proposal.reverted_by_user_id = actor_user_id
        proposal.status = SyncProposal.Status.REVERTED
        proposal.save(
            update_fields=[
                "reverted_at",
                "reverted_by_user_id",
                "status",
            ]
        )
        config = proposal.integration_config
        config.last_sync_status = IntegrationConfig.LastSyncStatus.REVERTED
        config.save(update_fields=["last_sync_status", "updated_at"])

    record_event(
        action_type="integration.sync_reverted",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(proposal.organization_id),
        affected_entity_type="SyncProposal",
        affected_entity_id=str(proposal.id),
        payload={"reason": (reason or "")[:255]},
    )

    _trigger_rematch_after_apply(
        organization_id=proposal.organization_id,
        proposal_id=proposal.id,
        triggered_by="connectors.sync_revert",
    )
    return proposal


# --- resolve_field_conflict ------------------------------------------------


def resolve_field_conflict(
    *,
    conflict_id: uuid.UUID | str,
    resolution: str,
    actor_user_id: uuid.UUID | str,
    custom_value: str | None = None,
) -> MasterFieldConflict:
    """Apply the user's choice from the conflict-queue UI."""
    if resolution not in {
        MasterFieldConflict.Resolution.KEEP_EXISTING,
        MasterFieldConflict.Resolution.TAKE_INCOMING,
        MasterFieldConflict.Resolution.KEEP_BOTH_AS_ALIASES,
        MasterFieldConflict.Resolution.ENTER_CUSTOM_VALUE,
    }:
        raise SyncError(f"Unknown resolution: {resolution}")
    if resolution == MasterFieldConflict.Resolution.ENTER_CUSTOM_VALUE and (
        custom_value is None or not str(custom_value).strip()
    ):
        raise SyncError("enter_custom_value requires a non-empty custom_value.")

    conflict = MasterFieldConflict.objects.select_related("sync_proposal").get(id=conflict_id)
    if not conflict.is_open:
        raise SyncError("Conflict is already resolved.")

    Model = CustomerMaster if conflict.master_type == MasterType.CUSTOMER else ItemMaster
    try:
        row = Model.objects.get(id=conflict.master_id)
    except Model.DoesNotExist:
        raise SyncError(f"Master record {conflict.master_id} no longer exists.")

    now_iso = timezone.now().isoformat()
    fname = conflict.field_name
    provenance = dict(row.field_provenance or {})

    if resolution == MasterFieldConflict.Resolution.KEEP_EXISTING:
        provenance[fname] = {
            "source": "manually_resolved",
            "entered_at": now_iso,
            "edited_by": str(actor_user_id),
            "kept_value": "existing",
        }
        # Value stays the same.
    elif resolution == MasterFieldConflict.Resolution.TAKE_INCOMING:
        setattr(row, fname, conflict.incoming_value)
        provenance[fname] = {
            **(conflict.incoming_provenance or {}),
            "applied_via_conflict_id": str(conflict.id),
            "approved_by": str(actor_user_id),
            "synced_at": now_iso,
        }
    elif resolution == MasterFieldConflict.Resolution.KEEP_BOTH_AS_ALIASES:
        # Only meaningful for the canonical-name field on each
        # master. Append the incoming value to aliases; canonical
        # name stays as-is.
        if conflict.master_type == MasterType.CUSTOMER and fname != "legal_name":
            raise SyncError("keep_both_as_aliases only applies to legal_name on customer masters.")
        if conflict.master_type == MasterType.ITEM and fname != "canonical_name":
            raise SyncError("keep_both_as_aliases only applies to canonical_name on item masters.")
        aliases = list(getattr(row, "aliases", []) or [])
        if conflict.incoming_value and conflict.incoming_value not in aliases:
            aliases.append(conflict.incoming_value)
        row.aliases = aliases
        provenance[fname] = {
            "source": "manually_resolved",
            "entered_at": now_iso,
            "edited_by": str(actor_user_id),
            "kept_value": "both_as_aliases",
        }
    else:  # ENTER_CUSTOM_VALUE
        setattr(row, fname, str(custom_value).strip())
        provenance[fname] = {
            "source": "manually_resolved",
            "entered_at": now_iso,
            "edited_by": str(actor_user_id),
        }

    # If the field is the TIN on a customer master + a manual choice
    # has been made, mark the verification state as
    # manually_resolved (Slice 73 enum).
    if (
        conflict.master_type == MasterType.CUSTOMER
        and fname == "tin"
        and isinstance(row, CustomerMaster)
    ):
        row.tin_verification_state = CustomerMaster.TinVerificationState.MANUALLY_RESOLVED
        row.tin_last_verified_at = timezone.now()

    row.field_provenance = provenance
    row.save()

    conflict.resolution = resolution
    conflict.resolved_at = timezone.now()
    conflict.resolved_by_user_id = actor_user_id
    conflict.custom_value = (
        str(custom_value).strip()
        if resolution == MasterFieldConflict.Resolution.ENTER_CUSTOM_VALUE
        else ""
    )
    conflict.save(
        update_fields=[
            "resolution",
            "resolved_at",
            "resolved_by_user_id",
            "custom_value",
        ]
    )

    record_event(
        action_type="master_record.conflict_resolved",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(conflict.organization_id),
        affected_entity_type="MasterFieldConflict",
        affected_entity_id=str(conflict.id),
        payload={
            "master_type": conflict.master_type,
            "field": fname,
            "resolution": resolution,
        },
    )
    return conflict


# --- lock / unlock ----------------------------------------------------------


def lock_field(
    *,
    organization_id: uuid.UUID | str,
    master_type: str,
    master_id: uuid.UUID | str,
    field_name: str,
    actor_user_id: uuid.UUID | str,
    reason: str = "",
) -> MasterFieldLock:
    """Pin one field on one master record so future syncs don't
    silently overwrite it. Idempotent — re-locking returns the
    existing row without re-emitting the audit event."""
    if master_type not in {MasterType.CUSTOMER, MasterType.ITEM}:
        raise SyncError(f"Unknown master_type: {master_type}")

    existing = MasterFieldLock.objects.filter(
        organization_id=organization_id,
        master_type=master_type,
        master_id=master_id,
        field_name=field_name,
    ).first()
    if existing is not None:
        return existing

    lock = MasterFieldLock.objects.create(
        organization_id=organization_id,
        master_type=master_type,
        master_id=master_id,
        field_name=field_name,
        locked_by_user_id=actor_user_id,
        reason=(reason or "")[:255],
    )
    record_event(
        action_type="master_record.field_locked",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(organization_id),
        affected_entity_type="MasterFieldLock",
        affected_entity_id=str(lock.id),
        payload={
            "master_type": master_type,
            "master_id": str(master_id),
            "field": field_name,
            "reason": (reason or "")[:255],
        },
    )
    return lock


def unlock_field(
    *,
    organization_id: uuid.UUID | str,
    master_type: str,
    master_id: uuid.UUID | str,
    field_name: str,
    actor_user_id: uuid.UUID | str,
) -> bool:
    """Remove the lock if present. Returns ``True`` iff a lock was
    actually removed (so the caller can avoid no-op audit churn)."""
    qs = MasterFieldLock.objects.filter(
        organization_id=organization_id,
        master_type=master_type,
        master_id=master_id,
        field_name=field_name,
    )
    locks = list(qs)
    if not locks:
        return False
    qs.delete()
    record_event(
        action_type="master_record.field_unlocked",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(organization_id),
        affected_entity_type="MasterFieldLock",
        affected_entity_id=str(locks[0].id),
        payload={
            "master_type": master_type,
            "master_id": str(master_id),
            "field": field_name,
        },
    )
    return True


# --- helpers ----------------------------------------------------------------


def _load_integration_config(
    config_id: uuid.UUID | str,
) -> IntegrationConfig:
    try:
        config = IntegrationConfig.objects.get(id=config_id)
    except IntegrationConfig.DoesNotExist:
        raise SyncError(f"IntegrationConfig {config_id} not found.")
    if config.deleted_at is not None:
        raise SyncError(f"IntegrationConfig {config_id} is soft-deleted.")
    return config


def _load_proposal_for_write(
    proposal_id: uuid.UUID | str,
) -> SyncProposal:
    try:
        return SyncProposal.objects.select_for_update().get(id=proposal_id)
    except SyncProposal.DoesNotExist:
        raise SyncError(f"SyncProposal {proposal_id} not found.")


def _trigger_rematch_after_apply(
    *,
    organization_id: uuid.UUID,
    proposal_id: uuid.UUID,
    triggered_by: str = "connectors.sync_apply",
) -> None:
    """Run the post-apply / post-revert re-match pass.

    Walks every ``ready_for_review`` invoice for the org + tries to
    re-match against the (now-updated) customer master set. Lifts
    get audited individually with
    ``invoice.master_match_lifted_by_sync``.
    """
    from apps.enrichment.rematch import rematch_pending_invoices

    result = rematch_pending_invoices(organization_id=organization_id, triggered_by=triggered_by)
    if result.lifted:
        record_event(
            action_type="connectors.rematch_completed",
            actor_type=AuditEvent.ActorType.SERVICE,
            actor_id="connectors.sync",
            organization_id=str(organization_id),
            affected_entity_type="SyncProposal",
            affected_entity_id=str(proposal_id),
            payload={
                "triggered_by": triggered_by,
                "rematched": result.rematched,
                "lifted": result.lifted,
                "fields_filled_total": result.fields_filled_total,
            },
        )
