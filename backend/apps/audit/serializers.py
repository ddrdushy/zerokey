"""DRF serializers for the audit context.

The audit log page renders these. Hashes are bytes on the model; we expose
them as hex strings for the UI's "technical details" expandable section.
"""

from __future__ import annotations

from rest_framework import serializers

from .models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    content_hash = serializers.SerializerMethodField()
    chain_hash = serializers.SerializerMethodField()

    class Meta:
        model = AuditEvent
        fields = [
            "id",
            "sequence",
            "timestamp",
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

    def get_content_hash(self, obj: AuditEvent) -> str:
        return bytes(obj.content_hash).hex() if obj.content_hash else ""

    def get_chain_hash(self, obj: AuditEvent) -> str:
        return bytes(obj.chain_hash).hex() if obj.chain_hash else ""
