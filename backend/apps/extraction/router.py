"""Routing — pick the engine for a given (capability, mime_type) pair.

Phase 2 routing logic is intentionally simple: walk active rules ordered by
priority, return the first whose mime allowlist matches. Per-customer
overrides and full expression evaluation land later.

The router only chooses among engines whose ``status == active``. A degraded
or archived engine is invisible to routing even if a rule references it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Engine, EngineRoutingRule


@dataclass(frozen=True)
class RoutingDecision:
    """Picked engine + the fallback chain to try on failure."""

    engine: Engine
    fallbacks: list[Engine]
    matched_rule_id: str | None


class NoRouteFound(Exception):
    """Raised when no active rule + active engine matches the input."""


def pick_engine(*, capability: str, mime_type: str) -> RoutingDecision:
    return _pick_engine(capability=capability, mime_type=mime_type, exclude_engine_id=None)


def pick_fallback_engine(
    *, capability: str, mime_type: str, exclude_engine_id: str
) -> RoutingDecision:
    """Return the next-priority active rule, skipping the engine that already ran.

    Used by the escalation pipeline (Slice 32) when a primary text-extract
    returns low confidence and we want to try the next-best engine before
    paying for vision. The existing ``pick_engine`` always returns the
    lowest-priority match; this variant returns the second-or-later match
    that doesn't reference the engine we're trying to escape from.

    ``NoRouteFound`` if no fallback rule exists; the caller decides whether
    that's an audit-and-skip (escalation chain has no more options) or a
    hard error (the primary path itself was a fallback that shouldn't have
    run).
    """
    return _pick_engine(
        capability=capability,
        mime_type=mime_type,
        exclude_engine_id=str(exclude_engine_id),
    )


def _pick_engine(
    *, capability: str, mime_type: str, exclude_engine_id: str | None
) -> RoutingDecision:
    rules = (
        EngineRoutingRule.objects.filter(
            capability=capability,
            is_active=True,
            engine__status=Engine.Status.ACTIVE,
        )
        .select_related("engine", "fallback_engine")
        .order_by("priority", "created_at")
    )

    for rule in rules:
        if exclude_engine_id and str(rule.engine_id) == exclude_engine_id:
            continue
        if not _mime_matches(rule.match_mime_types, mime_type):
            continue
        fallbacks: list[Engine] = []
        if rule.fallback_engine and rule.fallback_engine.status == Engine.Status.ACTIVE:
            fallbacks.append(rule.fallback_engine)
        return RoutingDecision(
            engine=rule.engine,
            fallbacks=fallbacks,
            matched_rule_id=str(rule.id),
        )

    raise NoRouteFound(
        f"No active routing rule matches capability={capability!r} mime={mime_type!r}"
    )


def _mime_matches(pattern: str, mime_type: str) -> bool:
    """Comma-separated allowlist; ``*`` is wildcard. Whitespace tolerated."""
    items = [token.strip() for token in pattern.split(",") if token.strip()]
    if not items or "*" in items:
        return True
    return mime_type in items
