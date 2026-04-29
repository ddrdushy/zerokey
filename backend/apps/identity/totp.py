"""TOTP (RFC 6238) two-factor authentication (Slice 89).

Implements just enough of RFC 6238 to serve the standard
authenticator-app flow (Google Authenticator, Authy, 1Password,
Microsoft Authenticator, Aegis, …):

  - 20-byte random secret, base32-encoded for transport.
  - SHA-1 HMAC, 30-second time step, 6-digit codes — the
    universally-supported defaults; deviating breaks Authenticator.
  - ±1 step tolerance on verification (90 seconds total window) so
    a slightly-skewed phone clock doesn't lock the user out.
  - 8 single-use recovery codes (16 hex chars each), HMAC-hashed
    at rest. Plaintext is surfaced exactly once, at confirm time.

Why we hand-roll instead of pulling pyotp/django-otp:

  - The implementation is ~30 lines. The rest of the cost
    (provisioning URI, recovery codes, login flow) lives in the
    auth flow regardless of library.
  - One fewer transitive dependency to vendor + audit. Both
    pyotp and django-otp are fine libraries; we don't *need* them.
  - Lets us tie at-rest encryption to ``apps.administration.crypto``
    explicitly, which is the project-wide envelope.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from urllib.parse import quote

from apps.administration.crypto import decrypt_value, encrypt_value

# RFC-6238 standard parameters. Don't change these without
# coordinating with the authenticator app vendors — virtually all
# of them assume the SHA-1 / 30s / 6-digit defaults.
DIGITS = 6
TIME_STEP_SECONDS = 30
ALGORITHM = hashlib.sha1
SECRET_BYTES = 20  # 160 bits, the RFC-6238 recommended minimum
DRIFT_TOLERANCE_STEPS = 1  # ±30s


def _generate_secret() -> str:
    """Produce a fresh base32-encoded shared secret."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode("ascii").rstrip("=")


def generate_secret_encrypted() -> tuple[str, str]:
    """Return ``(plain_b32_secret, encrypted_form)``.

    The plain form is shown to the user once during enrollment so
    they can scan the QR / type it in. The encrypted form goes on
    the User row.
    """
    plain = _generate_secret()
    return plain, encrypt_value(plain)


def decrypt_secret(stored: str) -> str:
    """Recover the base32 secret from its encrypted column."""
    return decrypt_value(stored or "")


def provisioning_uri(*, account_email: str, secret_b32: str, issuer: str = "ZeroKey") -> str:
    """Build the ``otpauth://`` URI for QR-scan or manual entry.

    Accepted by every mainstream authenticator app. Issuer is
    rendered in the app's account name; we hard-default to
    "ZeroKey" so the user can tell which login the code is for.
    """
    label = f"{issuer}:{account_email}"
    qs = (
        f"secret={secret_b32}"
        f"&issuer={quote(issuer)}"
        f"&algorithm=SHA1"
        f"&digits={DIGITS}"
        f"&period={TIME_STEP_SECONDS}"
    )
    return f"otpauth://totp/{quote(label)}?{qs}"


def _hotp(secret_b32: str, counter: int) -> str:
    """RFC-4226 HOTP value at the given counter.

    Re-pads the base32 secret because token_bytes-derived secrets
    are 32 chars (no '=' padding needed at length 32) but inputs
    that came from outside might be padded or trimmed.
    """
    pad = "=" * ((8 - len(secret_b32) % 8) % 8)
    key = base64.b32decode(secret_b32.upper() + pad)
    msg = counter.to_bytes(8, "big")
    digest = hmac.new(key, msg, ALGORITHM).digest()
    offset = digest[-1] & 0x0F
    code = (
        ((digest[offset] & 0x7F) << 24)
        | ((digest[offset + 1] & 0xFF) << 16)
        | ((digest[offset + 2] & 0xFF) << 8)
        | (digest[offset + 3] & 0xFF)
    )
    return str(code % (10**DIGITS)).zfill(DIGITS)


def verify_code(*, secret_b32: str, code: str, at: float | None = None) -> bool:
    """Constant-time TOTP verification with ±1 step tolerance.

    Strips spaces / dashes (some apps put a dash in the middle)
    and rejects anything that doesn't look like a 6-digit string.
    """
    if not secret_b32 or not code:
        return False
    cleaned = code.replace(" ", "").replace("-", "")
    if not cleaned.isdigit() or len(cleaned) != DIGITS:
        return False
    now = at if at is not None else time.time()
    counter = int(now // TIME_STEP_SECONDS)
    for offset in range(-DRIFT_TOLERANCE_STEPS, DRIFT_TOLERANCE_STEPS + 1):
        candidate = _hotp(secret_b32, counter + offset)
        if hmac.compare_digest(candidate, cleaned):
            return True
    return False


# --- Recovery codes ------------------------------------------------------


RECOVERY_CODE_COUNT = 8


def generate_recovery_codes() -> list[str]:
    """Mint a fresh batch of plaintext recovery codes.

    Codes are 16 lowercase hex characters in two groups of 8
    separated by a dash — visually distinct from a TOTP code so a
    user won't confuse them at login time.
    """
    out: list[str] = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = secrets.token_hex(8)
        out.append(f"{raw[:8]}-{raw[8:]}")
    return out


def hash_recovery_code(code: str) -> str:
    """Stable HMAC-SHA-256 hex digest of a recovery code.

    HMAC-keyed by the platform SECRET_KEY so a database leak alone
    doesn't permit brute-forcing the (16 hex chars, ~64 bits) code
    space. Same construction as Django's password-hashing pepper
    pattern.
    """
    from django.conf import settings

    normalised = code.strip().lower().replace(" ", "")
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        normalised.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_and_consume_recovery_code(*, user, code: str) -> bool:
    """Check + remove the matching code on success.

    Returns True iff the user had this code on file (single-use).
    The User row is mutated; callers must save it.
    """
    target = hash_recovery_code(code)
    hashes = list(user.totp_recovery_hashes or [])
    for stored in hashes:
        if hmac.compare_digest(stored, target):
            hashes.remove(stored)
            user.totp_recovery_hashes = hashes
            return True
    return False
