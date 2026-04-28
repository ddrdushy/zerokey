"""DRF serializers for the enrichment context — the Customers UI surface."""

from __future__ import annotations

from rest_framework import serializers

from apps.submission.models import Invoice

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


class CustomerInvoiceSummarySerializer(serializers.ModelSerializer):
    """Compact Invoice shape for the customer-detail invoices list.

    Carries only what the Customers UI's "Invoices from this buyer"
    table renders. The full invoice payload is one click away via the
    ingestion job link.
    """

    class Meta:
        model = Invoice
        fields = [
            "id",
            "ingestion_job_id",
            "invoice_number",
            "issue_date",
            "currency_code",
            "grand_total",
            "status",
            "created_at",
        ]
        read_only_fields = fields
