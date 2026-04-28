"""DRF serializers for submission (Invoice / LineItem)."""

from __future__ import annotations

from rest_framework import serializers

from .models import Invoice, LineItem


class LineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = LineItem
        fields = [
            "id",
            "line_number",
            "description",
            "unit_of_measurement",
            "quantity",
            "unit_price_excl_tax",
            "line_subtotal_excl_tax",
            "tax_type_code",
            "tax_rate",
            "tax_amount",
            "line_total_incl_tax",
            "classification_code",
            "discount_amount",
            "discount_reason_code",
            "per_field_confidence",
        ]
        read_only_fields = fields


class InvoiceSerializer(serializers.ModelSerializer):
    line_items = LineItemSerializer(many=True, read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id",
            "ingestion_job_id",
            "direction",
            "invoice_type",
            "status",
            "invoice_number",
            "issue_date",
            "due_date",
            "currency_code",
            "payment_terms_code",
            "payment_reference",
            "supplier_legal_name",
            "supplier_tin",
            "supplier_registration_number",
            "supplier_msic_code",
            "supplier_address",
            "supplier_phone",
            "supplier_sst_number",
            "buyer_legal_name",
            "buyer_tin",
            "buyer_registration_number",
            "buyer_msic_code",
            "buyer_address",
            "buyer_phone",
            "buyer_sst_number",
            "buyer_country_code",
            "subtotal",
            "total_tax",
            "grand_total",
            "myr_equivalent_total",
            "discount_amount",
            "discount_reason_code",
            "overall_confidence",
            "per_field_confidence",
            "structuring_engine",
            "lhdn_uuid",
            "lhdn_qr_code_url",
            "validation_timestamp",
            "cancellation_timestamp",
            "error_message",
            "line_items",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
