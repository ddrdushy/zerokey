"""Invoice + LineItem — the structured business entity that flows through
extraction, enrichment, validation, signing, and submission to LHDN.

Per DATA_MODEL.md and LHDN_INTEGRATION.md the Invoice carries the LHDN
mandatory fields. Phase 2 covers the major fields needed to reach the
``ready_for_review`` state; specialised fields (consolidated B2C, self-billed,
foreign supplier) land later.

Cross-context placement: every other context (extraction, enrichment,
validation) reads/writes Invoice through ``apps.submission.services``.
The submission context owns the entity because the lifecycle peaks at
LHDN submission — that is where the Invoice gets a UUID, QR code, and
signed-XML pointer.

Confidence model: each field carries an extraction confidence in
``per_field_confidence`` (JSONB). The router escalates low-confidence
fields to vision in a later slice; for now, the review UI renders the
score so the user knows where to look.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone

from apps.identity.models import TenantScopedModel


class Invoice(TenantScopedModel):
    """One Invoice corresponds to one IngestionJob.

    Lifecycle mirrors IngestionJob.Status. We duplicate the column rather
    than dereferencing the job because the Invoice has its own write path
    (signing, submitting) that updates the status independently once the
    extraction phase is done.
    """

    class Direction(models.TextChoices):
        OUTBOUND = "outbound", "Outbound"
        INBOUND = "inbound", "Inbound"

    class InvoiceType(models.TextChoices):
        STANDARD = "standard", "Standard"
        CREDIT_NOTE = "credit_note", "Credit note"
        DEBIT_NOTE = "debit_note", "Debit note"
        REFUND_NOTE = "refund_note", "Refund note"
        SELF_BILLED = "self_billed", "Self-billed"

    class Status(models.TextChoices):
        # These mirror IngestionJob.Status so callers can switch on either.
        EXTRACTING = "extracting", "Extracting"
        ENRICHING = "enriching", "Enriching"
        VALIDATING = "validating", "Validating"
        READY_FOR_REVIEW = "ready_for_review", "Ready for review"
        AWAITING_APPROVAL = "awaiting_approval", "Awaiting approval"
        SIGNING = "signing", "Signing"
        SUBMITTING = "submitting", "Submitting"
        VALIDATED = "validated", "Validated by LHDN"
        REJECTED = "rejected", "Rejected by LHDN"
        CANCELLED = "cancelled", "Cancelled"
        ERROR = "error", "Error"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Soft FK by uuid to avoid coupling submission ← ingestion at the model level.
    # Service layer keeps the link consistent.
    ingestion_job_id = models.UUIDField(unique=True, db_index=True)

    direction = models.CharField(
        max_length=16, choices=Direction.choices, default=Direction.OUTBOUND
    )
    invoice_type = models.CharField(
        max_length=16, choices=InvoiceType.choices, default=InvoiceType.STANDARD
    )
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.READY_FOR_REVIEW, db_index=True
    )

    # --- Header --------------------------------------------------------------
    invoice_number = models.CharField(max_length=128, blank=True)
    issue_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    currency_code = models.CharField(max_length=3, default="MYR")
    payment_terms_code = models.CharField(max_length=32, blank=True)
    payment_reference = models.CharField(max_length=128, blank=True)

    # --- Supplier (the customer organisation issuing the invoice) -----------
    # On v1 these mirror the issuing Organization, but they are stored on the
    # invoice because legal-name and registration details may have been
    # different at issue time, and the audit trail wants the values as they
    # were on the invoice itself.
    supplier_legal_name = models.CharField(max_length=255, blank=True)
    supplier_tin = models.CharField(max_length=32, blank=True)
    supplier_registration_number = models.CharField(max_length=64, blank=True)
    supplier_msic_code = models.CharField(max_length=8, blank=True)
    supplier_address = models.TextField(blank=True)
    supplier_phone = models.CharField(max_length=32, blank=True)
    supplier_sst_number = models.CharField(max_length=32, blank=True)

    # --- Buyer ---------------------------------------------------------------
    buyer_legal_name = models.CharField(max_length=255, blank=True)
    buyer_tin = models.CharField(max_length=32, blank=True)
    buyer_registration_number = models.CharField(max_length=64, blank=True)
    buyer_msic_code = models.CharField(max_length=8, blank=True)
    buyer_address = models.TextField(blank=True)
    buyer_phone = models.CharField(max_length=32, blank=True)
    buyer_sst_number = models.CharField(max_length=32, blank=True)
    buyer_country_code = models.CharField(max_length=2, blank=True)

    # --- Totals --------------------------------------------------------------
    subtotal = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    total_tax = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    grand_total = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    myr_equivalent_total = models.DecimalField(
        max_digits=19, decimal_places=2, null=True, blank=True
    )
    discount_amount = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    discount_reason_code = models.CharField(max_length=32, blank=True)

    # --- Confidence ----------------------------------------------------------
    overall_confidence = models.FloatField(null=True, blank=True)
    per_field_confidence = models.JSONField(default=dict, blank=True)
    structuring_engine = models.CharField(max_length=128, blank=True)
    raw_extracted_text = models.TextField(blank=True)

    # --- Submission lifecycle (set after signing/LHDN response) -------------
    lhdn_uuid = models.CharField(max_length=64, blank=True, db_index=True)
    lhdn_qr_code_url = models.URLField(blank=True)
    signed_xml_s3_key = models.CharField(max_length=1024, blank=True)
    validation_timestamp = models.DateTimeField(null=True, blank=True)
    cancellation_timestamp = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        db_table = "invoice"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["organization", "invoice_number"]),
        ]

    def __str__(self) -> str:
        return f"{self.invoice_number or self.id} ({self.status})"


class LineItem(TenantScopedModel):
    """One line item on an invoice.

    Tenant-scoped directly (not just via parent Invoice) for defensive RLS:
    a JOIN bug that fails to filter through Invoice.organization can't leak
    line-item rows because the line_item table also enforces RLS itself.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="line_items")

    line_number = models.IntegerField()

    description = models.TextField(blank=True)
    unit_of_measurement = models.CharField(max_length=16, blank=True)
    quantity = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    unit_price_excl_tax = models.DecimalField(
        max_digits=19, decimal_places=2, null=True, blank=True
    )
    line_subtotal_excl_tax = models.DecimalField(
        max_digits=19, decimal_places=2, null=True, blank=True
    )

    tax_type_code = models.CharField(max_length=16, blank=True)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    tax_amount = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    line_total_incl_tax = models.DecimalField(
        max_digits=19, decimal_places=2, null=True, blank=True
    )

    classification_code = models.CharField(max_length=16, blank=True)
    discount_amount = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    discount_reason_code = models.CharField(max_length=32, blank=True)

    per_field_confidence = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "line_item"
        ordering = ["invoice", "line_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["invoice", "line_number"], name="uniq_line_per_invoice"
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "invoice"]),
        ]

    def __str__(self) -> str:
        return f"{self.invoice_id} L{self.line_number}: {self.description[:30]}"


class ExceptionInboxItem(TenantScopedModel):
    """An invoice flagged for human attention.

    Per DATA_MODEL.md "exception inbox entities", these are the queue
    items the operator works through to triage invoices that didn't
    sail straight through the pipeline. Auto-created when an invoice
    hits a "needs attention" condition (validation error, structuring
    skipped, low confidence, LHDN rejection); auto-resolved when the
    condition clears (e.g. user fixes the validation issue).

    Lives in submission because the entity is keyed by Invoice and the
    lifecycle is wound around Invoice state changes. The Inbox UI
    surface is a workflow view on top of this table.

    Idempotency: ``unique_together (invoice, reason)`` so a flapping
    condition doesn't create duplicate rows. A re-flap on a previously
    resolved row reopens it (back to ``status=open``) and clears the
    resolved_* fields.
    """

    class Reason(models.TextChoices):
        VALIDATION_FAILURE = "validation_failure", "Validation failure"
        STRUCTURING_SKIPPED = "structuring_skipped", "Structuring skipped"
        LOW_CONFIDENCE_EXTRACTION = (
            "low_confidence_extraction",
            "Low-confidence extraction",
        )
        LHDN_REJECTION = "lhdn_rejection", "Rejected by LHDN"
        MANUAL_REVIEW_REQUESTED = (
            "manual_review_requested",
            "Manual review requested",
        )

    class Priority(models.TextChoices):
        NORMAL = "normal", "Normal"
        URGENT = "urgent", "Urgent"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name="inbox_items"
    )

    reason = models.CharField(max_length=32, choices=Reason.choices, db_index=True)
    priority = models.CharField(
        max_length=8, choices=Priority.choices, default=Priority.NORMAL
    )
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )

    # Free-text context the rule layer can attach (e.g. "3 errors:
    # required.invoice_number, required.supplier_tin, ..."). Never carries PII;
    # codes only.
    detail = models.JSONField(default=dict, blank=True)

    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by_user_id = models.UUIDField(null=True, blank=True)
    resolution_note = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "exception_inbox_item"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["invoice", "reason"],
                name="uniq_inbox_item_per_invoice_reason",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status", "-created_at"]),
            models.Index(fields=["organization", "reason", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.reason} on {self.invoice_id} ({self.status})"


class ExtractionCorrection(TenantScopedModel):
    """One human correction to an extracted field.

    Per DATA_MODEL.md §93: when the user edits a value the extractor
    populated (or left blank), we capture the delta — original value,
    corrected value, who changed it, when. This is the persistence
    layer behind the "learn from corrections" product claim.

    Captured automatically inside ``apps.submission.services.update_invoice``
    on every header / line-item / addition / removal. The audit event
    ``invoice.updated`` already records the change as a *fact*; this
    table records it as *training data* — the rows are queryable for
    per-engine accuracy analysis, per-tenant correction-rate dashboards,
    and (eventually) feedback into the engine routing decision.

    Field naming convention:
      - Header field      → ``"<field>"`` e.g. ``"supplier_legal_name"``
      - Line-item field   → ``"line_items[<line_number>].<field>"``
        e.g. ``"line_items[3].quantity"``
      - Add (new line)    → ``"line_items[<line_number>]"`` with
        ``original_value=""`` and ``corrected_value="<json>"``
      - Remove (line)     → ``"line_items[<line_number>]"`` with
        ``corrected_value=""`` and ``original_value="<json>"``

    Storage: ``original_value`` + ``corrected_value`` are JSON-encoded
    strings (so a Decimal "100.00" and the string "100.00" are
    distinguishable). The field column is short enough that an index
    on (organization, field_name) makes per-field accuracy queries
    cheap.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="corrections",
    )

    field_name = models.CharField(max_length=128, db_index=True)

    # JSON-encoded "before" and "after" so type information survives
    # the round-trip (vs. plain strings where Decimal("100.0") and
    # "100.0" are indistinguishable).
    original_value = models.TextField(blank=True)
    corrected_value = models.TextField(blank=True)

    # Engine that produced ``original_value``, when known. Lets a future
    # report say "qwen3-coder corrected wrongly on supplier_tin 23% of
    # the time" without joining through Invoice.structuring_engine.
    extracted_by_engine = models.CharField(max_length=128, blank=True)

    # The user who made the correction. Soft FK by uuid so a user
    # deletion (rare; usually deactivated, not deleted) doesn't
    # cascade-delete the training data.
    user_id = models.UUIDField(null=True, blank=True, db_index=True)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "extraction_correction"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "field_name"]),
            models.Index(fields=["invoice", "-created_at"]),
            models.Index(fields=["extracted_by_engine", "field_name"]),
        ]

    def __str__(self) -> str:
        return f"{self.field_name} on {self.invoice_id} by {self.user_id}"
