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
def sign_invoice(self, invoice_id: str) -> dict[str, object]:  # noqa: ANN001
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
def submit_to_lhdn(self, invoice_id: str) -> dict[str, object]:  # noqa: ANN001
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
def poll_invoice_status(self, invoice_id: str) -> dict[str, object]:  # noqa: ANN001
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
