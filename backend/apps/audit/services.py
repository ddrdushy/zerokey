"""Audit log service interface.

Other contexts call ``record_event(...)`` to append; nothing else writes to
the AuditEvent table directly. The function:

  1. Acquires a Postgres advisory lock so concurrent writers serialize.
  2. Reads the previous event's ``chain_hash`` (or ``GENESIS_PREV_HASH``).
  3. Builds the canonical event body (everything except the derived hashes).
  4. Computes ``content_hash`` and ``chain_hash``.
  5. Inserts the row in the same transaction.

The advisory lock id is fixed (see ``_AUDIT_ADVISORY_LOCK_ID``). Postgres
serializes any session that asks for the same lock id, which is exactly what
we need for gap-free sequencing.

On non-PostgreSQL backends (the SQLite-in-memory test database) we fall back
to a select-max approach inside the transaction. This is racy under real
concurrency but is acceptable for unit tests, which run single-threaded.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.db import connection, models, transaction
from django.db.models.functions import TruncDate
from django.utils import timezone

from .chain import GENESIS_PREV_HASH, ChainIntegrityError, compute_hashes, verify_link
from .models import AuditEvent, ChainVerificationRun

logger = logging.getLogger(__name__)


def _next_sequence() -> int:
    """Atomically reserve the next gap-free sequence number.

    On PostgreSQL we keep a dedicated single-row counter and increment it via
    ``UPDATE … RETURNING``. Postgres serializes concurrent UPDATEs on the same
    row through MVCC row locks — no advisory lock needed, no race window
    between SELECT and INSERT. Inside the caller's ``transaction.atomic()``
    block, a rollback unwinds the increment alongside the audit row insert,
    so gap-free is preserved.

    On SQLite (test db) we fall back to ``max + 1`` since SQLite tests are
    single-threaded.
    """
    if connection.vendor != "postgresql":
        last = AuditEvent.objects.order_by("-sequence").values_list("sequence", flat=True).first()
        return 1 if last is None else last + 1

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO audit_sequence (id, value)
            VALUES (1, 1)
            ON CONFLICT (id) DO UPDATE SET value = audit_sequence.value + 1
            RETURNING value;
            """
        )
        return int(cursor.fetchone()[0])


def _previous_chain_hash() -> bytes:
    last = AuditEvent.objects.order_by("-sequence").values_list("chain_hash", flat=True).first()
    if last is None:
        return GENESIS_PREV_HASH
    # BinaryField round-trips as bytes on Postgres and memoryview on some backends.
    return bytes(last)


def record_event(
    *,
    action_type: str,
    actor_type: AuditEvent.ActorType | str,
    actor_id: str = "",
    organization_id: str | None = None,
    affected_entity_type: str = "",
    affected_entity_id: str = "",
    payload: dict[str, Any] | None = None,
    payload_schema_version: int = 1,
    timestamp: datetime | None = None,
) -> AuditEvent:
    """Append a single event to the audit log.

    All hashing happens inside the transaction so a rollback never leaves a
    half-linked row. Callers should not pre-compute hashes.
    """
    payload = payload or {}
    ts = timestamp or timezone.now()
    actor = AuditEvent.ActorType(actor_type) if isinstance(actor_type, str) else actor_type

    with transaction.atomic():
        sequence = _next_sequence()
        previous_chain_hash = _previous_chain_hash()

        body = _canonical_body(
            sequence=sequence,
            timestamp=ts,
            organization_id=organization_id,
            actor_type=actor.value,
            actor_id=actor_id,
            action_type=action_type,
            affected_entity_type=affected_entity_type,
            affected_entity_id=affected_entity_id,
            payload=payload,
            payload_schema_version=payload_schema_version,
        )
        hashes = compute_hashes(body, previous_chain_hash)

        event = AuditEvent.objects.create(
            sequence=sequence,
            timestamp=ts,
            organization_id=organization_id,
            actor_type=actor.value,
            actor_id=actor_id,
            action_type=action_type,
            affected_entity_type=affected_entity_type,
            affected_entity_id=affected_entity_id,
            payload=payload,
            payload_schema_version=payload_schema_version,
            content_hash=hashes.content_hash,
            chain_hash=hashes.chain_hash,
        )
        return event


def _canonical_body(
    *,
    sequence: int,
    timestamp: datetime,
    organization_id: str | None,
    actor_type: str,
    actor_id: str,
    action_type: str,
    affected_entity_type: str,
    affected_entity_id: str,
    payload: dict[str, Any],
    payload_schema_version: int,
) -> dict[str, Any]:
    """Assemble the dict that gets canonicalized and hashed."""
    return {
        "action_type": action_type,
        "actor_id": actor_id,
        "actor_type": actor_type,
        "affected_entity_id": affected_entity_id,
        "affected_entity_type": affected_entity_type,
        "organization_id": organization_id,
        "payload": payload,
        "payload_schema_version": payload_schema_version,
        "sequence": sequence,
        "timestamp": timestamp.isoformat(timespec="milliseconds"),
    }


def stats_for_organization(
    *, organization_id: UUID | str, sparkline_days: int = 7
) -> dict[str, Any]:
    """Aggregate counts of this org's audit events for the dashboard KPI tile.

    Returns:
        ``total``        — all-time count of events for the org.
        ``last_24h``     — events in the last 24 hours.
        ``last_7d``      — events in the last 7 days.
        ``sparkline``    — list of ``{date, count}`` for the last
                           ``sparkline_days`` days, oldest first, gap-filled
                           with zero-count days so the front-end renders a
                           full rolling window.

    System events (``organization_id IS NULL``) are excluded — the tile shows
    the customer's own activity, not platform housekeeping. RLS filters
    cross-tenant rows at the DB layer; the explicit filter is belt-and-suspenders.
    """
    base = AuditEvent.objects.filter(organization_id=organization_id)
    now = timezone.now()

    total = base.count()
    last_24h = base.filter(timestamp__gte=now - timedelta(hours=24)).count()
    last_7d = base.filter(timestamp__gte=now - timedelta(days=7)).count()

    sparkline = _daily_sparkline(base, now=now, days=sparkline_days)

    return {
        "total": total,
        "last_24h": last_24h,
        "last_7d": last_7d,
        "sparkline": sparkline,
    }


def _daily_sparkline(queryset, *, now: datetime, days: int) -> list[dict[str, Any]]:
    """Bucket a queryset by the date of ``timestamp`` for the last ``days``.

    Gap-fills missing days with zero so the front-end always gets a series of
    length ``days`` ending today (in the request's timezone).
    """
    today = timezone.localdate(now)
    start = today - timedelta(days=days - 1)

    rows = (
        queryset.filter(timestamp__date__gte=start)
        .annotate(day=TruncDate("timestamp"))
        .values("day")
        .annotate(count=models.Count("id"))
    )
    by_day: dict[str, int] = {row["day"].isoformat(): int(row["count"]) for row in rows}

    series: list[dict[str, Any]] = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        series.append({"date": day.isoformat(), "count": by_day.get(day.isoformat(), 0)})
    return series


def list_events_for_organization(
    *,
    organization_id: UUID | str,
    action_type: str | None = None,
    limit: int = 50,
    before_sequence: int | None = None,
) -> list[AuditEvent]:
    """List audit events for an organization, newest first.

    Used by the customer-facing audit log page. Tenant-scoped — RLS
    belt-and-suspenders. ``action_type`` filters by exact match; the
    UI's "all" filter passes ``None``. ``before_sequence`` is the
    pagination cursor (each page returns events strictly older than
    the last-seen sequence number).

    Pagination via sequence number rather than offset keeps the
    query cheap as the log grows: the index on
    ``(organization, sequence)`` makes both filters point lookups.
    """
    qs = AuditEvent.objects.filter(organization_id=organization_id)
    if action_type:
        qs = qs.filter(action_type=action_type)
    if before_sequence is not None:
        qs = qs.filter(sequence__lt=before_sequence)
    return list(qs.order_by("-sequence")[:limit])


def list_action_types_for_organization(*, organization_id: UUID | str) -> list[str]:
    """Distinct action types present on the org's audit log.

    Drives the filter dropdown on the audit log page so the user only
    sees codes that actually appear in their data. Sorted alphabetically
    so the dropdown order is stable.

    The ``order_by()`` clearing matters: AuditEvent's default
    ``Meta.ordering = ["sequence"]`` would otherwise add sequence to the
    SELECT column list and defeat ``DISTINCT`` (every row's sequence is
    unique, so every action_type would appear once per row that emitted
    it). Explicit no-ordering query.
    """
    return sorted(
        AuditEvent.objects.filter(organization_id=organization_id)
        .order_by()
        .values_list("action_type", flat=True)
        .distinct()
    )


def count_events_for_organization(*, organization_id: UUID | str) -> int:
    """Total event count for the org. Renders as a context strip on the page."""
    return AuditEvent.objects.filter(organization_id=organization_id).count()


def _run_chain_verification(*, source: ChainVerificationRun.Source) -> ChainVerificationRun:
    """Execute one chain verification and record a ``ChainVerificationRun`` row.

    Shared core for both the customer-triggered (manual) call and the
    Celery beat task (scheduled). Returns the persisted run so the caller
    can build any external response or audit shape it needs.

    The run is recorded for *every* outcome — including ``error`` — so the
    audit page can surface "we tried at T, it errored" rather than going
    silent on infrastructure failures. ``error_detail`` is operational only
    and never leaves the API server.
    """
    # Lazy import to avoid circular: tenancy reads from audit on init.
    from apps.identity.tenancy import super_admin_context

    run = ChainVerificationRun.objects.create(
        status=ChainVerificationRun.Status.OK,  # provisional; overwritten before save
        source=source,
        events_verified=0,
    )
    try:
        with super_admin_context(reason=f"audit.verify_chain:{source}"):
            count = verify_chain()
        run.status = ChainVerificationRun.Status.OK
        run.events_verified = count
    except ChainIntegrityError as exc:
        run.status = ChainVerificationRun.Status.TAMPERED
        run.events_verified = 0
        run.error_detail = str(exc)
        # Log to ops with the offending sequence so the team can investigate.
        # The customer-facing path intentionally omits the sequence since it
        # might point at another tenant's event.
        logger.error("audit chain integrity check failed: %s", exc)
    except Exception as exc:
        # Anything non-tamper (DB unreachable, OOM, …) is recorded as ``error``
        # rather than swallowed — silent failure on a trust surface is worse
        # than an explicit "we couldn't run the check at T".
        run.status = ChainVerificationRun.Status.ERROR
        run.events_verified = 0
        run.error_detail = f"{type(exc).__name__}: {exc}"
        logger.exception("audit chain verification raised unexpectedly")
    finally:
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "events_verified", "error_detail", "completed_at"])
    return run


def verify_chain_for_visibility(
    *, organization_id: UUID | str, actor_user_id: UUID | str
) -> dict[str, Any]:
    """Customer-triggered chain verification.

    The audit chain is *global* (events from every tenant participate
    in one sequence; a row's ``chain_hash`` links to the previous row's
    regardless of which tenant produced it). A per-tenant verification
    would still have to walk the global sequence to validate any tenant
    row, so this elevates briefly to super-admin, runs the full chain
    verifier, and returns a customer-tailored summary.

    Cross-tenant information control: on tamper detection we DO NOT
    return the offending sequence number to the customer (it might
    point at another tenant's event). The caller gets only "tampering
    detected; contact support" — the underlying sequence is logged for
    operations.

    Audited: emits one ``audit.chain_verified`` event per call,
    organization-scoped to the requester. Same shape as every other
    customer-initiated action.
    """
    run = _run_chain_verification(source=ChainVerificationRun.Source.MANUAL)
    ok = run.status == ChainVerificationRun.Status.OK

    # Audit the verification act itself under normal RLS so the customer
    # sees their own verify call in their own log. ``error`` runs (e.g. DB
    # transient) are surfaced as not-ok with the same generic message —
    # the customer doesn't need to distinguish "tampered" from "couldn't
    # run", both mean "ops needs to look at this".
    record_event(
        action_type="audit.chain_verified",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(organization_id),
        affected_entity_type="AuditChain",
        affected_entity_id="",
        payload={
            "ok": ok,
            "events_verified": run.events_verified,
        },
    )

    return {
        "ok": ok,
        "events_verified": run.events_verified,
        # Generic message — never the underlying sequence number, which
        # could belong to another tenant.
        "tampering_detected": run.status == ChainVerificationRun.Status.TAMPERED,
        "support_message": (
            "All audit events verified — your chain is intact."
            if ok
            else "Chain integrity check failed. Operations has been alerted."
        ),
    }


def run_scheduled_chain_verification() -> ChainVerificationRun:
    """Background-task entry point.

    Called by ``apps.audit.tasks.verify_audit_chain`` on the beat
    schedule. Records a ``scheduled`` run and emits a system-level
    audit event (``organization_id=NULL``, ``actor_type=service``)
    so the verification activity itself is auditable.
    """
    run = _run_chain_verification(source=ChainVerificationRun.Source.SCHEDULED)
    ok = run.status == ChainVerificationRun.Status.OK

    # System-level event: no tenant, actor is the service. Operations sees
    # these in cross-tenant queries; tenants don't see them in their log.
    record_event(
        action_type="audit.chain_verified",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="audit.verify_audit_chain",
        organization_id=None,
        affected_entity_type="AuditChain",
        affected_entity_id="",
        payload={
            "ok": ok,
            "events_verified": run.events_verified,
            "source": "scheduled",
        },
    )
    return run


def latest_chain_verification() -> dict[str, Any] | None:
    """Customer-facing view of the most recent verification run.

    Returns ``None`` when no run has occurred yet (fresh deployment, no
    beat tick since startup). Otherwise returns a redacted shape: status,
    events_verified, when it ran, and a customer-safe message — never
    ``error_detail`` (operational) or the offending sequence number
    (cross-tenant).

    Both manual and scheduled runs are visible in the same shape, so the
    audit page can render "Last verified 12 minutes ago — all clean"
    regardless of who triggered it.
    """
    run = ChainVerificationRun.objects.order_by("-started_at").first()
    if run is None:
        return None
    ok = run.status == ChainVerificationRun.Status.OK
    return {
        "status": run.status,
        "ok": ok,
        "events_verified": run.events_verified,
        "source": run.source,
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "support_message": (
            "All audit events verified — your chain is intact."
            if ok
            else "Chain integrity check failed. Operations has been alerted."
        ),
    }


def verify_chain() -> int:
    """Re-hash every event in order and confirm the chain is intact.

    Returns the number of events verified. Raises ``ChainIntegrityError`` on
    the first mismatch with the offending sequence number in the message.
    """
    previous_chain_hash = GENESIS_PREV_HASH
    count = 0
    for event in AuditEvent.objects.order_by("sequence").iterator():
        body = _canonical_body(
            sequence=event.sequence,
            timestamp=event.timestamp,
            organization_id=str(event.organization_id) if event.organization_id else None,
            actor_type=event.actor_type,
            actor_id=event.actor_id,
            action_type=event.action_type,
            affected_entity_type=event.affected_entity_type,
            affected_entity_id=event.affected_entity_id,
            payload=event.payload,
            payload_schema_version=event.payload_schema_version,
        )
        try:
            verify_link(
                event_body=body,
                expected_content_hash=bytes(event.content_hash),
                previous_chain_hash=previous_chain_hash,
                expected_chain_hash=bytes(event.chain_hash),
            )
        except ChainIntegrityError as exc:
            raise ChainIntegrityError(f"sequence={event.sequence}: {exc}") from exc

        previous_chain_hash = bytes(event.chain_hash)
        count += 1

    return count
