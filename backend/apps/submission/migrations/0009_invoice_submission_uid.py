"""Slice 67 — split submission_uid off the signed_xml_s3_key kludge.

Slice 58 stashed LHDN's submission UID inside the
``signed_xml_s3_key`` column with the prefix ``submission_uid=`` so
the submit path could ship without a migration. This migration
adds a proper indexed column + backfills any existing rows + leaves
``signed_xml_s3_key`` alone (it'll be reused for the actual S3
key when signed-XML-at-rest lands).
"""

from __future__ import annotations

from django.db import migrations, models


def backfill_submission_uid(apps, schema_editor):
    Invoice = apps.get_model("submission", "Invoice")
    # Only rows that actually carry the kludge prefix get touched.
    # Anything else (legitimately empty, real S3 key) stays untouched.
    qs = Invoice.objects.filter(signed_xml_s3_key__startswith="submission_uid=")
    for invoice in qs.iterator():
        uid = (invoice.signed_xml_s3_key or "").removeprefix("submission_uid=").strip()
        if uid:
            invoice.submission_uid = uid[:64]
            invoice.signed_xml_s3_key = ""
            invoice.save(update_fields=["submission_uid", "signed_xml_s3_key"])


def reverse_backfill(apps, schema_editor):
    # Reversal puts the UID back into the kludge column. Used only
    # if we have to roll back this migration (rare).
    Invoice = apps.get_model("submission", "Invoice")
    qs = Invoice.objects.exclude(submission_uid="")
    for invoice in qs.iterator():
        invoice.signed_xml_s3_key = f"submission_uid={invoice.submission_uid}"
        invoice.submission_uid = ""
        invoice.save(update_fields=["submission_uid", "signed_xml_s3_key"])


class Migration(migrations.Migration):

    dependencies = [
        ("submission", "0008_party_id_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoice",
            name="submission_uid",
            field=models.CharField(
                blank=True, db_index=True, default="", max_length=64
            ),
            preserve_default=False,
        ),
        migrations.RunPython(backfill_submission_uid, reverse_backfill),
    ]
