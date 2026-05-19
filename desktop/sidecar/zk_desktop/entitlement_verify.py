"""Verify-only counterpart to apps.licensing.entitlements.

The cloud's licensing module owns both signing and verification — it
needs the private key to mint entitlements. The desktop only ever
verifies; the private key stays in the cloud KMS. So we ship a
trimmed module here that:

  - Loads the Ed25519 PUBLIC key from settings.
  - Parses the wire format (``<b64url(payload)>.<b64url(signature)>``).
  - Verifies the signature and returns the payload dict.

Wire format MUST match apps/licensing/entitlements.py — same b64url
encoding, same canonical JSON of the payload. If that contract drifts
the desktop will reject all entitlements.

Phase 5 will embed the public key at PyInstaller build time so a
tampered desktop binary can't trust a forged entitlement signed by a
different key. For Phase 3c we load from the env var
``ZK_DESKTOP_LICENSING_PUBLIC_KEY_PEM`` (the dev workflow fetches it
once from /api/v1/licenses/public-key/ and caches it locally).
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from django.conf import settings

LOG = logging.getLogger("zerokey.sidecar.entitlement")


class EntitlementVerifyError(Exception):
    """Raised when an entitlement can't be verified or parsed."""


@dataclass(frozen=True)
class VerifiedEntitlement:
    """The trusted payload after Ed25519 verification."""

    license_id: str
    organization_tin: str
    organization_legal_name: str
    plan: str
    status: str
    features: tuple[str, ...]
    signing_modes_allowed: tuple[str, ...]
    issued_at: datetime
    expires_at: datetime
    machine_fingerprint_hash: str
    raw: dict[str, Any]


_cached_pub: Ed25519PublicKey | None = None


def _load_pub() -> Ed25519PublicKey:
    """Cache the cloud's Ed25519 public key for the process lifetime."""
    global _cached_pub
    if _cached_pub is not None:
        return _cached_pub
    pem = getattr(settings, "ZK_DESKTOP_LICENSING_PUBLIC_KEY_PEM", "") or ""
    if not pem:
        raise EntitlementVerifyError(
            "ZK_DESKTOP_LICENSING_PUBLIC_KEY_PEM is not set. The desktop "
            "needs the cloud's Ed25519 public key to verify entitlements. "
            "Fetch from /api/v1/licenses/public-key/ once and pin it."
        )
    pub = serialization.load_pem_public_key(pem.encode("utf-8"))
    if not isinstance(pub, Ed25519PublicKey):
        raise EntitlementVerifyError(
            "ZK_DESKTOP_LICENSING_PUBLIC_KEY_PEM must be an Ed25519 public key"
        )
    _cached_pub = pub
    return pub


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + pad).encode("ascii"))


def verify(wire: str) -> VerifiedEntitlement:
    """Verify ``wire`` and return its trusted payload.

    Does NOT check ``expires_at`` — callers decide whether to enforce
    expiry strictly (mutating endpoints) or leniently (read-only mode
    after expiry). Phase 4 wires both policies in.
    """
    pub = _load_pub()
    if not wire or "." not in wire:
        raise EntitlementVerifyError("Malformed entitlement (missing '.')")
    try:
        b64_payload, b64_sig = wire.split(".", 1)
        payload_bytes = _b64url_decode(b64_payload)
        sig = _b64url_decode(b64_sig)
    except (ValueError, base64.binascii.Error) as exc:
        raise EntitlementVerifyError(f"Malformed entitlement: {exc}") from exc

    try:
        pub.verify(sig, payload_bytes)
    except InvalidSignature as exc:
        raise EntitlementVerifyError("Entitlement signature invalid") from exc

    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
        return VerifiedEntitlement(
            license_id=str(payload["license_id"]),
            organization_tin=str(payload["organization_tin"]),
            organization_legal_name=str(payload["organization_legal_name"]),
            plan=str(payload["plan"]),
            status=str(payload["status"]),
            features=tuple(payload.get("features") or []),
            signing_modes_allowed=tuple(payload.get("signing_modes_allowed") or []),
            issued_at=_parse_iso(payload["issued_at"]),
            expires_at=_parse_iso(payload["expires_at"]),
            machine_fingerprint_hash=str(payload.get("machine_fingerprint_hash") or ""),
            raw=payload,
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise EntitlementVerifyError(f"Entitlement payload missing/invalid: {exc}") from exc


def _parse_iso(s: str) -> datetime:
    # Python 3.10's fromisoformat accepts the format apps.licensing
    # emits (we control both sides; ISO-8601 with timezone offset).
    return datetime.fromisoformat(s)
