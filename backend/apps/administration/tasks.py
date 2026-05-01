"""Celery tasks for the administration context.

Today: the LHDN reference catalog refresh, scheduled via Celery
beat (configured in ``zerokey.settings.base``) on a monthly cadence
per LHDN_INTEGRATION.md "reference data caching".
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="administration.refresh_reference_catalogs",
    queue="low",
    max_retries=0,
    acks_late=False,
)
def refresh_reference_catalogs() -> dict[str, dict[str, int]]:
    """Pull LHDN catalogs + reconcile local rows (Slice 71).

    Calls into ``apps.administration.catalog_refresh.refresh_all_catalogs``,
    which fetches each catalog (MSIC / classification / UOM /
    tax-type / country) from the configured remote source, upserts
    new / changed codes, and marks dropped codes ``is_active=False``.

    No-ops with an audit reason when ``LHDN_CATALOG_BASE_URL`` is
    unset — operator hasn't configured the remote yet, the seed
    migration's catalog stays authoritative.
    """
    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event

    from . import catalog_refresh

    try:
        fetchers = catalog_refresh.default_fetchers()
    except catalog_refresh.CatalogNotConfigured as exc:
        record_event(
            action_type="administration.catalog_refresh.skipped",
            actor_type=AuditEvent.ActorType.SERVICE,
            actor_id="administration.catalog_refresh",
            organization_id=None,
            affected_entity_type="ReferenceCatalog",
            affected_entity_id="*",
            payload={"reason": str(exc)},
        )
        logger.info("administration.refresh_reference_catalogs.skipped %s", exc)
        return {}

    summary = catalog_refresh.refresh_all_catalogs(fetchers=fetchers)
    out = {
        label: {
            "added": s.added,
            "updated": s.updated,
            "deactivated": s.deactivated,
            "reactivated": s.reactivated,
            "unchanged": s.unchanged,
        }
        for label, s in summary.items()
    }
    logger.info("administration.refresh_reference_catalogs: %s", out)
    return out


@shared_task(
    name="administration.refresh_bnm_rates",
    queue="low",
    max_retries=0,
    acks_late=False,
)
def refresh_bnm_rates() -> dict[str, object]:
    """Pull daily BNM exchange rates + cache them (Slice 96).

    Runs daily on celery beat. Soft-fails on network / parse errors —
    we log and return so a flaky BNM endpoint doesn't poison the
    beat tick. The previous-day cache stays authoritative until the
    next successful fetch.
    """
    from . import bnm_rates

    summary = bnm_rates.fetch_and_cache()
    payload = {
        "fetched": summary.fetched,
        "upserted": summary.upserted,
        "unchanged": summary.unchanged,
        "failed_reason": summary.failed_reason,
    }
    logger.info("administration.refresh_bnm_rates: %s", payload)
    return payload
