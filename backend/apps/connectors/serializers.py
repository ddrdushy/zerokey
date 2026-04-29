"""DRF serializers for the connectors API surface."""

from __future__ import annotations

from rest_framework import serializers

from .models import (
    IntegrationConfig,
    MasterFieldConflict,
    MasterFieldLock,
    SyncProposal,
)


class IntegrationConfigSerializer(serializers.ModelSerializer):
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = IntegrationConfig
        fields = [
            "id",
            "connector_type",
            "sync_cadence",
            "auto_apply",
            "last_sync_at",
            "last_sync_status",
            "last_sync_error",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class SyncProposalSerializer(serializers.ModelSerializer):
    class Meta:
        model = SyncProposal
        fields = [
            "id",
            "integration_config",
            "actor_user_id",
            "status",
            "proposed_at",
            "expires_at",
            "applied_at",
            "applied_by_user_id",
            "reverted_at",
            "reverted_by_user_id",
            "diff",
        ]
        read_only_fields = fields


class MasterFieldConflictSerializer(serializers.ModelSerializer):
    is_open = serializers.BooleanField(read_only=True)

    class Meta:
        model = MasterFieldConflict
        fields = [
            "id",
            "sync_proposal",
            "master_type",
            "master_id",
            "field_name",
            "existing_value",
            "existing_provenance",
            "incoming_value",
            "incoming_provenance",
            "resolution",
            "custom_value",
            "resolved_at",
            "resolved_by_user_id",
            "is_open",
        ]
        read_only_fields = fields


class MasterFieldLockSerializer(serializers.ModelSerializer):
    class Meta:
        model = MasterFieldLock
        fields = [
            "id",
            "master_type",
            "master_id",
            "field_name",
            "locked_by_user_id",
            "locked_at",
            "reason",
        ]
        read_only_fields = fields
