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
