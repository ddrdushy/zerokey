"""Hash-chain construction and verification for the audit log.

Per AUDIT_LOG_SPEC.md:

    content_hash = SHA256( canonical( event minus {content_hash, chain_hash, signature} ) )
    chain_hash   = SHA256( previous_chain_hash_bytes || content_hash_bytes )

The genesis event (sequence == 1) uses 32 zero bytes as the previous-chain hash
input. We chose this convention explicitly because the spec leaves the genesis
representation open; the value is documented here and in the migration so a
verifier knows how to bootstrap.

Signatures (Ed25519 over chain_hash, key in KMS) are part of the spec but not
this Phase 1 slice — they are a layer of trust on top of an already-tamper-
evident chain. ``signature`` is left empty for now; the column exists so the
later wire-up does not require a schema change.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .canonical import canonical_bytes

# 32-byte zero seed for the genesis chain link. Documented choice (see module docstring).
GENESIS_PREV_HASH: bytes = bytes(32)


@dataclass(frozen=True)
class ChainHashes:
    content_hash: bytes
    chain_hash: bytes


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def compute_content_hash(event_body: dict[str, Any]) -> bytes:
    """Hash the event body. The body must NOT contain ``content_hash``,
    ``chain_hash`` or ``signature`` — those are derived from the body, not part
    of it."""
    forbidden = {"content_hash", "chain_hash", "signature"}
    leaked = forbidden & event_body.keys()
    if leaked:
        raise ValueError(f"event body must not contain derived fields: {sorted(leaked)}")
    return _sha256(canonical_bytes(event_body))


def compute_chain_hash(previous_chain_hash: bytes, content_hash: bytes) -> bytes:
    """Link this event into the chain.

    For the genesis event, ``previous_chain_hash`` is ``GENESIS_PREV_HASH``.
    """
    if len(previous_chain_hash) != 32:
        raise ValueError("previous_chain_hash must be 32 bytes")
    if len(content_hash) != 32:
        raise ValueError("content_hash must be 32 bytes")
    return _sha256(previous_chain_hash + content_hash)


def compute_hashes(event_body: dict[str, Any], previous_chain_hash: bytes) -> ChainHashes:
    """Convenience: compute both hashes for the event being inserted."""
    content_hash = compute_content_hash(event_body)
    chain_hash = compute_chain_hash(previous_chain_hash, content_hash)
    return ChainHashes(content_hash=content_hash, chain_hash=chain_hash)


def verify_link(
    *,
    event_body: dict[str, Any],
    expected_content_hash: bytes,
    previous_chain_hash: bytes,
    expected_chain_hash: bytes,
) -> None:
    """Raise ``ChainIntegrityError`` if the event does not match its stored hashes."""
    actual_content_hash = compute_content_hash(event_body)
    if actual_content_hash != expected_content_hash:
        raise ChainIntegrityError(
            "content_hash mismatch — payload was modified after the event was sealed"
        )
    actual_chain_hash = compute_chain_hash(previous_chain_hash, expected_content_hash)
    if actual_chain_hash != expected_chain_hash:
        raise ChainIntegrityError("chain_hash mismatch — sequence reordering or upstream tamper")


class ChainIntegrityError(Exception):
    """Raised when stored chain hashes do not match recomputed values."""
