"""Remote signer proxy — quacks like cryptography's RSAPrivateKey.

When an Organization on the desktop is in ``signing_mode='intermediary'``,
we don't have the private key — it stays in the cloud KMS. But the
cloud's submission/XAdES code calls
``loaded_cert.private_key.sign(data, padding, algorithm)`` directly.

This proxy implements the same ``.sign()`` signature and routes the
call through ``zk_desktop.cloud_signing.sign_document``. The contract
to the caller is identical to RSAPrivateKey.sign() — the desktop
swaps the implementation underneath.

Constraints:
  - Only SHA-256 is supported (digest size matches cloud).
  - Padding must be PKCS#1 v1.5 (what LHDN's XAdES uses).
  - The cloud call requires an entitlement; the proxy reads it from
    a contextvar set by EntitlementAuthentication on the current
    request. If no entitlement is in scope (e.g. a Celery-equivalent
    background job), signing fails loudly — we never silently use a
    stale entitlement.
"""

from __future__ import annotations

import contextvars
import hashlib
import logging

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed

from zk_desktop import cloud_signing

LOG = logging.getLogger("zerokey.sidecar.remote_signer")


_active_entitlement: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "zk_active_entitlement", default=None
)


def set_active_entitlement(wire: str | None) -> None:
    """Pin the entitlement bearer for the current task/request."""
    _active_entitlement.set(wire)


class RemoteSignerError(Exception):
    """Raised when the remote signer can't fulfil a sign() call."""


class RemoteRsaSigner:
    """Duck-typed stand-in for cryptography.hazmat...RSAPrivateKey.

    Only ``.sign()`` is implemented. Anything else (key_size,
    public_key(), private_numbers(), etc.) raises — the cloud's
    intermediary key never leaves the cloud, so by definition any
    code path that needs more than .sign() is broken on the desktop.
    """

    def __init__(self, cert_serial_hex: str = "") -> None:
        self.cert_serial_hex = cert_serial_hex

    def sign(self, data: bytes, padding_, algorithm) -> bytes:
        # We only support what LHDN's XAdES actually uses today.
        if not isinstance(padding_, padding.PKCS1v15):
            raise RemoteSignerError(
                f"Remote signer only supports PKCS#1 v1.5 padding (got {type(padding_).__name__})"
            )

        if isinstance(algorithm, Prehashed):
            # Caller has already hashed; data IS the digest.
            digest = data
            if len(digest) != 32:
                raise RemoteSignerError(
                    f"Prehashed digest must be 32 bytes for SHA-256 (got {len(digest)})"
                )
        elif isinstance(algorithm, hashes.SHA256):
            # Caller passed raw bytes + asked us to SHA-256. Do it here
            # so the cloud call always carries a 32-byte digest.
            digest = hashlib.sha256(data).digest()
        else:
            raise RemoteSignerError(
                f"Remote signer only supports SHA-256 (got {type(algorithm).__name__})"
            )

        wire = _active_entitlement.get()
        if not wire:
            raise RemoteSignerError(
                "No active entitlement in scope. Cloud signing needs the "
                "request's entitlement; set it via set_active_entitlement() "
                "before invoking the submission pipeline."
            )

        bundle = cloud_signing.sign_document(digest=digest, entitlement=wire)
        LOG.info(
            "zerokey.sidecar.remote_signer.signed audit_event=%s serial=%s",
            bundle.audit_event_id,
            bundle.serial_hex,
        )
        return bundle.signature

    # The rest of the RSAPrivateKey surface is intentionally absent.
    # If something tries to call .public_key() or .key_size on the
    # desktop, that code path needs to be reworked to fetch the cert
    # PEM separately (which we have — LoadedCertificate.cert_pem
    # ships back with the signature).

    def __repr__(self) -> str:
        return f"<RemoteRsaSigner serial={self.cert_serial_hex!r}>"
