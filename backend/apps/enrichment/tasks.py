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


@shared_task(
    name="enrichment.lookup_master_tin",
    queue="default",
    acks_late=True,
)
def lookup_master_tin(master_id: str) -> dict[str, object]:
    """Slice 116 — background LHDN TIN lookup for a master we know only by BRN.

    Companion to ``verify_master_tin``: that one confirms a known
    TIN, this one derives the TIN from a known BRN+name. Cached on
    the master row so subsequent invoices for the same buyer don't
    re-ping LHDN's rate-limited endpoint.
    """
    from . import tin_lookup

    try:
        result = tin_lookup.lookup_tin_from_brn(master_id)
    except tin_lookup.TinLookupError as exc:
        logger.warning(
            "enrichment.lookup_master_tin.error",
            extra={"master_id": master_id, "error": str(exc)},
        )
        return {"master_id": master_id, "state": "error", "reason": str(exc)}
    return {"master_id": master_id, **result}
