"""Celery tasks for the extraction pipeline.

The general worker (queue ``high``) handles extraction. Signing has its own
isolated worker on the ``signing`` queue.

Per ARCHITECTURE.md task discipline: idempotent (``run_extraction`` is a
no-op if the job is past the received state), exponential backoff on
transient failures, dead-letter on exhaustion.
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="extraction.structure_invoice",
    queue="high",
    max_retries=0,
    acks_late=False,
)
def structure_invoice(invoice_id: str) -> dict[str, str | float | int]:
    """Run FieldStructure on an invoice's raw text and populate Invoice fields."""
    from apps.identity.tenancy import set_tenant, super_admin_context
    from apps.submission.services import structure_invoice as _structure

    logger.info("structure_invoice: starting invoice=%s", invoice_id)
    # Worker has no tenant context; brief-elevate to find the org, then pin.
    with super_admin_context(reason="extraction.pipeline:invoice_lookup"):
        from apps.submission.models import Invoice

        invoice = Invoice.objects.get(id=invoice_id)
    set_tenant(invoice.organization_id)

    try:
        result = _structure(invoice_id)
    except Exception:
        logger.exception("structure_invoice: failed invoice=%s", invoice_id)
        raise
    logger.info(
        "structure_invoice: complete invoice=%s engine=%s confidence=%s lines=%s",
        invoice_id,
        result.engine,
        result.overall_confidence,
        result.line_count,
    )
    return {
        "invoice_id": str(result.invoice.id),
        "engine": result.engine,
        "confidence": result.overall_confidence,
        "line_count": result.line_count,
    }


SWEEP_STUCK_AFTER_SECONDS = 300  # 5 minutes
SWEEP_MAX_PER_RUN = 100  # Same safety cap as the SUBMITTING sweep.

# States a job can land in mid-pipeline. If a job sits in any of
# these for ``SWEEP_STUCK_AFTER_SECONDS`` it's almost certainly
# stranded — the worker crashed (e.g. the Slice 60 amendment-column
# IntegrityError that Slice 90 fixed) and the job will never
# advance on its own. The sweep transitions it to ``error`` with
# an explanatory message so the inbox / dashboard reflects reality
# instead of pretending the job is still in flight.
_STUCK_STATES = ("received", "classifying", "extracting", "enriching", "validating")


@shared_task(
    name="extraction.sweep_stuck_jobs",
    queue="low",
    acks_late=True,
)
def sweep_stuck_jobs() -> dict[str, object]:
    """Mark IngestionJobs stranded in non-terminal states as ``error``.

    Idempotent: once a job is in a terminal state the sweep never
    touches it. Runs on celery beat every couple of minutes —
    cheap query, only writes when something is actually stuck.
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.identity.tenancy import super_admin_context
    from apps.ingestion.models import IngestionJob

    cutoff = timezone.now() - timedelta(seconds=SWEEP_STUCK_AFTER_SECONDS)
    with super_admin_context(reason="extraction.sweep_stuck"):
        stuck = list(
            IngestionJob.objects.filter(
                status__in=_STUCK_STATES,
                updated_at__lte=cutoff,
            ).order_by("updated_at")[:SWEEP_MAX_PER_RUN]
        )
        for job in stuck:
            prior_status = job.status
            job.status = IngestionJob.Status.ERROR
            job.error_message = (
                f"Stuck in {prior_status} for >{SWEEP_STUCK_AFTER_SECONDS // 60} min — "
                f"swept by extraction.sweep_stuck_jobs"
            )[:8000]
            job.save(update_fields=["status", "error_message", "updated_at"])

    if stuck:
        logger.warning(
            "extraction.sweep_stuck_jobs.swept",
            extra={"count": len(stuck), "ids": [str(j.id) for j in stuck]},
        )
    return {"swept": len(stuck)}


@shared_task(
    name="extraction.extract_invoice",
    queue="high",
    max_retries=0,
    acks_late=False,
)
def extract_invoice(job_id: str) -> dict[str, str | float | int]:
    """Run the extraction pipeline for a single IngestionJob.

    Retries are disabled at the task level: ``run_extraction`` itself is
    idempotent on terminal states, but it transitions the job state machine
    eagerly. A blanket retry would see the second attempt skip with the
    job in ``classifying``/``extracting`` and fail to recover. Real retries
    land later, gated on a richer "is this safe to retry?" signal.
    """
    from .services import run_extraction

    logger.info("extract_invoice: starting job=%s", job_id)
    try:
        result = run_extraction(job_id)
    except Exception:
        logger.exception("extract_invoice: failed job=%s", job_id)
        raise
    logger.info(
        "extract_invoice: complete job=%s engine=%s confidence=%s text_len=%s",
        job_id,
        result.engine_name,
        result.confidence,
        result.text_length,
    )
    return {
        "job_id": str(result.job.id),
        "engine": result.engine_name,
        "confidence": result.confidence,
        "text_length": result.text_length,
    }
