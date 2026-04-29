"""Celery tasks for the enrichment context."""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="enrichment.verify_master_tin",
    queue="default",
    acks_late=True,
)
def verify_master_tin(master_id: str) -> dict[str, object]:
    """Background TIN-verify a CustomerMaster row.

    Calls into ``apps.enrichment.tin_verification.verify_master_tin``.
    Returns a small dict for log enrichment; persisted state on the
    master row is authoritative.
    """
    from . import tin_verification

    try:
        result = tin_verification.verify_master_tin(master_id)
    except tin_verification.TinVerificationError as exc:
        logger.warning(
            "enrichment.verify_master_tin.error",
            extra={"master_id": master_id, "error": str(exc)},
        )
        return {"master_id": master_id, "state": "error", "reason": str(exc)}
    return {"master_id": master_id, **result}
