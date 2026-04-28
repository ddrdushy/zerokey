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
