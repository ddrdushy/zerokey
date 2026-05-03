"""Billing celery tasks (Slice 100).

Today this is just the lifecycle sweep. Future: usage-overage
billing-cycle close-out, dunning emails, automated trial-end nudges.
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="billing.enforce_subscription_lifecycle", queue="low", acks_late=True)
def enforce_subscription_lifecycle_task() -> dict[str, int]:
    """Daily-ish sweep — runs the lifecycle state machine.

    Idempotent: an org already in the target state is skipped. The
    audit log is the source of truth for *when* each transition
    happened.
    """
    from .services import enforce_subscription_lifecycle

    counts = enforce_subscription_lifecycle()
    if any(counts.values()):
        logger.info("billing.lifecycle.sweep", extra={"counts": counts})
    return counts
