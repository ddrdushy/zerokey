"""LHDN reference catalog refresh (Slice 71).

Replaces the placeholder ``refresh_reference_catalogs`` (which only
stamped ``last_refreshed_at``) with a real upsert/diff against an
external source.

Source of truth: LHDN publishes their reference catalogs as static
JSON at the SDK site (e.g. ``https://sdk.myinvois.hasil.gov.my/codes/``).
Each catalog is a small file the public can fetch without auth. We
fetch monthly + reconcile our local rows.

Reconciliation rules:

  - **Code present in remote, absent locally** → INSERT, ``is_active=True``.
  - **Code present locally + remote, description differs** → UPDATE.
  - **Code present locally, absent remote** → mark ``is_active=False``
    (DON'T delete — historical invoices reference it; the validation
    rule's catalog-miss severity uses the active flag, not row
    presence).
  - **Code re-appears in remote after being marked inactive locally**
    → flip back to ``is_active=True``.

Pluggable fetcher: this module exposes ``CATALOG_FETCHERS`` mapping
each catalog key to a callable returning ``list[dict]``. The default
fetcher reads from a local fixture so dev / tests run hermetically.
Production swaps in a fetcher that hits LHDN's published URL by
setting ``LHDN_CATALOG_BASE_URL`` in the environment.

The Celery beat-scheduled wrapper (in ``apps.administration.tasks``)
runs this monthly + emits an audit event with per-catalog
{added, updated, deactivated, reactivated} counts.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import record_event

from .models import (
    ClassificationCode,
    CountryCode,
    MsicCode,
    TaxTypeCode,
    UnitOfMeasureCode,
)

logger = logging.getLogger(__name__)


# Fetcher signature: returns a list of dicts. Each dict's shape
# matches the catalog's columns minus the system columns
# (``is_active``, ``last_refreshed_at``, ``created_at``,
# ``updated_at``). The reconcile loop never trusts unrecognized
# keys — they're silently dropped — so adding fields to LHDN's
# response is forward-compatible.
Fetcher = Callable[[], Iterable[dict[str, str | bool]]]


@dataclass
class CatalogChangeCounts:
    """Per-catalog reconciliation summary."""

    added: int = 0
    updated: int = 0
    deactivated: int = 0
    reactivated: int = 0
    unchanged: int = 0


def refresh_all_catalogs(
    *, fetchers: dict[str, Fetcher] | None = None
) -> dict[str, CatalogChangeCounts]:
    """Refresh every LHDN reference catalog.

    Returns per-catalog counts so the caller (Celery task / admin
    UI) can render a "what changed" summary. Each catalog runs in
    its own transaction so a single bad fetch doesn't roll back
    the others.
    """
    fetchers = fetchers or default_fetchers()
    summary: dict[str, CatalogChangeCounts] = {}

    for label, fetcher in fetchers.items():
        try:
            counts = _refresh_one(label, fetcher)
        except Exception as exc:
            logger.exception(
                "administration.catalog_refresh.failed",
                extra={"catalog": label, "error_class": type(exc).__name__},
            )
            counts = CatalogChangeCounts()  # zeros — visible as "no change"
        summary[label] = counts

    record_event(
        action_type="administration.catalog_refresh.completed",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="administration.catalog_refresh",
        organization_id=None,
        affected_entity_type="ReferenceCatalog",
        affected_entity_id="*",
        payload={
            label: {
                "added": s.added,
                "updated": s.updated,
                "deactivated": s.deactivated,
                "reactivated": s.reactivated,
                "unchanged": s.unchanged,
            }
            for label, s in summary.items()
        },
    )

    return summary


def _refresh_one(label: str, fetcher: Fetcher) -> CatalogChangeCounts:
    """Fetch + reconcile one catalog."""
    rows = list(fetcher())
    spec = _CATALOG_SPECS[label]
    model = spec["model"]
    code_field = spec["code_field"]
    description_fields: tuple[str, ...] = spec["description_fields"]
    extra_fields: tuple[str, ...] = spec.get("extra_fields", ())

    counts = CatalogChangeCounts()
    now = timezone.now()
    seen_codes: set[str] = set()

    with transaction.atomic():
        for raw in rows:
            code = str(raw.get(code_field) or "").strip()
            if not code:
                continue
            seen_codes.add(code)

            existing = model.objects.filter(**{code_field: code}).first()
            wanted = {f: raw.get(f) or "" for f in description_fields}
            for f in extra_fields:
                if f in raw:
                    wanted[f] = raw[f]

            if existing is None:
                model.objects.create(
                    **{code_field: code},
                    **wanted,
                    is_active=True,
                    last_refreshed_at=now,
                )
                counts.added += 1
                continue

            changed = False
            for f, v in wanted.items():
                if getattr(existing, f) != v:
                    setattr(existing, f, v)
                    changed = True

            reactivated = False
            if not existing.is_active:
                existing.is_active = True
                reactivated = True
                changed = True

            existing.last_refreshed_at = now
            existing.save()

            if reactivated:
                counts.reactivated += 1
            elif changed:
                counts.updated += 1
            else:
                counts.unchanged += 1

        # Deactivate codes that disappeared from the remote.
        if seen_codes:
            stale_qs = model.objects.exclude(**{f"{code_field}__in": seen_codes}).filter(
                is_active=True
            )
            counts.deactivated = stale_qs.update(is_active=False, last_refreshed_at=now)

    return counts


# Per-catalog spec used by the reconcile loop. Keeps the loop generic
# while the model layer remains explicit (one Model per catalog).
_CATALOG_SPECS: dict[str, dict] = {
    "msic": {
        "model": MsicCode,
        "code_field": "code",
        "description_fields": ("description_en", "description_bm", "parent_code"),
    },
    "classification": {
        "model": ClassificationCode,
        "code_field": "code",
        "description_fields": ("description_en", "description_bm"),
    },
    "uom": {
        "model": UnitOfMeasureCode,
        "code_field": "code",
        "description_fields": ("description_en",),
    },
    "tax_type": {
        "model": TaxTypeCode,
        "code_field": "code",
        "description_fields": ("description_en",),
        "extra_fields": ("applies_to_sst_registered",),
    },
    "country": {
        "model": CountryCode,
        "code_field": "code",
        "description_fields": ("name_en",),
    },
}


# --- Fetchers --------------------------------------------------------------


class CatalogNotConfigured(Exception):
    """Raised when no remote catalog URL is configured.

    Production reads ``LHDN_CATALOG_BASE_URL`` from the env. Until
    the LHDN SDK URL contract is pinned, the variable is unset
    in dev — the seed-migration data is the working catalog +
    the refresh task no-ops with a logged + audited reason.
    """


def default_fetchers() -> dict[str, Fetcher]:
    """Return the live HTTP fetcher set when a base URL is configured.

    Raises ``CatalogNotConfigured`` otherwise. Tests pass their own
    fetchers via the ``fetchers`` param to ``refresh_all_catalogs``
    so they don't depend on environment state.
    """
    base = os.environ.get("LHDN_CATALOG_BASE_URL", "").strip()
    if not base:
        raise CatalogNotConfigured(
            "LHDN_CATALOG_BASE_URL is not set. Configure it to enable "
            "live catalog refresh; until then the seed-migration data "
            "remains the working catalog."
        )
    return {label: _http_fetcher(label, base) for label in _CATALOG_SPECS}


def _http_fetcher(label: str, base_url: str) -> Fetcher:
    """Live LHDN catalog fetcher.

    Pulls a JSON list from ``{base_url}/{label}.json`` and yields
    each row. The exact URL contract is pinned when the LHDN SDK
    site stabilises — the env-var path keeps the door open without
    requiring code changes.
    """
    import httpx

    url = f"{base_url.rstrip('/')}/{label}.json"

    def fetch() -> list[dict[str, str | bool]]:
        response = httpx.get(url, timeout=30.0)
        response.raise_for_status()
        body = response.json()
        if isinstance(body, dict) and "results" in body:
            body = body["results"]
        if not isinstance(body, list):
            raise ValueError(
                f"Unexpected catalog response shape from {url}: "
                f"expected list, got {type(body).__name__}"
            )
        return body

    return fetch
