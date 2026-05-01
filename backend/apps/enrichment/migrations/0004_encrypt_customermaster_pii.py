"""Encrypt PII at rest on CustomerMaster (Slice 95).

Mirror of submission/0012 — same pattern (AlterField + RunPython
data migration that walks rows and rewrites plaintext to ciphertext
under ``apps.administration.crypto.encrypt_value``).
"""

from django.db import migrations

from apps.administration.fields import EncryptedCharField, EncryptedTextField


_PII_FIELDS = ("phone", "sst_number", "address")


def _encrypt_existing_rows(apps, schema_editor):
    # Use live model (not the historical one from ``apps.get_model``)
    # so the EncryptedCharField/TextField subclasses' get_prep_value
    # auto-encrypts on save. encrypt_value is idempotent so re-running
    # is safe.
    from apps.enrichment.models import CustomerMaster
    from apps.identity.tenancy import super_admin_context

    rewritten = 0
    with super_admin_context(reason="slice_95.encrypt_customermaster_pii"):
        for row in CustomerMaster.objects.iterator():
            needs_rewrite = any(
                (getattr(row, name) or "") and not (getattr(row, name) or "").startswith("enc1:")
                for name in _PII_FIELDS
            )
            if not needs_rewrite:
                continue
            row.save(update_fields=list(_PII_FIELDS) + ["updated_at"])
            rewritten += 1
    if rewritten:
        print(f"  encrypted PII on {rewritten} customer_master row(s)")


class Migration(migrations.Migration):

    dependencies = [
        ("enrichment", "0003_field_provenance_and_states"),
    ]

    operations = [
        migrations.AlterField(
            model_name="customermaster",
            name="address",
            field=EncryptedTextField(blank=True, default=""),
        ),
        migrations.AlterField(
            model_name="customermaster",
            name="phone",
            field=EncryptedCharField(blank=True, default="", max_length=128),
        ),
        migrations.AlterField(
            model_name="customermaster",
            name="sst_number",
            field=EncryptedCharField(blank=True, default="", max_length=128),
        ),
        migrations.RunPython(_encrypt_existing_rows, migrations.RunPython.noop),
    ]
