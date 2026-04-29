"""Encrypt existing SystemSetting + Engine credential plaintext (Slice 55).

Walks every SystemSetting row and Engine row, looks at each string
value in the JSON dict, and rewrites it as ciphertext via
``apps.administration.crypto.encrypt_value``. Idempotent — values
that already carry the ``enc1:`` ciphertext prefix are left alone.

Backward swap: the decrypt path treats unprefixed values as legacy
plaintext, so even if this migration is rolled back we don't lose
data — the rows stay readable.
"""

from __future__ import annotations

from django.db import migrations


def _encrypt_dict(values, encrypt_fn):
    if not isinstance(values, dict):
        return values
    out = {}
    for k, v in values.items():
        out[k] = encrypt_fn(v) if isinstance(v, str) else v
    return out


def encrypt_forward(apps, schema_editor):  # noqa: ARG001
    """Rewrite plaintext credential values as ciphertext."""
    # Lazy import — module imports cryptography which we don't want
    # touched at app-config load time.
    from apps.administration.crypto import encrypt_value

    SystemSetting = apps.get_model("administration", "SystemSetting")
    for setting in SystemSetting.objects.all():
        encrypted = _encrypt_dict(setting.values or {}, encrypt_value)
        if encrypted != setting.values:
            setting.values = encrypted
            setting.save(update_fields=["values"])

    Engine = apps.get_model("extraction", "Engine")
    for engine in Engine.objects.all():
        encrypted = _encrypt_dict(engine.credentials or {}, encrypt_value)
        if encrypted != engine.credentials:
            engine.credentials = encrypted
            engine.save(update_fields=["credentials"])


def decrypt_reverse(apps, schema_editor):  # noqa: ARG001
    """Revert: decrypt ciphertext back to plaintext.

    Used only on a forward-then-rollback in dev. In production the
    reverse path should never run — rolling back the deployment that
    introduced encryption is fine because the read path tolerates
    ciphertext (the prefix is stable). But the option is here so
    test-suite migrations don't get stuck.
    """
    from apps.administration.crypto import decrypt_value

    SystemSetting = apps.get_model("administration", "SystemSetting")
    for setting in SystemSetting.objects.all():
        decrypted = _encrypt_dict(setting.values or {}, decrypt_value)
        if decrypted != setting.values:
            setting.values = decrypted
            setting.save(update_fields=["values"])

    Engine = apps.get_model("extraction", "Engine")
    for engine in Engine.objects.all():
        decrypted = _encrypt_dict(engine.credentials or {}, decrypt_value)
        if decrypted != engine.credentials:
            engine.credentials = decrypted
            engine.save(update_fields=["credentials"])


class Migration(migrations.Migration):
    dependencies = [
        ("administration", "0004_impersonationsession"),
        # Engine model lives in extraction; depend on its initial table
        # so the data migration can read its rows.
        ("extraction", "0005_seed_easyocr"),
    ]

    operations = [
        migrations.RunPython(encrypt_forward, decrypt_reverse),
    ]
