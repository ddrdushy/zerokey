"""DRF serializers specific to the platform-admin surface.

Distinct from the customer-facing ``audit.serializers``: the admin view
needs ``organization_id`` on every row so the operator can see WHICH
tenant the event belongs to. The customer view never returns
organization_id (every event the customer sees is their own org by
construction).
"""

from __future__ import annotations

from rest_framework import serializers

from apps.audit.models import AuditEvent


class PlatformAuditEventSerializer(serializers.ModelSerializer):
    content_hash = serializers.SerializerMethodField()
    chain_hash = serializers.SerializerMethodField()
    organization_id = serializers.SerializerMethodField()

    class Meta:
        model = AuditEvent
        fields = [
            "id",
            "sequence",
            "timestamp",
            "organization_id",
            "actor_type",
            "actor_id",
            "action_type",
            "affected_entity_type",
            "affected_entity_id",
            "payload",
            "payload_schema_version",
            "content_hash",
            "chain_hash",
        ]
        read_only_fields = fields

    def get_organization_id(self, obj: AuditEvent) -> str | None:
        return str(obj.organization_id) if obj.organization_id else None

    def get_content_hash(self, obj: AuditEvent) -> str:
        return bytes(obj.content_hash).hex() if obj.content_hash else ""

    def get_chain_hash(self, obj: AuditEvent) -> str:
        return bytes(obj.chain_hash).hex() if obj.chain_hash else ""
