"""At-rest encryption for webhook signing secrets.

The customer's webhook signing secret is shown ONCE at create time
(write-only contract — same as APIKey). To outbound-sign deliveries
the worker must reload that plaintext later, so we keep an encrypted
copy alongside the existing SHA-256 verification hash.

Today the encryption key is derived from ``settings.SECRET_KEY`` via
SHA-256. That ties secret confidentiality to the same secret Django
already protects (sessions, signed cookies, password reset tokens).
A future slice swaps this for an explicit ``WEBHOOK_SECRET_FERNET_KEY``
env var with a rotation procedure; the call sites here are stable
across that swap.

Why Fernet rather than raw cryptography primitives:

  - It's a one-shot AEAD (HMAC-SHA256 + AES-128-CBC) bundled with
    timestamp metadata. Tamper detection is automatic.
  - It's already a transitive dep (the ``cryptography`` library
    ships with the anthropic SDK), so no new dependency.
  - Versioned: ciphertexts are self-describing, so future key
    rotations don't need a migration.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet() -> Fernet:
    """Build the Fernet cipher from Django's SECRET_KEY.

    Same key for the lifetime of the process — Fernet itself doesn't
    cache so we keep this tiny + recompute per call. The cost is a
    SHA-256 hash, which is sub-microsecond.
    """
    raw = settings.SECRET_KEY.encode("utf-8")
    digest = hashlib.sha256(raw).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a plaintext webhook secret for at-rest storage."""
    if not plaintext:
        return ""
    token = _fernet().encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def decrypt_secret(ciphertext: str) -> str | None:
    """Decrypt a stored ciphertext. Returns ``None`` if missing/tampered.

    Returning ``None`` rather than raising is deliberate: the caller
    is the delivery worker, and a corrupt secret should mark the
    delivery unsigned + flag the endpoint for the operator —
    not crash the worker. The endpoint UI separately surfaces the
    "secret missing — please regenerate" state.
    """
    if not ciphertext:
        return None
    try:
        plain = _fernet().decrypt(ciphertext.encode("ascii"))
    except (InvalidToken, ValueError):
        return None
    return plain.decode("utf-8")
