"""Tests for the sync orchestration services (Slice 75)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.connectors import sync_services
from apps.connectors.models import (
    IntegrationConfig,
    MasterFieldConflict,
    MasterFieldLock,
    MasterType,
    SyncProposal,
)
from apps.connectors.sync_services import ConnectorRecord
from apps.enrichment.models import CustomerMaster, ItemMaster
from apps.identity.models import Organization, Role


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org(seeded) -> Organization:
    return Organization.objects.create(
        legal_name="Sync Service Test Sdn Bhd",
        tin="C2222222222",
        contact_email="ops@sync.example",
    )


@pytest.fixture
def config(org) -> IntegrationConfig:
    return IntegrationConfig.objects.create(
        organization=org,
        connector_type=IntegrationConfig.ConnectorType.AUTOCOUNT,
    )


def _record(
    *, source_id: str = "DEBT-1", **fields: str
) -> ConnectorRecord:
    return ConnectorRecord(source_record_id=source_id, fields=fields)


# =============================================================================
# propose_sync
# =============================================================================


@pytest.mark.django_db
class TestProposeSync:
    def test_unknown_buyer_goes_to_would_add(self, org, config) -> None:
        proposal = sync_services.propose_sync(
            integration_config_id=config.id,
            customer_records=[
                _record(
                    source_id="DEBT-1",
                    legal_name="Acme Sdn Bhd",
                    tin="C9999999999",
                    address="KL",
                ),
            ],
            actor_user_id=uuid.uuid4(),
        )
        diff = proposal.diff
        assert len(diff["customers"]["would_add"]) == 1
        assert diff["customers"]["would_add"][0]["fields"]["tin"] == "C9999999999"
        assert proposal.status == SyncProposal.Status.PROPOSED

    def test_existing_buyer_with_blank_field_auto_populates(
        self, org, config
    ) -> None:
        # Existing master with TIN + name only (no address).
        CustomerMaster.objects.create(
            organization=org,
            legal_name="Acme",
            tin="C9999999999",
            field_provenance={
                "legal_name": {"source": "extracted"},
                "tin": {"source": "extracted"},
            },
        )
        proposal = sync_services.propose_sync(
            integration_config_id=config.id,
            customer_records=[
                _record(
                    source_id="DEBT-1",
                    legal_name="Acme",
                    tin="C9999999999",
                    address="Now we have an address",
                ),
            ],
            actor_user_id=uuid.uuid4(),
        )
        # Match found — would_update with the address change.
        updates = proposal.diff["customers"]["would_update"]
        assert len(updates) == 1
        assert "address" in updates[0]["changes"]
        assert (
            updates[0]["changes"]["address"]["proposed"]
            == "Now we have an address"
        )
        # No conflict (existing was empty).
        assert proposal.diff["customers"]["conflicts"] == []

    def test_conflict_creates_conflict_row(self, org, config) -> None:
        master = CustomerMaster.objects.create(
            organization=org,
            legal_name="Acme",
            tin="C9999999999",
            address="Old address",
            field_provenance={
                "legal_name": {"source": "extracted"},
                "tin": {"source": "extracted"},
                "address": {"source": "manual"},  # user typed it
            },
        )
        actor = uuid.uuid4()
        proposal = sync_services.propose_sync(
            integration_config_id=config.id,
            customer_records=[
                _record(
                    source_id="DEBT-1",
                    legal_name="Acme",
                    tin="C9999999999",
                    address="New synced address",
                ),
            ],
            actor_user_id=actor,
        )
        # Diff carries the conflict.
        assert len(proposal.diff["customers"]["conflicts"]) == 1
        # Conflict row exists.
        row = MasterFieldConflict.objects.get(sync_proposal=proposal)
        assert row.field_name == "address"
        assert row.existing_value == "Old address"
        assert row.incoming_value == "New synced address"
        assert row.is_open is True

    def test_locked_field_routes_to_skipped_locked(
        self, org, config
    ) -> None:
        master = CustomerMaster.objects.create(
            organization=org,
            legal_name="Acme",
            tin="C9999999999",
            address="Original",
            field_provenance={
                "legal_name": {"source": "extracted"},
                "tin": {"source": "extracted"},
                "address": {"source": "extracted"},
            },
        )
        MasterFieldLock.objects.create(
            organization=org,
            master_type=MasterType.CUSTOMER,
            master_id=master.id,
            field_name="address",
            locked_by_user_id=uuid.uuid4(),
        )
        proposal = sync_services.propose_sync(
            integration_config_id=config.id,
            customer_records=[
                _record(
                    source_id="DEBT-1",
                    legal_name="Acme",
                    tin="C9999999999",
                    address="Connector wants to change this",
                ),
            ],
            actor_user_id=uuid.uuid4(),
        )
        skipped = proposal.diff["customers"]["skipped_locked"]
        assert len(skipped) == 1
        assert skipped[0]["field"] == "address"
        # No conflict row was created (locked != conflict).
        assert MasterFieldConflict.objects.count() == 0

    def test_verified_tin_routes_to_skipped_verified(
        self, org, config
    ) -> None:
        master = CustomerMaster.objects.create(
            organization=org,
            legal_name="Acme",
            tin="C9999999999",
            tin_verification_state=CustomerMaster.TinVerificationState.VERIFIED,
            field_provenance={
                "legal_name": {"source": "extracted"},
                "tin": {"source": "extracted"},
            },
        )
        proposal = sync_services.propose_sync(
            integration_config_id=config.id,
            customer_records=[
                _record(
                    source_id="DEBT-1",
                    legal_name="Acme",
                    tin="C8888888888",  # connector wants to overwrite
                ),
            ],
            actor_user_id=uuid.uuid4(),
        )
        skipped = proposal.diff["customers"]["skipped_verified"]
        assert any(s["field"] == "tin" for s in skipped)

    def test_audit_event_emitted(self, org, config) -> None:
        sync_services.propose_sync(
            integration_config_id=config.id,
            customer_records=[
                _record(source_id="DEBT-1", legal_name="X", tin="C1111111111"),
            ],
            actor_user_id=uuid.uuid4(),
        )
        ev = AuditEvent.objects.filter(
            action_type="integration.sync_proposed"
        ).first()
        assert ev is not None
        assert ev.payload["customers"]["would_add"] == 1


# =============================================================================
# apply_sync_proposal
# =============================================================================


@pytest.mark.django_db
class TestApplySyncProposal:
    def test_creates_new_master(self, org, config) -> None:
        actor = uuid.uuid4()
        proposal = sync_services.propose_sync(
            integration_config_id=config.id,
            customer_records=[
                _record(
                    source_id="DEBT-1",
                    legal_name="Brand New",
                    tin="C7777777777",
                    address="Address",
                ),
            ],
            actor_user_id=actor,
        )
        sync_services.apply_sync_proposal(
            proposal_id=proposal.id, actor_user_id=actor
        )
        master = CustomerMaster.objects.get(tin="C7777777777")
        assert master.legal_name == "Brand New"
        # New rows from sync get unverified_external_source.
        assert (
            master.tin_verification_state
            == CustomerMaster.TinVerificationState.UNVERIFIED_EXTERNAL_SOURCE
        )
        # Provenance is set with source_record_id + approved_by.
        assert master.field_provenance["tin"]["source"] == "synced_autocount"
        assert (
            master.field_provenance["tin"]["source_record_id"] == "DEBT-1"
        )

    def test_applies_would_update(self, org, config) -> None:
        existing = CustomerMaster.objects.create(
            organization=org,
            legal_name="Acme",
            tin="C9999999999",
            field_provenance={
                "legal_name": {"source": "extracted"},
                "tin": {"source": "extracted"},
            },
        )
        actor = uuid.uuid4()
        proposal = sync_services.propose_sync(
            integration_config_id=config.id,
            customer_records=[
                _record(
                    source_id="DEBT-1",
                    legal_name="Acme",
                    tin="C9999999999",
                    address="New from sync",
                ),
            ],
            actor_user_id=actor,
        )
        sync_services.apply_sync_proposal(
            proposal_id=proposal.id, actor_user_id=actor
        )
        existing.refresh_from_db()
        assert existing.address == "New from sync"
        # Provenance flipped to synced_autocount.
        assert (
            existing.field_provenance["address"]["source"]
            == "synced_autocount"
        )
        # applied_changes captured the prior value for revert.
        proposal.refresh_from_db()
        prior = proposal.applied_changes["customers"]["updated"][0]["prior"]
        assert prior["address"]["value"] == ""

    def test_refuses_double_apply(self, org, config) -> None:
        actor = uuid.uuid4()
        proposal = sync_services.propose_sync(
            integration_config_id=config.id,
            customer_records=[
                _record(source_id="DEBT-1", legal_name="X", tin="C1111111111"),
            ],
            actor_user_id=actor,
        )
        sync_services.apply_sync_proposal(
            proposal_id=proposal.id, actor_user_id=actor
        )
        with pytest.raises(sync_services.SyncError, match="proposed"):
            sync_services.apply_sync_proposal(
                proposal_id=proposal.id, actor_user_id=actor
            )

    def test_audit_event_emitted_with_counts(self, org, config) -> None:
        actor = uuid.uuid4()
        proposal = sync_services.propose_sync(
            integration_config_id=config.id,
            customer_records=[
                _record(source_id="A", legal_name="A", tin="C1111111111"),
                _record(source_id="B", legal_name="B", tin="C2222222222"),
            ],
            actor_user_id=actor,
        )
        sync_services.apply_sync_proposal(
            proposal_id=proposal.id, actor_user_id=actor
        )
        ev = AuditEvent.objects.filter(
            action_type="integration.sync_applied"
        ).first()
        assert ev is not None
        assert ev.payload["customers_created"] == 2


# =============================================================================
# revert_sync_proposal
# =============================================================================


@pytest.mark.django_db
class TestRevertSyncProposal:
    def test_revert_undoes_creates(self, org, config) -> None:
        actor = uuid.uuid4()
        proposal = sync_services.propose_sync(
            integration_config_id=config.id,
            customer_records=[
                _record(source_id="DEBT-1", legal_name="New", tin="C1111111111"),
            ],
            actor_user_id=actor,
        )
        sync_services.apply_sync_proposal(
            proposal_id=proposal.id, actor_user_id=actor
        )
        assert CustomerMaster.objects.count() == 1
        sync_services.revert_sync_proposal(
            proposal_id=proposal.id,
            actor_user_id=actor,
            reason="bad export",
        )
        # Created row was deleted.
        assert CustomerMaster.objects.count() == 0
        proposal.refresh_from_db()
        assert proposal.status == SyncProposal.Status.REVERTED

    def test_revert_restores_updated_fields(self, org, config) -> None:
        existing = CustomerMaster.objects.create(
            organization=org,
            legal_name="Acme",
            tin="C9999999999",
            address="Original address",
            field_provenance={
                "legal_name": {"source": "extracted"},
                "tin": {"source": "extracted"},
                "address": {"source": "extracted"},
            },
        )
        actor = uuid.uuid4()
        proposal = sync_services.propose_sync(
            integration_config_id=config.id,
            customer_records=[
                _record(
                    source_id="DEBT-1",
                    legal_name="Acme",
                    tin="C9999999999",
                    address="Synced address",
                ),
            ],
            actor_user_id=actor,
        )
        # Address was unchanged → no would_update; address was empty?
        # No — address was "Original address" (not empty), and incoming
        # is "Synced address" → conflict, NOT auto. So apply doesn't
        # change the address. Re-test with auto_populate path: clear
        # the existing address first.
        existing.address = ""
        existing.field_provenance.pop("address", None)
        existing.save()

        proposal2 = sync_services.propose_sync(
            integration_config_id=config.id,
            customer_records=[
                _record(
                    source_id="DEBT-1",
                    legal_name="Acme",
                    tin="C9999999999",
                    address="Synced address",
                ),
            ],
            actor_user_id=actor,
        )
        sync_services.apply_sync_proposal(
            proposal_id=proposal2.id, actor_user_id=actor
        )
        existing.refresh_from_db()
        assert existing.address == "Synced address"

        sync_services.revert_sync_proposal(
            proposal_id=proposal2.id,
            actor_user_id=actor,
            reason="reconsidered",
        )
        existing.refresh_from_db()
        # Reverted to the original blank.
        assert existing.address == ""

    def test_refuses_revert_outside_window(self, org, config) -> None:
        actor = uuid.uuid4()
        proposal = sync_services.propose_sync(
            integration_config_id=config.id,
            customer_records=[
                _record(source_id="DEBT-1", legal_name="X", tin="C1111111111"),
            ],
            actor_user_id=actor,
        )
        sync_services.apply_sync_proposal(
            proposal_id=proposal.id, actor_user_id=actor
        )
        # Push expires_at into the past.
        proposal.refresh_from_db()
        proposal.expires_at = timezone.now() - timedelta(days=1)
        proposal.save()

        with pytest.raises(sync_services.RevertWindowExpired):
            sync_services.revert_sync_proposal(
                proposal_id=proposal.id,
                actor_user_id=actor,
                reason="too late",
            )
        proposal.refresh_from_db()
        assert proposal.status == SyncProposal.Status.EXPIRED


# =============================================================================
# resolve_field_conflict
# =============================================================================


@pytest.mark.django_db
class TestResolveFieldConflict:
    def _make_conflict_setup(self, org, config):
        master = CustomerMaster.objects.create(
            organization=org,
            legal_name="Acme",
            tin="C9999999999",
            address="Old address",
            field_provenance={
                "legal_name": {"source": "extracted"},
                "tin": {"source": "extracted"},
                "address": {"source": "manual"},
            },
        )
        actor = uuid.uuid4()
        proposal = sync_services.propose_sync(
            integration_config_id=config.id,
            customer_records=[
                _record(
                    source_id="DEBT-1",
                    legal_name="Acme",
                    tin="C9999999999",
                    address="New from connector",
                ),
            ],
            actor_user_id=actor,
        )
        conflict = MasterFieldConflict.objects.get(sync_proposal=proposal)
        return master, conflict, actor

    def test_keep_existing_does_not_change_value(self, org, config) -> None:
        master, conflict, actor = self._make_conflict_setup(org, config)
        sync_services.resolve_field_conflict(
            conflict_id=conflict.id,
            resolution=MasterFieldConflict.Resolution.KEEP_EXISTING,
            actor_user_id=actor,
        )
        master.refresh_from_db()
        assert master.address == "Old address"
        assert (
            master.field_provenance["address"]["source"] == "manually_resolved"
        )

    def test_take_incoming_overwrites_value(self, org, config) -> None:
        master, conflict, actor = self._make_conflict_setup(org, config)
        sync_services.resolve_field_conflict(
            conflict_id=conflict.id,
            resolution=MasterFieldConflict.Resolution.TAKE_INCOMING,
            actor_user_id=actor,
        )
        master.refresh_from_db()
        assert master.address == "New from connector"

    def test_enter_custom_value_requires_value(self, org, config) -> None:
        master, conflict, actor = self._make_conflict_setup(org, config)
        with pytest.raises(sync_services.SyncError, match="custom_value"):
            sync_services.resolve_field_conflict(
                conflict_id=conflict.id,
                resolution=MasterFieldConflict.Resolution.ENTER_CUSTOM_VALUE,
                actor_user_id=actor,
            )

    def test_enter_custom_value_applies(self, org, config) -> None:
        master, conflict, actor = self._make_conflict_setup(org, config)
        sync_services.resolve_field_conflict(
            conflict_id=conflict.id,
            resolution=MasterFieldConflict.Resolution.ENTER_CUSTOM_VALUE,
            actor_user_id=actor,
            custom_value="Curated address",
        )
        master.refresh_from_db()
        assert master.address == "Curated address"

    def test_resolving_twice_rejected(self, org, config) -> None:
        master, conflict, actor = self._make_conflict_setup(org, config)
        sync_services.resolve_field_conflict(
            conflict_id=conflict.id,
            resolution=MasterFieldConflict.Resolution.KEEP_EXISTING,
            actor_user_id=actor,
        )
        with pytest.raises(sync_services.SyncError, match="already resolved"):
            sync_services.resolve_field_conflict(
                conflict_id=conflict.id,
                resolution=MasterFieldConflict.Resolution.TAKE_INCOMING,
                actor_user_id=actor,
            )

    def test_audit_event_emitted(self, org, config) -> None:
        master, conflict, actor = self._make_conflict_setup(org, config)
        sync_services.resolve_field_conflict(
            conflict_id=conflict.id,
            resolution=MasterFieldConflict.Resolution.KEEP_EXISTING,
            actor_user_id=actor,
        )
        ev = AuditEvent.objects.filter(
            action_type="master_record.conflict_resolved"
        ).first()
        assert ev is not None
        assert ev.payload["resolution"] == "keep_existing"


# =============================================================================
# lock / unlock
# =============================================================================


@pytest.mark.django_db
class TestLockUnlock:
    def test_lock_creates_row_and_audit(self, org) -> None:
        master_id = uuid.uuid4()
        actor = uuid.uuid4()
        lock = sync_services.lock_field(
            organization_id=org.id,
            master_type=MasterType.CUSTOMER,
            master_id=master_id,
            field_name="tin",
            actor_user_id=actor,
            reason="LHDN-verified",
        )
        assert lock.id is not None
        ev = AuditEvent.objects.filter(
            action_type="master_record.field_locked"
        ).first()
        assert ev is not None

    def test_lock_idempotent(self, org) -> None:
        master_id = uuid.uuid4()
        actor = uuid.uuid4()
        first = sync_services.lock_field(
            organization_id=org.id,
            master_type=MasterType.CUSTOMER,
            master_id=master_id,
            field_name="tin",
            actor_user_id=actor,
        )
        second = sync_services.lock_field(
            organization_id=org.id,
            master_type=MasterType.CUSTOMER,
            master_id=master_id,
            field_name="tin",
            actor_user_id=actor,
        )
        assert first.id == second.id
        # Only one audit event (re-locking returns existing without
        # re-emitting).
        events = AuditEvent.objects.filter(
            action_type="master_record.field_locked"
        ).count()
        assert events == 1

    def test_unlock_removes_row(self, org) -> None:
        master_id = uuid.uuid4()
        actor = uuid.uuid4()
        sync_services.lock_field(
            organization_id=org.id,
            master_type=MasterType.CUSTOMER,
            master_id=master_id,
            field_name="tin",
            actor_user_id=actor,
        )
        removed = sync_services.unlock_field(
            organization_id=org.id,
            master_type=MasterType.CUSTOMER,
            master_id=master_id,
            field_name="tin",
            actor_user_id=actor,
        )
        assert removed is True
        assert MasterFieldLock.objects.count() == 0

    def test_unlock_no_op_when_not_locked(self, org) -> None:
        removed = sync_services.unlock_field(
            organization_id=org.id,
            master_type=MasterType.CUSTOMER,
            master_id=uuid.uuid4(),
            field_name="tin",
            actor_user_id=uuid.uuid4(),
        )
        assert removed is False
        # No audit event for a no-op.
        events = AuditEvent.objects.filter(
            action_type="master_record.field_unlocked"
        ).count()
        assert events == 0
