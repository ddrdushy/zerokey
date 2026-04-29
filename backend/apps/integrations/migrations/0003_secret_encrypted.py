"""Add WebhookEndpoint.secret_encrypted (Fernet ciphertext of the signing
secret). Required so the outbound delivery worker (Slice 53) can sign
payloads with the literal secret the customer was shown at create time.
"""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0002_integrations_rls"),
    ]

    operations = [
        migrations.AddField(
            model_name="webhookendpoint",
            name="secret_encrypted",
            field=models.TextField(blank=True, default=""),
        ),
    ]
