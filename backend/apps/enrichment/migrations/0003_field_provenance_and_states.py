"""Slice 73 — per-field provenance + extended verification states.

Three operations land together so the table is in a coherent shape
after the migration runs:

1. ``CustomerMaster.field_provenance`` JSON column (default ``{}``)
   — per-field source/metadata. Backfill walks every existing row
   and marks each populated field as ``source: extracted`` with
   ``extracted_at = created_at`` since today every field on a
   CustomerMaster row originated from invoice extraction (the
   only path that creates rows is enrichment._enrich_customer).
2. ``ItemMaster.field_provenance`` JSON column with the same
   backfill semantics.
3. ``CustomerMaster.tin_verification_state`` enum extended with
   ``unverified_external_source`` (synced from connector) and
   ``manually_resolved`` (user picked in conflict queue). Existing
   ``unverified`` / ``verified`` / ``failed`` rows are unchanged.
   ``max_length`` bumped 16 → 32 to fit the longest new value.
"""

from __future__ import annotations

from django.db import migrations, models


# Field map per master — used by the backfill to walk only the
# fields that actually carry source-attributable values.
CUSTOMER_FIELDS: tuple[str, ...] = (
    "legal_name",
    "tin",
    "registration_number",
    "msic_code",
    "address",
    "phone",
    "sst_number",
    "country_code",
)

ITEM_FIELDS: tuple[str, ...] = (
    "canonical_name",
    "default_msic_code",
    "default_classification_code",
    "default_tax_type_code",
    "default_unit_of_measurement",
)


def _entry_for_extracted(when_iso: str) -> dict:
    return {"source": "extracted", "extracted_at": when_iso}


def backfill_provenance(apps, schema_editor):  # noqa: ARG001
    Customer = apps.get_model("enrichment", "CustomerMaster")
    Item = apps.get_model("enrichment", "ItemMaster")

    for row in Customer.objects.iterator():
        when = (row.created_at or row.updated_at).isoformat()
        prov: dict[str, dict] = row.field_provenance or {}
        for fname in CUSTOMER_FIELDS:
            value = getattr(row, fname, "")
            if value and fname not in prov:
                prov[fname] = _entry_for_extracted(when)
        if prov:
            row.field_provenance = prov
            row.save(update_fields=["field_provenance", "updated_at"])

    for row in Item.objects.iterator():
        when = (row.created_at or row.updated_at).isoformat()
        prov = row.field_provenance or {}
        for fname in ITEM_FIELDS:
            value = getattr(row, fname, "")
            if value and fname not in prov:
                prov[fname] = _entry_for_extracted(when)
        if prov:
            row.field_provenance = prov
            row.save(update_fields=["field_provenance", "updated_at"])


def reverse_backfill(apps, schema_editor):  # noqa: ARG001
    # Reversing the AddField column drop handles the JSON itself;
    # nothing else to undo.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("enrichment", "0002_rls_policies"),
    ]

    operations = [
        migrations.AddField(
            model_name="customermaster",
            name="field_provenance",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="itemmaster",
            name="field_provenance",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AlterField(
            model_name="customermaster",
            name="tin_verification_state",
            field=models.CharField(
                choices=[
                    ("unverified", "Unverified"),
                    (
                        "unverified_external_source",
                        "Unverified (from external source)",
                    ),
                    ("verified", "Verified"),
                    ("failed", "Failed verification"),
                    ("manually_resolved", "Manually resolved"),
                ],
                default="unverified",
                max_length=32,
            ),
        ),
        migrations.RunPython(backfill_provenance, reverse_backfill),
    ]
