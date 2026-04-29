# Generated for Slice 82 — WhatsApp ingestion routing key.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0014_inbox_token"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="whatsapp_phone_number_id",
            field=models.CharField(blank=True, db_index=True, default="", max_length=64),
        ),
    ]
