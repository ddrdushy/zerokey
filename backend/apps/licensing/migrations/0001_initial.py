# Phase 1 of DESKTOP_PIVOT_PLAN.md — licensing models.
#
# License is platform-wide (NOT tenant-scoped). The matching RLS policy
# we apply to other tenant tables does NOT apply here — Symprio operates
# this table directly.

from __future__ import annotations

import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("identity", "0023_organization_auto_submit"),
    ]

    operations = [
        migrations.CreateModel(
            name="License",
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
                ("organization_legal_name", models.CharField(max_length=255)),
                (
                    "organization_tin",
                    models.CharField(db_index=True, max_length=64, unique=True),
                ),
                (
                    "plan",
                    models.CharField(
                        choices=[
                            ("starter", "Starter"),
                            ("professional", "Professional"),
                            ("enterprise", "Enterprise"),
                        ],
                        default="starter",
                        max_length=32,
                    ),
                ),
                (
                    "key_hash",
                    models.CharField(db_index=True, max_length=64, unique=True),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "Active"),
                            ("suspended", "Suspended"),
                            ("revoked", "Revoked"),
                            ("expired", "Expired"),
                        ],
                        db_index=True,
                        default="active",
                        max_length=16,
                    ),
                ),
                (
                    "issued_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                ("expires_at", models.DateTimeField(db_index=True)),
                (
                    "bound_fingerprint_hash",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                ("bound_at", models.DateTimeField(blank=True, null=True)),
                ("last_heartbeat_at", models.DateTimeField(blank=True, null=True)),
                (
                    "last_heartbeat_ip",
                    models.GenericIPAddressField(blank=True, null=True),
                ),
                (
                    "last_desktop_version",
                    models.CharField(blank=True, default="", max_length=32),
                ),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("revoke_reason", models.TextField(blank=True, default="")),
                (
                    "owner_user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="owned_licenses",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "licenses",
                "ordering": ["-issued_at"],
            },
        ),
        migrations.AddIndex(
            model_name="license",
            index=models.Index(
                fields=["status", "expires_at"],
                name="licenses_status_expires_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="license",
            index=models.Index(
                fields=["owner_user", "status"],
                name="licenses_owner_status_idx",
            ),
        ),
        migrations.CreateModel(
            name="LicenseHeartbeat",
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
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("validate", "Validate"),
                            ("heartbeat", "Heartbeat"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "result",
                    models.CharField(
                        choices=[
                            ("ok", "OK"),
                            ("fingerprint_mismatch", "Fingerprint mismatch"),
                            ("revoked", "Revoked"),
                            ("expired", "Expired"),
                            ("suspended", "Suspended"),
                            ("unknown_key", "Unknown key"),
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "at",
                    models.DateTimeField(
                        db_index=True, default=django.utils.timezone.now
                    ),
                ),
                ("ip", models.GenericIPAddressField(blank=True, null=True)),
                (
                    "desktop_version",
                    models.CharField(blank=True, default="", max_length=32),
                ),
                (
                    "machine_fingerprint_hash",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                ("entitlement_id", models.UUIDField(blank=True, null=True)),
                (
                    "license",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="heartbeats",
                        to="licensing.license",
                    ),
                ),
            ],
            options={
                "db_table": "license_heartbeats",
                "ordering": ["-at"],
            },
        ),
    ]
