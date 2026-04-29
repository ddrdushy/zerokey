"""DRF serializers for the enrichment context — Customers + Items UI surfaces."""

from __future__ import annotations

from rest_framework import serializers

from apps.submission.models import Invoice

from .models import CustomerMaster, ItemMaster


class CustomerMasterSerializer(serializers.ModelSerializer):
    # Slice 81 — list of field names that have an active
    # MasterFieldLock for this row. The UI renders a lock icon
    # on each field; toggling it calls the
    # /connectors/locks/{,/unlock/} endpoint and refreshes.
    locked_fields = serializers.SerializerMethodField()

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
            # Slice 73 — per-field provenance map. The UI reads this
            # to render the "from AutoCount", "extracted", "entered
            # manually" pill next to each field.
            "field_provenance",
            # Slice 81 — per-field locks.
            "locked_fields",
            "usage_count",
            "last_used_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_locked_fields(self, obj: CustomerMaster) -> list[str]:
        # Imported lazily so the enrichment app doesn't load
        # connectors at import time (which would create an
        # apps-loading-order surprise on a clean migrate).
        from apps.connectors.models import MasterFieldLock, MasterType

        return list(
            MasterFieldLock.objects.filter(
                organization_id=obj.organization_id,
                master_type=MasterType.CUSTOMER,
                master_id=obj.id,
            ).values_list("field_name", flat=True)
        )


class ItemMasterSerializer(serializers.ModelSerializer):
    # Slice 83 — symmetric to CustomerMasterSerializer.locked_fields:
    # the Items UI renders a lock icon on each field; the click
    # toggles MasterFieldLock(master_type=item, master_id=row).
    locked_fields = serializers.SerializerMethodField()

    class Meta:
        model = ItemMaster
        fields = [
            "id",
            "canonical_name",
            "aliases",
            "default_msic_code",
            "default_classification_code",
            "default_tax_type_code",
            "default_unit_of_measurement",
            "default_unit_price_excl_tax",
            "field_provenance",
            "locked_fields",
            "usage_count",
            "last_used_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_locked_fields(self, obj: ItemMaster) -> list[str]:
        # Lazy import for the same apps-loading-order reason as
        # CustomerMasterSerializer.get_locked_fields.
        from apps.connectors.models import MasterFieldLock, MasterType

        return list(
            MasterFieldLock.objects.filter(
                organization_id=obj.organization_id,
                master_type=MasterType.ITEM,
                master_id=obj.id,
            ).values_list("field_name", flat=True)
        )


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
