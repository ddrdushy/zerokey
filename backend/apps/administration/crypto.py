"""At-rest encryption for platform secrets (Slice 55).

The platform stores two classes of high-value secret in the database:

  - **SystemSetting.values**: super-admin-managed credentials for
    platform integrations (LHDN client_id/secret, Stripe API key,
    SMTP password). Visible to anyone with database access if
    plaintext.
  - **Engine.credentials**: per-engine vendor keys (Anthropic API
    key, Azure subscription key, Ollama Cloud token). Same exposure.

This module owns the at-rest envelope. Both surfaces transparently
encrypt-on-write + decrypt-on-read by routing through the helpers
here. Plaintext written before this slice landed remains readable
(the marker prefix ``enc1:`` distinguishes ciphertext from legacy
plaintext) and the migration that ships with this slice walks the
existing rows and rewrites them.

Why Fernet (AES-128-CBC + HMAC-SHA256, all-in-one AEAD):

  - It's already a transitive dependency (the ``cryptography``
    library ships with the anthropic SDK).
  - Versioned ciphertexts mean we can rotate the key without a
    schema migration — the next encrypt produces v2-tagged output;
    decrypt walks the version list.
  - All-in-one tamper detection. A flipped byte fails decryption,
    not silently produces garbage.

Why a key derived from ``SECRET_KEY`` rather than a separate
``FIELD_ENCRYPTION_KEY`` env var TODAY:

  - One less moving piece for the dev environment.
  - SECRET_KEY is already the highest-criticality string Django
    has; tying field-level confidentiality to it is correct
    threat-modelling — an attacker with SECRET_KEY can already
    forge sessions, signed cookies, and password reset tokens.

Why we'll swap to a dedicated key + KMS in production:

  - Rotation cadence differs. SECRET_KEY rotates rarely (Django
    sessions invalidate); field encryption may want monthly
    rotation independent of session state.
  - KMS-backed envelope encryption (decrypt-the-DEK-on-startup,
    keep DEK in memory) is the AWS-native pattern for at-rest
    confidentiality + auditable access.

The swap point is exactly the function ``_dek()`` below — replace
its body with a KMS Decrypt call against an envelope-encrypted
DEK loaded from S3 / Secrets Manager. The call sites here don't
change.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

logger = logging.getLogger(__name__)


# Ciphertext marker prefix. Values that start with this are encrypted;
# everything else is treated as legacy plaintext (read-through, with
# the migration rewriting on first opportunity).
_CIPHERTEXT_PREFIX = "enc1:"


def _dek() -> bytes:
    """Resolve the data-encryption key (DEK).

    Production swap point. Today: SHA-256 of SECRET_KEY ⇒ Fernet key.
    Tomorrow: KMS Decrypt on a DEK ciphertext loaded from Secrets
    Manager at process startup, cached in memory.
    """
    raw = settings.SECRET_KEY.encode("utf-8")
    return base64.urlsafe_b64encode(hashlib.sha256(raw).digest())


def _fernet() -> Fernet:
    return Fernet(_dek())


def encrypt_value(plain: str) -> str:
    """Encrypt a single string for at-rest storage.

    Idempotent on already-encrypted strings — re-encrypting an
    already-encrypted value would cost a layer of indirection on
    every read, so we no-op when the input already carries the
    ciphertext marker. The migration relies on this to be safe
    against partial replays.

    Empty / None input returns empty string unchanged. The
    semantic "no value" stays distinguishable from "encrypted
    empty value" — callers that need to distinguish those should
    use a different sentinel.
    """
    if not plain:
        return ""
    if isinstance(plain, str) and plain.startswith(_CIPHERTEXT_PREFIX):
        return plain
    token = _fernet().encrypt(plain.encode("utf-8"))
    return _CIPHERTEXT_PREFIX + token.decode("ascii")


def decrypt_value(stored: str) -> str:
    """Decrypt a stored value. Pass-through for legacy plaintext.

    Returns the empty string for None / empty / corrupted ciphertext.
    A logging warning fires on InvalidToken so an operator notices
    a schema migration that left a row half-encrypted, but the
    application doesn't crash — degrades to "no value" so callers
    that have an env-fallback path still work.
    """
    if not stored:
        return ""
    if not isinstance(stored, str):
        return str(stored)
    if not stored.startswith(_CIPHERTEXT_PREFIX):
        # Legacy plaintext from before this slice landed. The migration
        # rewrites it on first opportunity; readers see it as-is.
        return stored
    token = stored[len(_CIPHERTEXT_PREFIX):].encode("ascii")
    try:
        plain = _fernet().decrypt(token)
    except (InvalidToken, ValueError):
        logger.warning(
            "secrets_at_rest.decrypt_failed",
            extra={"prefix": stored[: len(_CIPHERTEXT_PREFIX) + 4]},
        )
        return ""
    return plain.decode("utf-8")


def encrypt_dict_values(values: dict[str, Any]) -> dict[str, Any]:
    """Encrypt every string value in a dict; leave non-strings alone.

    SystemSetting.values + Engine.credentials are JSON dicts of
    string credentials. Non-string values (booleans, ints — rare
    in credential dicts but possible for things like timeout
    seconds) are left as-is; encrypting non-secrets buys nothing.

    Keys are NOT encrypted — the audit log records WHICH keys
    changed when an admin edits a SystemSetting (by name only),
    and that operator-visibility is a feature.
    """
    if not isinstance(values, dict):
        return values
    out: dict[str, Any] = {}
    for k, v in values.items():
        if isinstance(v, str):
            out[k] = encrypt_value(v)
        else:
            out[k] = v
    return out


def decrypt_dict_values(values: dict[str, Any]) -> dict[str, Any]:
    """Decrypt every string value in a dict; leave non-strings alone."""
    if not isinstance(values, dict):
        return values
    out: dict[str, Any] = {}
    for k, v in values.items():
        if isinstance(v, str):
            out[k] = decrypt_value(v)
        else:
            out[k] = v
    return out
