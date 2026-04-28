"""Celery tasks for the administration context.

Today: just the LHDN reference catalog refresh. Scheduled via Celery
beat (configured in zerokey.celery) on a monthly cadence per
LHDN_INTEGRATION.md "reference data caching".
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="administration.refresh_reference_catalogs",
    queue="default",
    max_retries=0,
    acks_late=False,
)
def refresh_reference_catalogs() -> dict[str, int]:
    """Refresh MSIC / classification / UOM / tax / country catalogs from LHDN.

    Today this is a stub that stamps ``last_refreshed_at`` on every
    active row — the LHDN integration credentials in the ``lhdn``
    SystemSetting (Slice 10) aren't wired to a real API client yet.
    The shape and scheduling are here so wiring the client later is a
    one-place change.
    """
    from apps.administration.services import refresh_reference_catalogs as _refresh

    counts = _refresh()
    logger.info("administration.refresh_reference_catalogs: %s", counts)
    return counts
