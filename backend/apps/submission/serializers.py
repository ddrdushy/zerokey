"""DRF serializers for submission (Invoice / LineItem).

The Invoice response carries the validation-issue list so the review UI
gets the structured fields + the findings in a single round-trip. Cross-
context import of ``apps.validation.services`` is allowed (services-only,
never models — see ARCHITECTURE.md).
"""

from __future__ import annotations

from rest_framework import serializers

from apps.validation.services import issues_for_invoice

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


class ExceptionInboxItemSerializer(serializers.ModelSerializer):
    """Compact shape for the Inbox table.

    Embeds the small invoice context the table displays (number, buyer
    name, status, ingestion job for the click-through link). Full
    invoice payload is one click away.
    """

    invoice_id = serializers.UUIDField(source="invoice.id", read_only=True)
    ingestion_job_id = serializers.UUIDField(source="invoice.ingestion_job_id", read_only=True)
    invoice_number = serializers.CharField(source="invoice.invoice_number", read_only=True)
    invoice_status = serializers.CharField(source="invoice.status", read_only=True)
    buyer_legal_name = serializers.CharField(source="invoice.buyer_legal_name", read_only=True)

    class Meta:
        # Avoid the late-import; reach the model via the serializer field declarations.
        from .models import ExceptionInboxItem as _Model

        model = _Model
        fields = [
            "id",
            "reason",
            "priority",
            "status",
            "detail",
            "resolved_at",
            "resolved_by_user_id",
            "resolution_note",
            "created_at",
            "updated_at",
            "invoice_id",
            "ingestion_job_id",
            "invoice_number",
            "invoice_status",
            "buyer_legal_name",
        ]
        read_only_fields = fields


class InvoiceListSummarySerializer(serializers.ModelSerializer):
    """Compact Invoice shape for the all-invoices list page.

    Wider than the per-customer summary (Slice 19) because the all-
    invoices view doesn't have a buyer column header — every row needs
    to carry buyer_legal_name + buyer_tin so the table renders
    "who is this invoice from?" for each row.
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
            "buyer_legal_name",
            "buyer_tin",
            "status",
            "created_at",
        ]
        read_only_fields = fields


class ValidationIssueSerializer(serializers.Serializer):
    """Mirror of validation.ValidationIssue for embedding in the Invoice payload.

    Defined here rather than in apps.validation.serializers because the
    consumer is the Invoice review UI, and keeping the response shape
    co-located with InvoiceSerializer keeps the API surface obvious.
    """

    code = serializers.CharField()
    severity = serializers.CharField()
    field_path = serializers.CharField()
    message = serializers.CharField()
    detail = serializers.JSONField()


class InvoiceSerializer(serializers.ModelSerializer):
    line_items = LineItemSerializer(many=True, read_only=True)
    validation_issues = serializers.SerializerMethodField()
    validation_summary = serializers.SerializerMethodField()

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
            "supplier_id_type",
            "supplier_id_value",
            "buyer_legal_name",
            "buyer_tin",
            "buyer_registration_number",
            "buyer_msic_code",
            "buyer_address",
            "buyer_phone",
            "buyer_sst_number",
            "buyer_country_code",
            "buyer_id_type",
            "buyer_id_value",
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
            # Amendment fields (Slice 60/61)
            "original_invoice_uuid",
            "original_invoice_internal_id",
            "adjustment_reason",
            "error_message",
            "line_items",
            "validation_issues",
            "validation_summary",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_validation_issues(self, invoice: Invoice) -> list[dict]:
        rows = issues_for_invoice(organization_id=invoice.organization_id, invoice_id=invoice.id)
        return ValidationIssueSerializer(rows, many=True).data

    def get_validation_summary(self, invoice: Invoice) -> dict:
        rows = issues_for_invoice(organization_id=invoice.organization_id, invoice_id=invoice.id)
        summary = {"errors": 0, "warnings": 0, "infos": 0}
        for row in rows:
            if row.severity == "error":
                summary["errors"] += 1
            elif row.severity == "warning":
                summary["warnings"] += 1
            elif row.severity == "info":
                summary["infos"] += 1
        summary["has_blocking_errors"] = summary["errors"] > 0
        return summary
