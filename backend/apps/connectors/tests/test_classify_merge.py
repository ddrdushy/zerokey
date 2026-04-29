"""Named tests for every cell of the classify_merge matrix (Slice 74).

The classifier is a pure function — these tests don't need DB
access. They cover the full matrix from the module docstring,
named one test per row so a regression in any cell points
directly at which rule changed.
"""

from __future__ import annotations

from apps.connectors.merge_classifier import (
    ClassifyInputs,
    Verdict,
    classify_merge,
)


def _inputs(
    *,
    existing: str = "",
    existing_source: str | None = None,
    incoming: str = "",
    incoming_source: str = "synced_csv",
    is_locked: bool = False,
    is_authority_verified: bool = False,
) -> ClassifyInputs:
    """Test-helper builder — keeps each test focused on the one
    field it's exercising rather than restating every default."""
    return ClassifyInputs(
        existing_value=existing,
        existing_provenance=({"source": existing_source} if existing_source is not None else None),
        incoming_value=incoming,
        incoming_source=incoming_source,
        is_locked=is_locked,
        is_authority_verified=is_authority_verified,
    )


# =============================================================================
# Locked field — overrides everything below.
# =============================================================================


class TestLocked:
    def test_locked_with_changed_value_skipped(self) -> None:
        out = classify_merge(
            _inputs(
                existing="OLD",
                existing_source="synced_xero",
                incoming="NEW",
                incoming_source="synced_xero",
                is_locked=True,
            )
        )
        assert out is Verdict.SKIPPED_LOCKED

    def test_locked_beats_verified(self) -> None:
        out = classify_merge(
            _inputs(
                existing="C9999999999",
                existing_source="verified_lhdn",
                incoming="C8888888888",
                is_locked=True,
                is_authority_verified=True,
            )
        )
        assert out is Verdict.SKIPPED_LOCKED

    def test_locked_beats_auto_populate(self) -> None:
        # Even if the existing slot is empty, a lock means "don't
        # let any sync write here". The user explicitly pinned it.
        out = classify_merge(
            _inputs(
                existing="",
                incoming="NEW",
                is_locked=True,
            )
        )
        assert out is Verdict.SKIPPED_LOCKED


# =============================================================================
# Authority-verified — outranks any connector's claim.
# =============================================================================


class TestAuthorityVerified:
    def test_verified_blocks_overwrite(self) -> None:
        out = classify_merge(
            _inputs(
                existing="C9999999999",
                existing_source="verified_lhdn",
                incoming="C8888888888",
                is_authority_verified=True,
            )
        )
        assert out is Verdict.SKIPPED_VERIFIED

    def test_verified_blocks_even_same_source(self) -> None:
        # A verified TIN doesn't get overwritten even by the same
        # connector that originally populated it. LHDN is the
        # authority; the connector is not.
        out = classify_merge(
            _inputs(
                existing="C9999999999",
                existing_source="synced_autocount",
                incoming="C8888888888",
                incoming_source="synced_autocount",
                is_authority_verified=True,
            )
        )
        assert out is Verdict.SKIPPED_VERIFIED


# =============================================================================
# Empty existing — auto-populate happy path.
# =============================================================================


class TestEmptyExisting:
    def test_empty_existing_with_incoming_auto_populates(self) -> None:
        out = classify_merge(_inputs(existing="", incoming="ACME SDN BHD"))
        assert out is Verdict.AUTO_POPULATE

    def test_both_empty_is_noop(self) -> None:
        out = classify_merge(_inputs(existing="", incoming=""))
        assert out is Verdict.NOOP

    def test_whitespace_only_treated_as_empty(self) -> None:
        # Existing "   " should be treated as empty, not as a
        # different non-empty value. Otherwise a connector that
        # sends a real value would route to conflict instead of
        # auto-populate.
        out = classify_merge(_inputs(existing="   ", incoming="ACME"))
        assert out is Verdict.AUTO_POPULATE


# =============================================================================
# Identical values — noop regardless of source.
# =============================================================================


class TestIdentical:
    def test_identical_values_is_noop(self) -> None:
        out = classify_merge(
            _inputs(
                existing="ACME",
                existing_source="extracted",
                incoming="ACME",
                incoming_source="synced_xero",
            )
        )
        assert out is Verdict.NOOP

    def test_identical_with_whitespace_diff_is_noop(self) -> None:
        # Trim before compare — "ACME" and " ACME " are the same
        # value to a customer.
        out = classify_merge(
            _inputs(
                existing="ACME",
                existing_source="manual",
                incoming=" ACME ",
                incoming_source="synced_csv",
            )
        )
        assert out is Verdict.NOOP


# =============================================================================
# Same-source synced overwrite.
# =============================================================================


class TestSameSourceOverwrite:
    def test_same_connector_overwrites_silently(self) -> None:
        # Customer renamed an account in AutoCount. Re-sync from
        # AutoCount = the connector's source-of-truth changed; we
        # should follow.
        out = classify_merge(
            _inputs(
                existing="OldName",
                existing_source="synced_autocount",
                incoming="NewName",
                incoming_source="synced_autocount",
            )
        )
        assert out is Verdict.AUTO_OVERWRITE

    def test_xero_to_xero_overwrites(self) -> None:
        out = classify_merge(
            _inputs(
                existing="Old",
                existing_source="synced_xero",
                incoming="New",
                incoming_source="synced_xero",
            )
        )
        assert out is Verdict.AUTO_OVERWRITE

    def test_csv_to_csv_overwrites(self) -> None:
        out = classify_merge(
            _inputs(
                existing="Old",
                existing_source="synced_csv",
                incoming="New",
                incoming_source="synced_csv",
            )
        )
        assert out is Verdict.AUTO_OVERWRITE


# =============================================================================
# Cross-source / cross-provenance conflicts.
# =============================================================================


class TestConflict:
    def test_synced_x_vs_synced_y_is_conflict(self) -> None:
        # Customer has the same buyer in Xero AND in QuickBooks
        # with different addresses. Don't pick — ask the human.
        out = classify_merge(
            _inputs(
                existing="Address Xero",
                existing_source="synced_xero",
                incoming="Address QB",
                incoming_source="synced_quickbooks",
            )
        )
        assert out is Verdict.CONFLICT

    def test_extracted_vs_external_is_conflict(self) -> None:
        # The LLM extracted "Acme Inc." from a real invoice; the
        # connector says "Acme Sdn Bhd". Both could be right — the
        # invoice header's wording vs the system-of-record entry.
        out = classify_merge(
            _inputs(
                existing="Acme Inc.",
                existing_source="extracted",
                incoming="Acme Sdn Bhd",
                incoming_source="synced_autocount",
            )
        )
        assert out is Verdict.CONFLICT

    def test_manual_vs_external_is_conflict(self) -> None:
        # User typed something in the customer detail page; the
        # connector wants to override. The user's edit is durable
        # signal even without a lock — kick to the queue.
        out = classify_merge(
            _inputs(
                existing="Manually entered",
                existing_source="manual",
                incoming="Synced value",
                incoming_source="synced_xero",
            )
        )
        assert out is Verdict.CONFLICT

    def test_manually_resolved_vs_external_is_conflict(self) -> None:
        # User picked this value in a previous conflict-queue run.
        # A new sync that wants to overwrite must go through the
        # queue again — the resolution doesn't auto-pin (that's
        # what locks are for, separately).
        out = classify_merge(
            _inputs(
                existing="ResolvedValue",
                existing_source="manually_resolved",
                incoming="NewSynced",
                incoming_source="synced_xero",
            )
        )
        assert out is Verdict.CONFLICT

    def test_extracted_vs_extracted_different_invoice_is_conflict(self) -> None:
        # Two invoices for the same buyer report different
        # addresses (one had a typo). Resolution queue is the
        # right place — neither is silently authoritative.
        out = classify_merge(
            _inputs(
                existing="Address A",
                existing_source="extracted",
                incoming="Address B",
                incoming_source="extracted",
            )
        )
        assert out is Verdict.CONFLICT

    def test_no_existing_provenance_yet_differing_value_is_conflict(
        self,
    ) -> None:
        # Edge case: existing value exists but provenance dict has
        # no entry for this field (pre-Slice-73 row that wasn't
        # backfilled, or a future field the migration didn't cover).
        # Default to conservative — conflict, not silent overwrite.
        out = classify_merge(
            _inputs(
                existing="Mystery",
                existing_source=None,
                incoming="ConnectorValue",
                incoming_source="synced_xero",
            )
        )
        assert out is Verdict.CONFLICT


# =============================================================================
# Determinism — same inputs always return the same verdict.
# =============================================================================


class TestDeterminism:
    def test_classify_merge_is_pure(self) -> None:
        ins = _inputs(
            existing="OldName",
            existing_source="synced_autocount",
            incoming="NewName",
            incoming_source="synced_autocount",
        )
        # Five back-to-back runs all return the same answer. No
        # hidden state that could drift with time / random.
        verdicts = {classify_merge(ins) for _ in range(5)}
        assert verdicts == {Verdict.AUTO_OVERWRITE}
