"""DRF serializers for the enrichment context — the Customers UI surface."""

from __future__ import annotations

from rest_framework import serializers

from .models import CustomerMaster


class CustomerMasterSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerMaster
        fields = [
            "id",
            "legal_name",
            "aliases",
            "tin",
            "tin_verification_state",
            "tin_last_verified_at",
            "registration_number",
            "msic_code",
            "address",
            "phone",
            "sst_number",
            "country_code",
            "usage_count",
            "last_used_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
