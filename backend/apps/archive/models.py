"""Archive domain models — long-term retention surface.

Per LHDN_INTEGRATION.md §"Consolidated B2C invoice" the customer must
retain per-transaction detail for B2C consolidations even though the
LHDN-submitted invoice carries only the summary line. The archive is
where those details live, linked to the consolidated invoice's UUID.

Per DATA_MODEL.md §"Retention and deletion" we also archive
historical invoice snapshots on a 7-year retention schedule (LHDN
requirement) and source documents on a 1-year schedule.

Append-only at the application layer — services never UPDATE or
DELETE rows. The retention policy uses a ``deletion_pending`` flag
plus a future sweeper job rather than direct deletes so the audit
chain can always reconstruct what was once archived.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone

from apps.identity.models import TenantScopedModel


class ArchivedDocument(TenantScopedModel):
    """A retained snapshot of a document or summary.

    Two primary use cases:

      1. **Consolidated B2C transactions** — when a customer submits
         a monthly consolidated B2C invoice to LHDN, each underlying
         transaction is archived here keyed by ``parent_invoice_id``
         (the consolidated invoice's UUID). LHDN doesn't see these;
         a customer audit might.

      2. **Long-term invoice retention** — every customer invoice is
         archived as a JSON snapshot at ``submitted`` so the seven-
         year retention requirement is met even after the live
         ``Invoice`` row has been edited or deleted.

    Fields are deliberately broad (``document_type`` enum, JSON
    payload, optional S3 reference) so future archive use cases
    drop in without a migration.
    """

    class DocumentType(models.TextChoices):
        # The transaction-level detail behind a consolidated B2C invoice.
        B2C_TRANSACTION = "b2c_transaction", "B2C transaction (consolidated detail)"
        # Snapshot of a customer Invoice at a noteworthy state
        # transition (submitted, accepted by LHDN, etc).
        INVOICE_SNAPSHOT = "invoice_snapshot", "Invoice snapshot"
        # A customer-uploaded source document we keep beyond the
        # active ingestion window.
        INGESTION_SOURCE = "ingestion_source", "Ingestion source document"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    document_type = models.CharField(
        max_length=32,
        choices=DocumentType.choices,
        db_index=True,
    )

    related_entity_type = models.CharField(max_length=64, blank=True)
    related_entity_id = models.CharField(max_length=128, blank=True, db_index=True)

    # The consolidated invoice this row's transaction was rolled into,
    # if any. NULL for non-B2C archives.
    parent_invoice_id = models.UUIDField(null=True, blank=True, db_index=True)

    payload = models.JSONField(default=dict, blank=True)

    s3_object_key = models.CharField(max_length=512, blank=True)
    file_mime_type = models.CharField(max_length=128, blank=True)
    file_size = models.BigIntegerField(null=True, blank=True)

    retain_until = models.DateTimeField(null=True, blank=True, db_index=True)
    deletion_pending = models.BooleanField(default=False)

    archived_by_user_id = models.UUIDField(null=True, blank=True)
    archived_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "archive_document"
        ordering = ["-archived_at"]
        indexes = [
            models.Index(fields=["organization", "document_type", "-archived_at"]),
            models.Index(fields=["parent_invoice_id"]),
            models.Index(fields=["related_entity_type", "related_entity_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.document_type} on {self.organization_id} @ {self.archived_at.isoformat()}"
