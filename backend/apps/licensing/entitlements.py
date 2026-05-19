"""Signed entitlement issuance + verification.

An entitlement is a tiny blob the desktop caches and uses to gate every
licensed operation while offline. It's signed with an Ed25519 keypair
held by this service; the desktop ships the public key embedded in its
binary and verifies every entitlement before trusting it.

Wire format — deliberately not full JWS, just enough to be cheap to
sign/verify and trivially diff'able when debugging:

    <b64url(payload_json)>.<b64url(signature)>

``payload_json`` is canonical JSON (sorted keys, no whitespace). The
signature is Ed25519 over the raw payload bytes (not the b64url
encoding — keeps the verifier simple).

The keypair is loaded from settings (``LICENSING_ED25519_PRIVATE_KEY_PEM``
and ``LICENSING_ED25519_PUBLIC_KEY_PEM``). In dev, if neither is set, we
generate an ephemeral keypair on first use and cache it — the desktop
build picks the matching public key out of the dev env. In prod, both
must be set or issuance fails closed.
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.exceptions import InvalidSignature
from django.conf import settings

logger = logging.getLogger(__name__)


# How long a freshly-issued entitlement is valid before the desktop must
# refresh via heartbeat. 30 days matches the offline-grace promise in
# DESKTOP_PIVOT_PLAN.md §"Locked architectural decisions" #4.
ENTITLEMENT_TTL_DAYS = 30


class EntitlementError(Exception):
    """Raised when an entitlement can't be issued or verified."""


@dataclass(frozen=True)
class Entitlement:
    """The structured payload we sign and the desktop trusts."""

    entitlement_id: uuid.UUID
    license_id: uuid.UUID
    organization_tin: str
    organization_legal_name: str
    plan: str
    status: str
    features: list[str]
    signing_modes_allowed: list[str]
    issued_at: datetime
    expires_at: datetime
    # The fingerprint we bound on first activation. The desktop checks
    # this against its current fingerprint and refuses to load if they
    # diverge — defence in depth against the cloud being compromised
    # and issuing entitlements for keys it shouldn't.
    machine_fingerprint_hash: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "entitlement_id": str(self.entitlement_id),
            "license_id": str(self.license_id),
            "organization_tin": self.organization_tin,
            "organization_legal_name": self.organization_legal_name,
            "plan": self.plan,
            "status": self.status,
            "features": list(self.features),
            "signing_modes_allowed": list(self.signing_modes_allowed),
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "machine_fingerprint_hash": self.machine_fingerprint_hash,
        }


_cached_private_key: Ed25519PrivateKey | None = None
_cached_public_key: Ed25519PublicKey | None = None


def _load_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    """Resolve the signing keypair from settings.

    Order:
      1. Both env-injected PEMs present → use them.
      2. DEBUG and neither set → generate ephemeral, cache for the
         process lifetime. Log loudly so nobody ships this.
      3. Otherwise → raise. We do not silently downgrade in prod.
    """
    global _cached_private_key, _cached_public_key
    if _cached_private_key is not None and _cached_public_key is not None:
        return _cached_private_key, _cached_public_key

    priv_pem = getattr(settings, "LICENSING_ED25519_PRIVATE_KEY_PEM", "") or ""
    pub_pem = getattr(settings, "LICENSING_ED25519_PUBLIC_KEY_PEM", "") or ""

    if priv_pem and pub_pem:
        priv = serialization.load_pem_private_key(priv_pem.encode("utf-8"), password=None)
        pub = serialization.load_pem_public_key(pub_pem.encode("utf-8"))
        if not isinstance(priv, Ed25519PrivateKey) or not isinstance(pub, Ed25519PublicKey):
            raise EntitlementError(
                "LICENSING_ED25519_*_KEY_PEM must be an Ed25519 keypair"
            )
        _cached_private_key, _cached_public_key = priv, pub
        return priv, pub

    if getattr(settings, "DEBUG", False):
        logger.warning(
            "licensing.entitlements.using_ephemeral_keypair "
            "set LICENSING_ED25519_PRIVATE_KEY_PEM + LICENSING_ED25519_PUBLIC_KEY_PEM "
            "in prod — entitlements signed this process will not verify after restart."
        )
        priv = Ed25519PrivateKey.generate()
        pub = priv.public_key()
        _cached_private_key, _cached_public_key = priv, pub
        return priv, pub

    raise EntitlementError(
        "Licensing keypair not configured. Set LICENSING_ED25519_PRIVATE_KEY_PEM "
        "and LICENSING_ED25519_PUBLIC_KEY_PEM in the environment."
    )


def _canonical_json(payload: dict[str, Any]) -> bytes:
    """Sorted-keys, no-whitespace JSON. The bytes we actually sign."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + pad).encode("ascii"))


def issue_entitlement(
    *,
    license_id: uuid.UUID,
    organization_tin: str,
    organization_legal_name: str,
    plan: str,
    status: str,
    features: list[str],
    signing_modes_allowed: list[str],
    machine_fingerprint_hash: str,
    ttl_days: int = ENTITLEMENT_TTL_DAYS,
) -> tuple[Entitlement, str]:
    """Mint a fresh signed entitlement.

    Returns ``(entitlement_struct, wire_format_string)``. The wire
    format string is what the API hands back to the desktop.
    """
    priv, _ = _load_keypair()
    now = datetime.now(tz=timezone.utc)
    ent = Entitlement(
        entitlement_id=uuid.uuid4(),
        license_id=license_id,
        organization_tin=organization_tin,
        organization_legal_name=organization_legal_name,
        plan=plan,
        status=status,
        features=features,
        signing_modes_allowed=signing_modes_allowed,
        issued_at=now,
        expires_at=now + timedelta(days=ttl_days),
        machine_fingerprint_hash=machine_fingerprint_hash,
    )
    payload_bytes = _canonical_json(ent.to_payload())
    sig = priv.sign(payload_bytes)
    wire = f"{_b64url(payload_bytes)}.{_b64url(sig)}"
    return ent, wire


def verify_entitlement(wire: str) -> dict[str, Any]:
    """Verify a wire-format entitlement and return its payload dict.

    Used by the cloud signing endpoint (in Phase 3) and by tests.
    The desktop runs the equivalent verification locally against its
    embedded public key.
    """
    _, pub = _load_keypair()
    try:
        b64_payload, b64_sig = wire.split(".")
    except ValueError as exc:
        raise EntitlementError("Malformed entitlement (missing '.')") from exc
    payload_bytes = _b64url_decode(b64_payload)
    sig = _b64url_decode(b64_sig)
    try:
        pub.verify(sig, payload_bytes)
    except InvalidSignature as exc:
        raise EntitlementError("Entitlement signature invalid") from exc
    return json.loads(payload_bytes.decode("utf-8"))


def public_key_pem() -> str:
    """The PEM-encoded public key. Exposed at /licensing/public-key/
    for transparency + so dev installs can pin the dev key."""
    _, pub = _load_keypair()
    return pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
