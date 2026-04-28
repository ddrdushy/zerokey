"""DRF serializers for the customer-facing engine-activity surface."""

from __future__ import annotations

from rest_framework import serializers

from .models import EngineCall


class EngineSummarySerializer(serializers.Serializer):
    """Per-engine roll-up. Service builds the dict; we just declare the shape."""

    engine_name = serializers.CharField()
    vendor = serializers.CharField()
    capability = serializers.CharField()
    total_calls = serializers.IntegerField()
    success_count = serializers.IntegerField()
    failure_count = serializers.IntegerField()
    timeout_count = serializers.IntegerField()
    unavailable_count = serializers.IntegerField()
    success_rate = serializers.FloatField()
    avg_duration_ms = serializers.IntegerField()
    total_cost_micros = serializers.IntegerField()


class EngineCallSerializer(serializers.ModelSerializer):
    """Compact shape for the recent-calls table."""

    engine_name = serializers.CharField(source="engine.name", read_only=True)
    vendor = serializers.CharField(source="engine.vendor", read_only=True)

    class Meta:
        model = EngineCall
        fields = [
            "id",
            "engine_name",
            "vendor",
            "request_id",
            "started_at",
            "duration_ms",
            "outcome",
            "error_class",
            "cost_micros",
            "confidence",
            "diagnostics",
        ]
        read_only_fields = fields
