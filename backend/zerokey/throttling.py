"""Project-wide DRF throttle classes + rate-limit response headers.

Slice 104 — implements ``API_DESIGN.md`` rate-limiting contract:

  * Anonymous requests: 60/min by IP.
  * Authenticated requests: 600/min by user (effectively a sustained
    10 req/sec burst). The cap is high enough that no UI ever feels
    it; the only callers it bites are runaway scripts.
  * Plan-tier overrides: ``Plan.features.api_rate_limit_per_minute``
    overrides the authenticated default when set on the active org's
    plan. Reading the plan adds one cache lookup per request, hot
    in Redis.
  * Response headers: ``X-RateLimit-Limit`` /
    ``X-RateLimit-Remaining`` / ``X-RateLimit-Reset`` are emitted on
    every response, and ``Retry-After`` on 429.

The throttle classes here use DRF's existing ``SimpleRateThrottle``
machinery so the cache backend is the project Redis cache (no extra
infrastructure).
"""

from __future__ import annotations

import time
from typing import Any

from rest_framework import throttling
from rest_framework.request import Request

# Default rates; overridable per-tier via plan features.
ANON_RATE_PER_MINUTE = 60
USER_RATE_PER_MINUTE = 600


class _RateLimitMixin:
    """Bookkeeping shared by both throttle classes.

    DRF's ``SimpleRateThrottle.allow_request`` already maintains a
    sliding window of timestamps in the cache. We piggyback on that
    to compute Remaining / Reset and stash them on the request so
    the response middleware can echo them as headers.
    """

    def allow_request(self, request: Request, view: Any) -> bool:  # type: ignore[override]
        # If get_cache_key returns None, SimpleRateThrottle.allow_request
        # short-circuits to True without populating ``history`` — meaning
        # this throttle didn't apply to this request. Skip header
        # bookkeeping in that case so the OTHER applicable throttle's
        # values reach the response.
        cache_key = self.get_cache_key(request, view)  # type: ignore[attr-defined]
        if cache_key is None:
            return True
        allowed = super().allow_request(request, view)  # type: ignore[misc]
        history: list[float] = getattr(self, "history", []) or []
        limit: int = getattr(self, "num_requests", 0)
        duration: int = getattr(self, "duration", 60)
        now = self.timer() if hasattr(self, "timer") else time.time()
        remaining = max(0, limit - len(history)) if allowed else 0
        reset_at = int(history[-1] + duration) if history else int(now + duration)
        # DRF wraps the Django HttpRequest in a rest_framework.Request;
        # the response middleware sees the wrapped HttpRequest, so we
        # set the attr there.
        info = {"limit": limit, "remaining": remaining, "reset": reset_at}
        target = getattr(request, "_request", request)
        target._zk_ratelimit = info  # type: ignore[attr-defined]
        return allowed


class AnonThrottle(_RateLimitMixin, throttling.SimpleRateThrottle):
    """IP-based rate limit for unauthenticated requests."""

    scope = "anon"
    rate = f"{ANON_RATE_PER_MINUTE}/min"

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        if request.user and request.user.is_authenticated:
            return None  # leave authenticated requests to UserThrottle
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class UserThrottle(_RateLimitMixin, throttling.SimpleRateThrottle):
    """Per-user rate limit. Falls through to plan tier override."""

    scope = "user"
    rate = f"{USER_RATE_PER_MINUTE}/min"

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        if not (request.user and request.user.is_authenticated):
            return None
        return self.cache_format % {
            "scope": self.scope,
            "ident": str(request.user.pk),
        }

    def allow_request(self, request: Request, view: Any) -> bool:  # type: ignore[override]
        # Plan-tier override: reads cached plan features for the
        # active org. Falls through to USER_RATE_PER_MINUTE if no
        # override or any lookup hiccups.
        override = _resolved_per_minute(request)
        if override and override != USER_RATE_PER_MINUTE:
            self.rate = f"{override}/min"
            self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request, view)


def _resolved_per_minute(request: Request) -> int | None:
    """Look up the active org's plan-tier rate override.

    Best-effort: any error returns None and the caller falls through
    to the default user rate. We never want a billing-lookup failure
    to hard-fail the request.
    """
    if not (request.user and request.user.is_authenticated):
        return None
    organization_id = None
    try:
        organization_id = request.session.get("organization_id")  # type: ignore[union-attr]
    except Exception:
        return None
    if not organization_id:
        return None
    try:
        from apps.billing.services import resolved_feature_flags  # noqa: PLC0415

        flags = resolved_feature_flags(organization_id=organization_id)
        # Feature flag can carry a numeric override under a known
        # slug; fall back when absent. Plan-tier rates as numeric
        # features land properly in Slice 107 — for now any present
        # override wins.
        rate = flags.get("api.rate_limit_per_minute") if isinstance(flags, dict) else None
        if isinstance(rate, int) and rate > 0:
            return rate
    except Exception:
        return None
    return None


class RateLimitHeaderMiddleware:
    """Echo ``X-RateLimit-*`` headers from the request bookkeeping."""

    def __init__(self, get_response: Any) -> None:
        self.get_response = get_response

    def __call__(self, request: Any) -> Any:
        response = self.get_response(request)
        info = getattr(request, "_zk_ratelimit", None)
        if info:
            response["X-RateLimit-Limit"] = str(info["limit"])
            response["X-RateLimit-Remaining"] = str(info["remaining"])
            response["X-RateLimit-Reset"] = str(info["reset"])
        return response
