"""TIN validation cache layer (Slice 59A).

LHDN's ``/api/v1.0/taxpayer/validate/{tin}`` is rate-limited at 60
RPM. The integration spec recommends 24-hour caching: validated TINs
don't change minute to minute, and re-querying every time we touch
a customer's invoice would burn through the rate budget on a busy
day.

Cache backend: Django's default cache. In dev that's locmem; in
production that's Redis (see settings.base.CACHES). Both honor the
TTL we set here.

Cache shape:
  - Key:   ``lhdn:tin:{tin}:{environment}``
  - Value: ``"valid"`` | ``"invalid"`` (string sentinel — easier to
    distinguish from a cache miss than ``True``/``False``).

Why include the environment in the key: a TIN that's recognized in
LHDN's sandbox might not be recognized in production (LHDN seeds
the sandbox with synthetic taxpayer data). The cache should not
leak across.

Why cache negatives too (``"invalid"``): customers will retry-paste
the same wrong TIN multiple times when correcting an invoice. Caching
the negative for 24 hours is right — if a TIN flips from invalid to
valid, that's a real-world event the customer notices + fixes
manually anyway.
"""

from __future__ import annotations

import logging
import uuid

from django.core.cache import cache

from . import lhdn_client

logger = logging.getLogger(__name__)

# Per spec §4.5: 24 hours.
TIN_CACHE_TTL_SECONDS = 24 * 60 * 60


def is_tin_valid(*, organization_id: uuid.UUID | str, tin: str) -> bool:
    """Cached LHDN TIN validation.

    Returns:
      - ``True``  — LHDN accepts the TIN.
      - ``False`` — LHDN rejects it (or call failed; conservative
        default — caller treats this as "not validated yet" rather
        than blocking submission).
    """
    tin = (tin or "").strip()
    if not tin:
        return False

    try:
        creds = lhdn_client.credentials_for_org(organization_id=organization_id)
    except lhdn_client.LHDNError:
        # Org hasn't configured LHDN yet — we can't validate, so
        # don't block. Submission-time validation will surface the
        # gap if it's still wrong.
        return False

    cache_key = f"lhdn:tin:{tin}:{creds.environment}"
    cached = cache.get(cache_key)
    if cached == "valid":
        return True
    if cached == "invalid":
        return False

    # Cache miss — call LHDN.
    try:
        valid = lhdn_client.validate_tin(creds=creds, tin=tin)
    except lhdn_client.LHDNError as exc:
        # Connectivity / auth / 5xx failure. Don't cache — retry
        # next call. Log so operators see chronic failures.
        logger.warning(
            "lhdn.tin_validate.failed",
            extra={
                "organization_id": str(organization_id),
                "environment": creds.environment,
                "error_class": type(exc).__name__,
            },
        )
        return False

    cache.set(
        cache_key,
        "valid" if valid else "invalid",
        TIN_CACHE_TTL_SECONDS,
    )
    return valid


def invalidate_cached_tin(*, tin: str, environment: str | None = None) -> None:
    """Drop one TIN from the cache.

    Used when an operator manually corrects a TIN — the next
    submission attempt should re-validate rather than honor a stale
    "invalid" hit. ``environment`` is optional; if omitted, both
    sandbox + production keys are dropped.
    """
    tin = (tin or "").strip()
    if not tin:
        return
    envs = [environment] if environment else ["sandbox", "production"]
    for env in envs:
        cache.delete(f"lhdn:tin:{tin}:{env}")
