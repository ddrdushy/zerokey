"""Encrypt PII at rest on Invoice (Slice 95).

Two parts:

  1. AlterField on the eight PII columns to switch from
     ``CharField`` / ``TextField`` to the encrypted subclasses. The
     underlying SQL column type stays VARCHAR / TEXT (we just bump
     max_length to fit the ~150 % ciphertext bloat on CharField
     columns); the change is purely at the ORM layer.
  2. RunPython data migration that walks every existing row and
     re-saves the PII fields. ``EncryptedCharField.get_prep_value``
     calls ``encrypt_value`` (idempotent on already-encrypted
     strings), so plaintext rows become ciphertext on save and
     re-runs are no-ops.

Reverse path: ``RunPython.noop`` for the data migration. We don't
re-write ciphertext to plaintext on rollback — if you need to
undo the encryption, restore from backup. Reversing the schema
``AlterField`` is the standard Django reversal (back to plain
CharField / TextField).
"""

from django.db import migrations, models

from apps.administration.fields import EncryptedCharField, EncryptedTextField


_PII_FIELDS = (
    "supplier_phone",
    "supplier_sst_number",
    "supplier_address",
    "supplier_id_value",
    "buyer_phone",
    "buyer_sst_number",
    "buyer_address",
    "buyer_id_value",
)


def _encrypt_existing_rows(apps, schema_editor):
    # We CAN'T use ``apps.get_model`` here — the historical model has
    # plain CharField/TextField on the PII columns and won't auto-
    # encrypt on save. Use the live model so the EncryptedCharField
    # subclass's ``get_prep_value`` (= ``encrypt_value``) fires on
    # every write. ``encrypt_value`` is idempotent on already-
    # encrypted strings so a re-run is a no-op.
    from apps.identity.tenancy import super_admin_context
    from apps.submission.models import Invoice

    rewritten = 0
    with super_admin_context(reason="slice_95.encrypt_invoice_pii"):
        for row in Invoice.objects.iterator():
            needs_rewrite = any(
                (getattr(row, name) or "") and not (getattr(row, name) or "").startswith("enc1:")
                for name in _PII_FIELDS
            )
            if not needs_rewrite:
                continue
            row.save(update_fields=list(_PII_FIELDS) + ["updated_at"])
            rewritten += 1
    if rewritten:
        print(f"  encrypted PII on {rewritten} invoice row(s)")


class Migration(migrations.Migration):

    dependencies = [
        ("submission", "0011_invoice_amendment_field_defaults"),
    ]

    operations = [
        migrations.AlterField(
            model_name="invoice",
            name="supplier_address",
            field=EncryptedTextField(blank=True, default=""),
        ),
        migrations.AlterField(
            model_name="invoice",
            name="supplier_phone",
            field=EncryptedCharField(blank=True, default="", max_length=128),
        ),
        migrations.AlterField(
            model_name="invoice",
            name="supplier_sst_number",
            field=EncryptedCharField(blank=True, default="", max_length=128),
        ),
        migrations.AlterField(
            model_name="invoice",
            name="supplier_id_value",
            field=EncryptedCharField(blank=True, default="", max_length=256),
        ),
        migrations.AlterField(
            model_name="invoice",
            name="buyer_address",
            field=EncryptedTextField(blank=True, default=""),
        ),
        migrations.AlterField(
            model_name="invoice",
            name="buyer_phone",
            field=EncryptedCharField(blank=True, default="", max_length=128),
        ),
        migrations.AlterField(
            model_name="invoice",
            name="buyer_sst_number",
            field=EncryptedCharField(blank=True, default="", max_length=128),
        ),
        migrations.AlterField(
            model_name="invoice",
            name="buyer_id_value",
            field=EncryptedCharField(blank=True, default="", max_length=256),
        ),
        migrations.RunPython(_encrypt_existing_rows, migrations.RunPython.noop),
    ]
