"""Deferred submission (Slice 96)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("submission", "0012_encrypt_invoice_pii"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoice",
            name="scheduled_submit_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
