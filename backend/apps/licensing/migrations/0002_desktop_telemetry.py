# Phase 6 of DESKTOP_PIVOT_PLAN.md — telemetry counters from the
# desktop. One row per license per day; counts only, no invoice data.

from __future__ import annotations

import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("licensing", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="DesktopTelemetry",
            fields=[
                (
                    "created_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now, editable=False
                    ),
                ),
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
                ("day", models.DateField(db_index=True)),
                ("invoices_ingested", models.IntegerField(default=0)),
                ("invoices_submitted", models.IntegerField(default=0)),
                ("invoices_failed", models.IntegerField(default=0)),
                ("consolidated_b2c_built", models.IntegerField(default=0)),
                (
                    "desktop_version",
                    models.CharField(blank=True, default="", max_length=32),
                ),
                (
                    "received_at",
                    models.DateTimeField(
                        db_index=True, default=django.utils.timezone.now
                    ),
                ),
                (
                    "received_ip",
                    models.GenericIPAddressField(blank=True, null=True),
                ),
                (
                    "license",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="telemetry",
                        to="licensing.license",
                    ),
                ),
            ],
            options={
                "db_table": "license_desktop_telemetry",
                "ordering": ["-day"],
            },
        ),
        migrations.AddConstraint(
            model_name="desktoptelemetry",
            constraint=models.UniqueConstraint(
                fields=("license", "day"),
                name="license_telemetry_one_per_day",
            ),
        ),
    ]
