"""Phase 2 of PORTAL_PLAN.md — connector document-pull cursor.

Tracks "what's the most recent invoice / CN / DN we've pulled from
each connector". The pull service reads the cursor, asks the adapter
for documents issued *after* it, ingests each one, then advances the
cursor.

Per-connector and per-document-type — separate cursors for invoices,
credit notes, and debit notes so a backfill on one document type
doesn't reset the others.
"""

from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("connectors", "0005_add_sql_account_sage_ubs_connector_types"),
    ]

    operations = [
        migrations.CreateModel(
            name="ConnectorPullCursor",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("organization_id", models.UUIDField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "integration_config",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="pull_cursors",
                        to="connectors.integrationconfig",
                    ),
                ),
                (
                    "document_type",
                    models.CharField(
                        choices=[
                            ("invoice", "Invoice"),
                            ("credit_note", "Credit note"),
                            ("debit_note", "Debit note"),
                        ],
                        max_length=16,
                    ),
                ),
                # Highest external-system reference we've successfully
                # ingested for this connector + document type. Adapters
                # treat it as opaque — could be a date string, a row id,
                # an issue number. The adapter compares using its own
                # ordering when answering "give me docs after X".
                ("last_external_ref", models.CharField(blank=True, default="", max_length=255)),
                ("last_pulled_at", models.DateTimeField(blank=True, null=True)),
                ("last_pull_status", models.CharField(blank=True, default="", max_length=32)),
                ("last_pull_count", models.IntegerField(default=0)),
                ("last_pull_error", models.TextField(blank=True, default="")),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=["integration_config", "document_type"],
                        name="unique_cursor_per_connector_and_doc_type",
                    ),
                ],
            },
        ),
    ]
