"""Tests for at-rest encryption of platform secrets (Slice 55)."""

from __future__ import annotations

import pytest

from apps.administration.crypto import (
    decrypt_dict_values,
    decrypt_value,
    encrypt_dict_values,
    encrypt_value,
)


class TestSingleValue:
    def test_roundtrip(self) -> None:
        plain = "sk-anthropic-12345"
        cipher = encrypt_value(plain)
        assert cipher != plain
        assert cipher.startswith("enc1:")
        assert decrypt_value(cipher) == plain

    def test_empty_passthrough(self) -> None:
        assert encrypt_value("") == ""
        assert decrypt_value("") == ""

    def test_legacy_plaintext_passthrough(self) -> None:
        """A row written before encryption rolled out reads back as-is."""
        legacy = "AKIA-some-aws-key-12345"
        # Decrypt should pass legacy plaintext through (no prefix).
        assert decrypt_value(legacy) == legacy

    def test_idempotent_encrypt(self) -> None:
        """Re-encrypting an already-encrypted value is a no-op."""
        cipher = encrypt_value("hello")
        cipher2 = encrypt_value(cipher)
        assert cipher == cipher2

    def test_corrupt_ciphertext_returns_empty(self) -> None:
        """A flipped byte must not crash the decrypt path."""
        cipher = encrypt_value("secret")
        tampered = cipher[:-3] + "AAA"
        assert decrypt_value(tampered) == ""

    def test_ciphertext_never_contains_plaintext(self) -> None:
        plain = "very-distinctive-substring-xyz123"
        cipher = encrypt_value(plain)
        assert plain not in cipher


class TestDictValues:
    def test_encrypts_strings_only(self) -> None:
        encrypted = encrypt_dict_values(
            {"api_key": "sk-real", "timeout_seconds": 30, "use_tls": True}
        )
        assert encrypted["api_key"].startswith("enc1:")
        # Non-strings pass through unchanged.
        assert encrypted["timeout_seconds"] == 30
        assert encrypted["use_tls"] is True

    def test_keys_not_encrypted(self) -> None:
        """Keys stay plaintext — the audit log records WHICH keys
        changed (by name), and that's load-bearing for compliance.
        """
        encrypted = encrypt_dict_values({"client_id": "abc", "client_secret": "xyz"})
        assert "client_id" in encrypted
        assert "client_secret" in encrypted

    def test_roundtrip_dict(self) -> None:
        original = {"host": "smtp.example.com", "password": "p4ss"}
        roundtripped = decrypt_dict_values(encrypt_dict_values(original))
        assert roundtripped == original

    def test_mixed_legacy_and_encrypted(self) -> None:
        """A dict with both legacy plaintext and freshly-encrypted
        values reads correctly. This is the migration-in-progress
        state.
        """
        # Simulate: one value written before Slice 55 (legacy),
        # one written after (encrypted).
        cipher = encrypt_value("new-secret")
        mixed = {"legacy_key": "old-plaintext", "fresh_key": cipher}
        decrypted = decrypt_dict_values(mixed)
        assert decrypted["legacy_key"] == "old-plaintext"
        assert decrypted["fresh_key"] == "new-secret"

    def test_non_dict_passes_through(self) -> None:
        """Defensive: a malformed values column shouldn't crash."""
        assert encrypt_dict_values(None) is None
        assert decrypt_dict_values(None) is None


@pytest.mark.django_db
class TestSystemSettingsResolver:
    def test_upsert_stores_ciphertext_at_rest(self) -> None:
        from apps.administration.models import SystemSetting
        from apps.administration.services import upsert_system_setting, system_setting

        upsert_system_setting(
            namespace="testns",
            values={"api_key": "secret-value-12345"},
        )
        # Raw DB read: column should hold ciphertext, not plaintext.
        row = SystemSetting.objects.get(namespace="testns")
        stored = row.values["api_key"]
        assert stored.startswith("enc1:")
        assert "secret-value-12345" not in stored
        # Resolver returns plaintext.
        assert system_setting(namespace="testns", key="api_key") == "secret-value-12345"

    def test_resolver_handles_legacy_plaintext(self) -> None:
        """Rows written before Slice 55 still resolve correctly."""
        from apps.administration.models import SystemSetting
        from apps.administration.services import system_setting

        SystemSetting.objects.create(
            namespace="legacyns",
            values={"api_key": "old-plaintext-key"},
        )
        assert system_setting(namespace="legacyns", key="api_key") == "old-plaintext-key"


@pytest.mark.django_db
class TestEngineCredentialResolver:
    def test_decrypts_engine_credential(self) -> None:
        from apps.administration.crypto import encrypt_value
        from apps.extraction.credentials import engine_credential
        from apps.extraction.models import Engine

        engine = Engine.objects.create(
            name="test-engine-x",
            vendor="acme",
            capability=Engine.Capability.TEXT_EXTRACT,
            status=Engine.Status.ACTIVE,
            credentials={"api_key": encrypt_value("real-engine-key")},
        )
        try:
            assert engine_credential(engine_name="test-engine-x", key="api_key") == "real-engine-key"
        finally:
            engine.delete()

    def test_handles_legacy_plaintext_credential(self) -> None:
        from apps.extraction.credentials import engine_credential
        from apps.extraction.models import Engine

        engine = Engine.objects.create(
            name="test-engine-legacy",
            vendor="acme",
            capability=Engine.Capability.TEXT_EXTRACT,
            status=Engine.Status.ACTIVE,
            credentials={"api_key": "legacy-plaintext-key"},
        )
        try:
            assert (
                engine_credential(engine_name="test-engine-legacy", key="api_key")
                == "legacy-plaintext-key"
            )
        finally:
            engine.delete()
