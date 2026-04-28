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
