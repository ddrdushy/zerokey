"""Pure-unit tests for the hash chain primitives (no DB)."""

from __future__ import annotations

import hashlib

import pytest

from apps.audit.canonical import canonical_bytes
from apps.audit.chain import (
    GENESIS_PREV_HASH,
    ChainIntegrityError,
    compute_chain_hash,
    compute_content_hash,
    compute_hashes,
    verify_link,
)


class TestChainPrimitives:
    def test_genesis_prev_hash_is_32_zero_bytes(self) -> None:
        assert GENESIS_PREV_HASH == bytes(32)
        assert len(GENESIS_PREV_HASH) == 32

    def test_content_hash_matches_canonical_sha256(self) -> None:
        body = {"action_type": "x", "payload": {"a": 1}}
        expected = hashlib.sha256(canonical_bytes(body)).digest()
        assert compute_content_hash(body) == expected

    def test_content_hash_rejects_derived_fields(self) -> None:
        with pytest.raises(ValueError, match="content_hash"):
            compute_content_hash({"content_hash": b"x"})
        with pytest.raises(ValueError, match="chain_hash"):
            compute_content_hash({"chain_hash": b"x"})
        with pytest.raises(ValueError, match="signature"):
            compute_content_hash({"signature": b"x"})

    def test_chain_hash_links_previous_and_content(self) -> None:
        prev = bytes(32)
        content = bytes.fromhex("a" * 64)
        expected = hashlib.sha256(prev + content).digest()
        assert compute_chain_hash(prev, content) == expected

    def test_chain_hash_validates_input_lengths(self) -> None:
        with pytest.raises(ValueError):
            compute_chain_hash(b"short", bytes(32))
        with pytest.raises(ValueError):
            compute_chain_hash(bytes(32), b"short")

    def test_compute_hashes_returns_both(self) -> None:
        body = {"action_type": "auth.login_success", "sequence": 1}
        result = compute_hashes(body, GENESIS_PREV_HASH)
        assert len(result.content_hash) == 32
        assert len(result.chain_hash) == 32
        assert result.content_hash != result.chain_hash

    def test_chain_is_deterministic(self) -> None:
        body = {"action_type": "x", "sequence": 1}
        a = compute_hashes(body, GENESIS_PREV_HASH)
        b = compute_hashes(body, GENESIS_PREV_HASH)
        assert a.content_hash == b.content_hash
        assert a.chain_hash == b.chain_hash

    def test_payload_tamper_changes_content_hash(self) -> None:
        original = compute_hashes({"sequence": 1, "payload": {"x": 1}}, GENESIS_PREV_HASH)
        tampered = compute_hashes({"sequence": 1, "payload": {"x": 2}}, GENESIS_PREV_HASH)
        assert original.content_hash != tampered.content_hash
        assert original.chain_hash != tampered.chain_hash

    def test_verify_link_passes_for_correct_hashes(self) -> None:
        body = {"sequence": 1, "action_type": "x"}
        h = compute_hashes(body, GENESIS_PREV_HASH)
        verify_link(
            event_body=body,
            expected_content_hash=h.content_hash,
            previous_chain_hash=GENESIS_PREV_HASH,
            expected_chain_hash=h.chain_hash,
        )

    def test_verify_link_detects_payload_tampering(self) -> None:
        body = {"sequence": 1, "action_type": "x"}
        h = compute_hashes(body, GENESIS_PREV_HASH)
        with pytest.raises(ChainIntegrityError, match="content_hash"):
            verify_link(
                event_body={"sequence": 1, "action_type": "tampered"},
                expected_content_hash=h.content_hash,
                previous_chain_hash=GENESIS_PREV_HASH,
                expected_chain_hash=h.chain_hash,
            )

    def test_verify_link_detects_chain_reordering(self) -> None:
        body = {"sequence": 1, "action_type": "x"}
        h = compute_hashes(body, GENESIS_PREV_HASH)
        wrong_prev = hashlib.sha256(b"other").digest()
        with pytest.raises(ChainIntegrityError, match="chain_hash"):
            verify_link(
                event_body=body,
                expected_content_hash=h.content_hash,
                previous_chain_hash=wrong_prev,
                expected_chain_hash=h.chain_hash,
            )
