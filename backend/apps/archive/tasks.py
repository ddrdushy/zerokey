"""Archive celery tasks (Slice 101).

Today: retention sweep that flips ``deletion_pending=True`` on rows
past their ``retain_until`` date. The actual destructive purge stays
out of this slice — it requires admin sign-off + a separate audited
gesture per COMPLIANCE.md.
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="archive.sweep_expired_archives", queue="low", acks_late=True)
def sweep_expired_archives_task() -> dict[str, int]:
    """Daily-ish sweep — flag expired ArchivedDocuments for purge."""
    from .services import sweep_expired_archives

    counts = sweep_expired_archives()
    if counts.get("flagged"):
        logger.info("archive.retention.sweep", extra={"counts": counts})
    return counts
