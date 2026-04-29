# Generated for Slice 89 — TOTP 2FA.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("identity", "0016_approval_policy"),
    ]

    operations = [
        # Encrypted at rest via apps.administration.crypto. Stored as
        # text (Fernet-token text wrapped with the "enc1:" marker).
        migrations.AddField(
            model_name="user",
            name="totp_secret_encrypted",
            field=models.TextField(blank=True, default=""),
        ),
        # JSON list of HMAC-SHA-256 hex digests of the eight recovery
        # codes. Plaintext codes are surfaced once at confirm time +
        # never persisted. A used code is removed from the list.
        migrations.AddField(
            model_name="user",
            name="totp_recovery_hashes",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
