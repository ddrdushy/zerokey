# Generated for Slice 87 — two-step approval workflow.

import uuid

import django.db.models.deletion
from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):

    dependencies = [
        ("identity", "0016_approval_policy"),
        ("submission", "0009_invoice_submission_uid"),
    ]

    operations = [
        migrations.CreateModel(
            name="ApprovalRequest",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("requested_by_user_id", models.UUIDField(db_index=True)),
                (
                    "requested_at",
                    models.DateTimeField(db_index=True, default=timezone.now),
                ),
                ("requested_reason", models.TextField(blank=True)),
                (
                    "decided_by_user_id",
                    models.UUIDField(blank=True, db_index=True, null=True),
                ),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("decision_note", models.TextField(blank=True)),
                (
                    "invoice",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="approval_requests",
                        to="submission.invoice",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="identity.organization",
                    ),
                ),
            ],
            options={
                "db_table": "submission_approval_request",
                "ordering": ["-requested_at"],
                "indexes": [
                    models.Index(
                        fields=["organization", "status"],
                        name="submission__organiz_3a1d12_idx",
                    ),
                    models.Index(
                        fields=["invoice", "-requested_at"],
                        name="submission__invoice_92a6b1_idx",
                    ),
                ],
            },
        ),
    ]
