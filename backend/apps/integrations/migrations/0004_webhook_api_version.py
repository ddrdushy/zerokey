"""Per-endpoint webhook API version (Slice 96)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("integrations", "0003_secret_encrypted"),
    ]

    operations = [
        migrations.AddField(
            model_name="webhookendpoint",
            name="api_version",
            field=models.CharField(default="v1", max_length=8),
        ),
    ]
