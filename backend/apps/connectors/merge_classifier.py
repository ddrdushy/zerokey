"""Per-field merge classifier (Slice 74).

The pure-function backbone of the two-phase sync. ``classify_merge``
takes the existing master-row state for one field + the incoming
value/source from the connector + any field-level lock that
applies, and returns one of six verdicts. The propose path
(Slice 75) walks every connector record × every mapped field
through this and routes the result into the right diff bucket
(``would_add`` / ``would_update`` / ``conflicts`` / ``skipped_*``).

The classifier itself is intentionally unaware of:
  - Which connector ran (it sees the source string only).
  - Which master record is being touched (callers do row-level
    ID resolution before invoking).
  - The audit log (the propose path emits the audit event for
    the run; per-field classification is too granular to audit
    individually — the diff blob carries the per-field detail).

Audit replay: re-running the classifier with the same inputs
must always return the same verdict. The function is pure +
deterministic — no DB reads, no time, no env. Callers pass any
state they need (locks, verification state) as inputs.

Matrix (named tests for every cell live in test_classify_merge.py):

  | existing state                       | incoming               | result               |
  | ------------------------------------ | ---------------------- | -------------------- |
  | empty                                | any non-empty          | ``auto_populate``    |
  | empty                                | empty                  | ``noop``             |
  | identical to incoming                | any                    | ``noop``             |
  | ``synced_X``                         | ``synced_X`` (same)    | ``auto_overwrite``   |
  | ``synced_X``                         | ``synced_Y`` (diff)    | ``conflict``         |
  | ``extracted``                        | any external           | ``conflict``         |
  | ``manual``                           | any external           | ``conflict``         |
  | ``manually_resolved``                | any                    | ``conflict``         |
  | ``verified_lhdn`` (verified TIN)     | any                    | ``skipped_verified`` |
  | locked (``MasterFieldLock`` present) | any                    | ``skipped_locked``   |

Locked + verified take precedence over everything else: a
verified TIN that's also locked routes to ``skipped_locked``
(locks are stronger than provenance trust ranks). The ordering
in the implementation matches the table — locked first, then
verified, then provenance-driven outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Verdict(str, Enum):
    """The six outcomes of one (existing, incoming) field comparison."""

    AUTO_POPULATE = "auto_populate"
    NOOP = "noop"
    AUTO_OVERWRITE = "auto_overwrite"
    CONFLICT = "conflict"
    SKIPPED_LOCKED = "skipped_locked"
    SKIPPED_VERIFIED = "skipped_verified"


@dataclass(frozen=True)
class ClassifyInputs:
    """All the state ``classify_merge`` needs.

    Bundled in a frozen dataclass rather than positional args so
    callers can't accidentally swap ``existing_value`` and
    ``incoming_value`` (a frequent and silent bug otherwise — the
    types are both ``str``).
    """

    # The current master-row value for this field, normalised to a
    # plain string. ``""`` for empty / unset fields — matches the
    # JSONField default + how the master rows store blank fields.
    existing_value: str

    # The current provenance entry for this field, or ``None`` if
    # the master has never had this field populated. We use the
    # ``source`` key of the entry — other keys are metadata and
    # don't affect classification.
    existing_provenance: dict | None

    # The value the connector wants to write.
    incoming_value: str

    # The connector's source tag. Always one of the
    # ``synced_*`` strings (or ``"manually_resolved"`` for
    # conflict-queue resolution flows that re-enter
    # ``classify_merge``). Drives the same-source vs different-
    # source branch.
    incoming_source: str

    # True iff a ``MasterFieldLock`` exists for this
    # (master_type, master_id, field_name). Read by the caller
    # from the lock table once per master record + cached for
    # the loop; ``classify_merge`` itself does no DB reads.
    is_locked: bool

    # True iff the field is the master's TIN AND the master's
    # ``tin_verification_state`` is ``verified``. The classifier
    # generalises this as "is the existing value backed by an
    # authority stronger than any connector?". Today TIN-via-LHDN
    # is the only such authority; future fields with their own
    # external verification (e.g. SSL-verified email) plug in here.
    is_authority_verified: bool


def classify_merge(inputs: ClassifyInputs) -> Verdict:
    """Return the merge verdict for one field × one incoming value.

    See module docstring for the full matrix; implementation order
    matches the table top-to-bottom:

      1. Locked → ``skipped_locked`` (locks beat everything).
      2. Authority-verified → ``skipped_verified``.
      3. Empty existing → ``auto_populate`` (or ``noop`` if both empty).
      4. Identical values → ``noop`` (regardless of source).
      5. Same-source synced overwrite → ``auto_overwrite``.
      6. Anything else → ``conflict``.
    """
    # Step 1 — locked. A locked field is always conflict-queue
    # material; we still surface the "skipped" outcome so the user
    # sees the would-be change in the diff preview without it
    # auto-applying. Bulk lock-aware resolution lives in Slice 75+.
    if inputs.is_locked:
        return Verdict.SKIPPED_LOCKED

    # Step 2 — authority-verified. The TIN that LHDN said is real
    # outranks any connector's claim about it. Slice 75 surfaces
    # the would-be change as a "skipped_verified" entry in the
    # diff so the user can manually elect to override (rare path).
    if inputs.is_authority_verified:
        return Verdict.SKIPPED_VERIFIED

    incoming = (inputs.incoming_value or "").strip()
    existing = (inputs.existing_value or "").strip()

    # Step 3 — empty existing.
    if not existing:
        if not incoming:
            # Both empty — connector has nothing to add, master
            # has nothing to lose.
            return Verdict.NOOP
        return Verdict.AUTO_POPULATE

    # Step 4 — identical values.
    if existing == incoming:
        return Verdict.NOOP

    # At this point existing is non-empty, incoming differs, no
    # lock, no authority. The provenance source determines whether
    # we trust the incoming write or kick to the conflict queue.
    existing_source = ((inputs.existing_provenance or {}).get("source") or "").strip()

    # Step 5 — same-source synced overwrite. If both the existing
    # value and the incoming value come from the same connector,
    # the incoming one is by definition fresher (it's what's in
    # the source system right now). Auto-overwrite is the right
    # call — the customer's source-of-truth for this connector
    # changed.
    if existing_source.startswith("synced_") and existing_source == inputs.incoming_source:
        return Verdict.AUTO_OVERWRITE

    # Step 6 — everything else: differing values + different
    # provenances → human disposes.
    return Verdict.CONFLICT
