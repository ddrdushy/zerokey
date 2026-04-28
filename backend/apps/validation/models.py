"""Validation issue model.

Per LHDN_INTEGRATION.md the validation engine is the pre-flight gate
between extraction/structuring and signing/submission. It runs LHDN's
field-level rules locally so we catch the issues before LHDN does — the
"we caught it before LHDN did" UX promise from PRODUCT_VISION.md.

A ``ValidationIssue`` is one finding from one rule on one Invoice. The
review UI groups them by ``severity`` and ``field_path`` so the user
sees what to fix and where.

Tenant-scoped at the model level (RLS + an explicit ``organization`` FK)
to match the per-table CREATE POLICY pattern used elsewhere; defensive
isolation so a JOIN bug that fails to filter through Invoice can't leak
issue text from other customers.

Cross-context model imports are forbidden — call
``apps.validation.services`` from outside this app.
"""

from __future__ import annotations

import uuid

from django.db import models

from apps.identity.models import TenantScopedModel


class ValidationIssue(TenantScopedModel):
    """A single finding produced by a validation rule against an Invoice."""

    class Severity(models.TextChoices):
        # Submission-blocking. The user must fix before signing/submission.
        ERROR = "error", "Error"
        # Submission-allowed but worth flagging (e.g. due-date in the past).
        WARNING = "warning", "Warning"
        # Informational only (e.g. RM 10K threshold note for the user's awareness).
        INFO = "info", "Info"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Soft FK by uuid — same pattern as Invoice.ingestion_job_id.
    invoice_id = models.UUIDField(db_index=True)

    # Stable identifier per rule (e.g. "supplier.tin.format",
    # "totals.grand_total.mismatch", "rm10k.threshold"). Translatable
    # message strings live in the rules module; the code is the join key
    # used by the front-end translation layer.
    code = models.CharField(max_length=64, db_index=True)
    severity = models.CharField(max_length=8, choices=Severity.choices)

    # Dotted path identifying which field on the Invoice (or which line
    # item) the issue applies to. The review UI uses this to highlight
    # the offending field. Examples:
    #   "supplier_tin"
    #   "buyer_msic_code"
    #   "totals.grand_total"
    #   "line_items[2].quantity"
    field_path = models.CharField(max_length=128, blank=True, db_index=True)

    # Plain-language explanation per UX_PRINCIPLES.md principle 4
    # ("errors are explained, not announced"). Stored in English at
    # write time; the front-end maps ``code`` to the user's language
    # via the i18n catalog when richer locale handling lands.
    message = models.CharField(max_length=512)

    # Optional structured detail — actual vs expected, computed differences,
    # the upstream rule's machine-readable output. Surfaced in the UI's
    # "technical details" expandable section. Decimals are rendered as
    # strings to satisfy the audit-payload contract elsewhere.
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "validation_issue"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "invoice_id"]),
            models.Index(fields=["invoice_id", "severity"]),
        ]

    def __str__(self) -> str:
        return f"{self.severity}:{self.code} on invoice {self.invoice_id}"
