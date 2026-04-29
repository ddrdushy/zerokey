"""Model tests for SyncProposal / MasterFieldLock / MasterFieldConflict (Slice 74).

These cover schema-level invariants — uniqueness, default state,
reverse FK access. Service-level orchestration (propose / apply /
revert / resolve) lands in Slice 75.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.connectors.models import (
    IntegrationConfig,
    MasterFieldConflict,
    MasterFieldLock,
    MasterType,
    SyncProposal,
)
from apps.identity.models import Organization, Role


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org(seeded) -> Organization:
    return Organization.objects.create(
        legal_name="Conflict Test Sdn Bhd",
        tin="C2222222222",
        contact_email="ops@conflict.example",
    )


@pytest.fixture
def integration_config(org) -> IntegrationConfig:
    return IntegrationConfig.objects.create(
        organization=org,
        connector_type=IntegrationConfig.ConnectorType.AUTOCOUNT,
    )


# =============================================================================
# SyncProposal
# =============================================================================


@pytest.mark.django_db
class TestSyncProposalShape:
    def test_create_minimal(self, org, integration_config) -> None:
        actor = uuid.uuid4()
        proposal = SyncProposal.objects.create(
            organization=org,
            integration_config=integration_config,
            actor_user_id=actor,
            expires_at=timezone.now()
            + timedelta(days=SyncProposal.REVERT_WINDOW_DAYS),
            diff={"customers": {"would_add": []}},
        )
        assert proposal.id is not None
        assert proposal.status == SyncProposal.Status.PROPOSED
        assert proposal.applied_at is None
        assert proposal.reverted_at is None
        assert proposal.applied_changes == {}

    def test_protect_blocks_integration_config_delete(
        self, org, integration_config
    ) -> None:
        SyncProposal.objects.create(
            organization=org,
            integration_config=integration_config,
            actor_user_id=uuid.uuid4(),
            expires_at=timezone.now() + timedelta(days=14),
        )
        # IntegrationConfig is on_delete=PROTECT — can't hard-delete
        # while a proposal references it. Customers should soft-
        # delete the config (deleted_at) so historical proposals
        # stay readable.
        with pytest.raises(Exception):  # ProtectedError
            integration_config.delete()


# =============================================================================
# MasterFieldLock
# =============================================================================


@pytest.mark.django_db
class TestMasterFieldLockShape:
    def test_unique_per_master_field(self, org) -> None:
        master_id = uuid.uuid4()
        actor = uuid.uuid4()
        MasterFieldLock.objects.create(
            organization=org,
            master_type=MasterType.CUSTOMER,
            master_id=master_id,
            field_name="tin",
            locked_by_user_id=actor,
            reason="LHDN-verified, don't overwrite",
        )
        # Same (org, master_type, master_id, field_name) collides.
        with pytest.raises(IntegrityError):
            MasterFieldLock.objects.create(
                organization=org,
                master_type=MasterType.CUSTOMER,
                master_id=master_id,
                field_name="tin",
                locked_by_user_id=actor,
            )

    def test_different_field_same_master_ok(self, org) -> None:
        master_id = uuid.uuid4()
        MasterFieldLock.objects.create(
            organization=org,
            master_type=MasterType.CUSTOMER,
            master_id=master_id,
            field_name="tin",
            locked_by_user_id=uuid.uuid4(),
        )
        # Different field on the same master — OK.
        MasterFieldLock.objects.create(
            organization=org,
            master_type=MasterType.CUSTOMER,
            master_id=master_id,
            field_name="address",
            locked_by_user_id=uuid.uuid4(),
        )
        assert (
            MasterFieldLock.objects.filter(
                organization=org, master_id=master_id
            ).count()
            == 2
        )

    def test_customer_and_item_with_same_uuid_independent(self, org) -> None:
        # Defense-in-depth: master_id is a UUID — the chance of
        # collision between a CustomerMaster and ItemMaster is
        # vanishing, but the model treats them as distinct rows
        # via master_type. Verify the unique constraint scopes by
        # type.
        same_id = uuid.uuid4()
        MasterFieldLock.objects.create(
            organization=org,
            master_type=MasterType.CUSTOMER,
            master_id=same_id,
            field_name="tin",
            locked_by_user_id=uuid.uuid4(),
        )
        MasterFieldLock.objects.create(
            organization=org,
            master_type=MasterType.ITEM,
            master_id=same_id,
            field_name="tin",
            locked_by_user_id=uuid.uuid4(),
        )
        assert (
            MasterFieldLock.objects.filter(
                organization=org, master_id=same_id
            ).count()
            == 2
        )


# =============================================================================
# MasterFieldConflict
# =============================================================================


@pytest.mark.django_db
class TestMasterFieldConflictShape:
    def _make_proposal(self, org, integration_config) -> SyncProposal:
        return SyncProposal.objects.create(
            organization=org,
            integration_config=integration_config,
            actor_user_id=uuid.uuid4(),
            expires_at=timezone.now() + timedelta(days=14),
        )

    def test_open_conflict(self, org, integration_config) -> None:
        proposal = self._make_proposal(org, integration_config)
        master_id = uuid.uuid4()
        conflict = MasterFieldConflict.objects.create(
            organization=org,
            sync_proposal=proposal,
            master_type=MasterType.CUSTOMER,
            master_id=master_id,
            field_name="address",
            existing_value="Old",
            existing_provenance={"source": "extracted"},
            incoming_value="New",
            incoming_provenance={"source": "synced_autocount"},
        )
        assert conflict.is_open is True
        assert conflict.resolution == ""

    def test_resolution_round_trip(self, org, integration_config) -> None:
        proposal = self._make_proposal(org, integration_config)
        actor = uuid.uuid4()
        conflict = MasterFieldConflict.objects.create(
            organization=org,
            sync_proposal=proposal,
            master_type=MasterType.CUSTOMER,
            master_id=uuid.uuid4(),
            field_name="tin",
            existing_value="C9999999999",
            incoming_value="C8888888888",
        )
        conflict.resolution = MasterFieldConflict.Resolution.TAKE_INCOMING
        conflict.resolved_at = timezone.now()
        conflict.resolved_by_user_id = actor
        conflict.save()
        assert conflict.is_open is False
        assert (
            conflict.resolution == MasterFieldConflict.Resolution.TAKE_INCOMING
        )

    def test_cascade_from_proposal_deletes_conflicts(
        self, org, integration_config
    ) -> None:
        proposal = self._make_proposal(org, integration_config)
        for i in range(3):
            MasterFieldConflict.objects.create(
                organization=org,
                sync_proposal=proposal,
                master_type=MasterType.CUSTOMER,
                master_id=uuid.uuid4(),
                field_name=f"field_{i}",
            )
        # The integration_config is PROTECT; the conflicts are
        # CASCADE from proposal. To test cascade we delete the
        # proposal directly (which would only happen in a
        # rollback / hard-delete admin path).
        proposal.delete()
        assert MasterFieldConflict.objects.count() == 0
