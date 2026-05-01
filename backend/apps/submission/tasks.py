"""Celery tasks for the submission context (real impl from Slice 58).

The signing task routes to the dedicated ``signing`` queue, which
runs on isolated worker containers (see ARCHITECTURE.md, "The
signing service"). In production those containers have read-only
S3 access scoped to the customer-certificates prefix and KMS
decrypt access to the certificate envelope key — nothing else.
The blast radius of a compromise is bounded by these IAM controls,
not by application code.

Today's storage: encrypted-at-rest inline columns on the
Organization (Slice 58). Production swap to KMS-stored S3 blobs
is a one-line change in ``apps.submission.certificates._load`` —
the rest of the pipeline doesn't move.
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="submission.sign_invoice",
    queue="signing",
    bind=True,
    max_retries=2,
    acks_late=True,
)
def sign_invoice(self, invoice_id: str) -> dict[str, object]:
    """Sign an invoice payload with the customer's LHDN cert.

    Calls into ``apps.submission.lhdn_submission.sign_invoice``. The
    function audits + records outcome on the Invoice itself; this
    wrapper just returns a small dict for log enrichment.
    """
    from . import lhdn_submission

    try:
        result = lhdn_submission.sign_invoice(invoice_id)
    except lhdn_submission.SubmissionError as exc:
        logger.warning(
            "submission.sign_invoice.error",
            extra={"invoice_id": invoice_id, "error": str(exc)},
        )
        return {"invoice_id": invoice_id, "ok": False, "reason": str(exc)}
    # Strip the bytes payload — we don't want bytes flowing through
    # Celery's result backend.
    return {
        "invoice_id": invoice_id,
        "ok": result.get("ok", False),
        "digest_hex": result.get("digest_hex", ""),
        "cert_kind": result.get("cert_kind", ""),
        "reason": result.get("reason", ""),
    }


@shared_task(
    name="submission.submit_to_lhdn",
    queue="high",
    bind=True,
    max_retries=3,
    acks_late=True,
)
def submit_to_lhdn(self, invoice_id: str) -> dict[str, object]:
    """Sign-then-submit an invoice to LHDN MyInvois.

    Returns a small status dict. Real per-invoice state lands on
    the Invoice row + the audit chain — this wrapper is for log
    enrichment + worker observability only.
    """
    from . import lhdn_submission

    try:
        result = lhdn_submission.submit_invoice_to_lhdn(invoice_id)
    except lhdn_submission.SubmissionError as exc:
        return {"invoice_id": invoice_id, "ok": False, "reason": str(exc)}
    return {
        "invoice_id": invoice_id,
        "ok": result.get("ok", False),
        "submission_uid": result.get("submission_uid", ""),
        "reason": result.get("reason", ""),
    }


# LHDN spec §4.2 polling cadence: 2s → 4s → 8s → 16s → 30s (max).
# Stop when overallStatus != "InProgress". The task self-reschedules
# with these countdowns rather than relying on a fixed Celery
# retry_backoff; matching the published cadence keeps us inside
# LHDN's expected access pattern.
POLL_BACKOFF_SECONDS = (2, 4, 8, 16, 30)
POLL_MAX_ATTEMPTS = 12  # 30s × ~6 = ~3 minutes after backoff plateaus


@shared_task(
    name="submission.poll_invoice_status",
    queue="default",
    bind=True,
    max_retries=POLL_MAX_ATTEMPTS,
    acks_late=True,
)
def poll_invoice_status(self, invoice_id: str) -> dict[str, object]:
    """Poll LHDN for one invoice's submission status.

    Self-reschedules with an exponential-then-plateau backoff
    matching the integration spec. Stops when the document is in a
    terminal state (Valid / Invalid / Cancelled) or the retry
    budget is exhausted.
    """
    from . import lhdn_submission

    try:
        result = lhdn_submission.poll_invoice_status(invoice_id)
    except lhdn_submission.SubmissionError as exc:
        return {"invoice_id": invoice_id, "ok": False, "reason": str(exc)}

    document_status = result.get("document_status", "") or ""
    out = {
        "invoice_id": invoice_id,
        "ok": result.get("ok", False),
        "document_status": document_status,
        "lhdn_uuid": result.get("lhdn_uuid", ""),
    }

    # Terminal states → stop polling.
    if document_status in {"Valid", "Invalid", "Cancelled"}:
        return out

    # Non-terminal → schedule the next poll. Pick the next backoff
    # from the cadence; clamp to the last value once we're past it.
    attempt = self.request.retries
    if attempt >= self.max_retries:
        # Out of retry budget. Operator can re-trigger via the
        # /poll-lhdn/ endpoint manually.
        out["reason"] = "polling-budget-exhausted"
        return out

    cadence_idx = min(attempt, len(POLL_BACKOFF_SECONDS) - 1)
    countdown = POLL_BACKOFF_SECONDS[cadence_idx]
    raise self.retry(countdown=countdown)


# Slice 69 — beat-scheduled sweep for stuck-SUBMITTING invoices.
#
# The per-invoice poll chain (above) covers the happy path: submit
# → poll every 2/4/8/16/30s up to ~3 minutes. But the chain breaks
# if the worker restarts mid-sequence, the retry budget exhausts,
# or LHDN takes longer than 3 minutes to validate (rare but
# observed under load).
#
# Without a sweep, those invoices sit in SUBMITTING forever from
# the customer's perspective even though LHDN has long since
# validated them. The sweep reconciles every minute by re-queueing
# poll_invoice_status for any invoice that:
#   - is still in SUBMITTING
#   - has a submission_uid (i.e. actually reached LHDN)
#   - was last touched > SWEEP_STALE_AFTER_SECONDS ago (so we
#     don't double-poll the per-invoice chain)
#
# The sweep itself doesn't call LHDN — it just queues poll tasks
# on the default queue. The polls run on workers + obey the
# spec's cadence + budget.

SWEEP_STALE_AFTER_SECONDS = 120  # 2 minutes — past the per-invoice
# chain's plateau, so we only sweep
# invoices the chain has missed.
SWEEP_MAX_PER_RUN = 100  # Safety cap. A backlog past this is its
# own problem worth alerting on.


@shared_task(
    name="submission.dispatch_scheduled",
    queue="low",
    acks_late=True,
)
def dispatch_scheduled() -> dict[str, object]:
    """Slice 96 — fire submit on invoices whose ``scheduled_submit_at`` is due.

    Runs on a 1-minute beat schedule. Picks up rows where:
      - ``scheduled_submit_at`` is non-null AND in the past,
      - ``status`` is ``ready_for_review`` (not already in flight,
        not validated, not rejected).

    For each match, clears ``scheduled_submit_at`` (so a re-run
    doesn't double-fire even if the submit is still queued) and
    queues the submit task. The submit pipeline runs the same
    pre-flight validation it always does — if the invoice has
    drifted out of submittable state, it'll surface the issues
    cleanly rather than silently fail.
    """
    from datetime import timezone as _tz

    from django.utils import timezone

    from apps.identity.tenancy import super_admin_context

    from .models import Invoice

    now = timezone.now().astimezone(_tz.utc)
    dispatched: list[str] = []
    with super_admin_context(reason="submission.dispatch_scheduled"):
        due = list(
            Invoice.objects.filter(
                status=Invoice.Status.READY_FOR_REVIEW,
                scheduled_submit_at__isnull=False,
                scheduled_submit_at__lte=now,
            ).order_by("scheduled_submit_at")[:50]
        )
        for inv in due:
            inv.scheduled_submit_at = None
            inv.save(update_fields=["scheduled_submit_at", "updated_at"])
            # Queue the existing per-invoice submit task — same path
            # the user-clicked submit takes, so signing + LHDN call
            # + audit all run identically.
            submit_to_lhdn.delay(str(inv.id))
            dispatched.append(str(inv.id))
    if dispatched:
        logger.info("submission.dispatch_scheduled.fired", extra={"count": len(dispatched)})
    return {"dispatched": len(dispatched)}


@shared_task(
    name="submission.sweep_inflight_polls",
    queue="low",
    acks_late=True,
)
def sweep_inflight_polls() -> dict[str, object]:
    """Find SUBMITTING invoices that the per-invoice poll missed +
    re-queue ``poll_invoice_status`` for each.

    Idempotent: re-queueing a poll for an invoice that just
    transitioned to a terminal state inside ``poll_invoice_status``
    is a cheap no-op — the function returns early with the new
    status. Worst case is one extra LHDN GET per invoice per
    sweep cycle.
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.identity.tenancy import super_admin_context

    from .models import Invoice

    cutoff = timezone.now() - timedelta(seconds=SWEEP_STALE_AFTER_SECONDS)
    with super_admin_context(reason="submission.sweep"):
        stale = list(
            Invoice.objects.filter(
                status=Invoice.Status.SUBMITTING,
            )
            .exclude(submission_uid="")
            .filter(updated_at__lte=cutoff)
            .order_by("updated_at")
            .values_list("id", flat=True)[:SWEEP_MAX_PER_RUN]
        )

    for invoice_id in stale:
        poll_invoice_status.delay(str(invoice_id))

    if stale:
        logger.info(
            "submission.sweep_inflight_polls.dispatched",
            extra={"count": len(stale)},
        )
    return {"requeued": len(stale)}
