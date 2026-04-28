"""Celery tasks for the audit context.

Currently one task: a scheduled chain integrity check. The chain is
*always* verifiable on demand via ``POST /api/v1/audit/verify/`` — the
scheduled task gives the customer the stronger statement "we last
verified the chain X minutes ago, you don't have to" without anyone
having to click anything.

Per ARCHITECTURE.md task discipline: the verification itself runs
under super-admin elevation (the chain is global), records exactly one
``ChainVerificationRun`` row per tick, and emits one system-level
``audit.chain_verified`` event. Failures and tamper-detections are
recorded as runs (status ``error`` / ``tampered``) rather than
swallowed — silent failure on a trust surface is worse than an
explicit "we tried at T, here's what happened".
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="audit.verify_audit_chain",
    queue="low",
    max_retries=0,
    acks_late=False,
)
def verify_audit_chain() -> dict[str, str | int]:
    """Run one scheduled chain verification.

    No retries: a transient DB failure is recorded on the run as
    ``status=error`` and surfaces to the audit page; the next beat
    tick (default every six hours) re-attempts. A retry storm on a
    cryptographic check buys nothing.
    """
    from .services import run_scheduled_chain_verification

    logger.info("verify_audit_chain: starting")
    run = run_scheduled_chain_verification()
    logger.info(
        "verify_audit_chain: complete status=%s events=%s",
        run.status,
        run.events_verified,
    )
    return {
        "run_id": str(run.id),
        "status": run.status,
        "events_verified": run.events_verified,
    }
