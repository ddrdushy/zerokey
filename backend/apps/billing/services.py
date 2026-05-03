"""Billing services.

Read-mostly today — the customer Settings → Billing tab uses these to
render plan + subscription state. Writes (subscription create / cancel
/ upgrade) come with the Stripe wiring slice; today the data shape is
in place but the actual payment flow isn't.

Cross-context callers go through this module, never import the
models directly.
"""

from __future__ import annotations

import uuid
from typing import Any

from django.utils import timezone

from .models import Plan, Subscription, UsageEvent


def list_public_plans() -> list[dict[str, Any]]:
    """Plans visible on the public pricing page."""
    qs = Plan.objects.filter(is_active=True, is_public=True).order_by("monthly_price_cents", "tier")
    return [_plan_dict(p) for p in qs]


def get_plan(slug: str, version: int | None = None) -> Plan | None:
    qs = Plan.objects.filter(slug=slug, is_active=True)
    if version is not None:
        return qs.filter(version=version).first()
    return qs.order_by("-version").first()


def _plan_dict(plan: Plan) -> dict[str, Any]:
    return {
        "id": str(plan.id),
        "slug": plan.slug,
        "version": plan.version,
        "name": plan.name,
        "description": plan.description,
        "tier": plan.tier,
        "monthly_price_cents": int(plan.monthly_price_cents),
        "annual_price_cents": int(plan.annual_price_cents),
        "billing_currency": plan.billing_currency,
        "included_invoices_per_month": int(plan.included_invoices_per_month),
        "per_overage_cents": int(plan.per_overage_cents),
        "included_users": int(plan.included_users),
        "included_api_keys": int(plan.included_api_keys),
        "features": plan.features or {},
    }


def get_active_subscription(*, organization_id: uuid.UUID | str) -> dict[str, Any] | None:
    """Return the active (or trialing) subscription for an org, or None."""
    sub = (
        Subscription.objects.filter(
            organization_id=organization_id,
            status__in=[
                Subscription.Status.ACTIVE,
                Subscription.Status.TRIALING,
                Subscription.Status.PAST_DUE,
            ],
        )
        .select_related("plan")
        .order_by("-created_at")
        .first()
    )
    return _subscription_dict(sub) if sub is not None else None


def _subscription_dict(sub: Subscription) -> dict[str, Any]:
    return {
        "id": str(sub.id),
        "status": sub.status,
        "billing_cycle": sub.billing_cycle,
        "plan": _plan_dict(sub.plan),
        "current_period_start": sub.current_period_start.isoformat()
        if sub.current_period_start
        else None,
        "current_period_end": sub.current_period_end.isoformat()
        if sub.current_period_end
        else None,
        "trial_started_at": sub.trial_started_at.isoformat() if sub.trial_started_at else None,
        "trial_ends_at": sub.trial_ends_at.isoformat() if sub.trial_ends_at else None,
        "cancel_at_period_end": bool(sub.cancel_at_period_end),
        "cancelled_at": sub.cancelled_at.isoformat() if sub.cancelled_at else None,
        "stripe_customer_id": sub.stripe_customer_id,
        "stripe_subscription_id": sub.stripe_subscription_id,
    }


def current_period_usage(
    *,
    organization_id: uuid.UUID | str,
    event_type: str = UsageEvent.EventType.INVOICE_PROCESSED,
) -> dict[str, Any]:
    """Sum of ``quantity`` for events in the active subscription's
    current period. Returns ``{count, limit, overage_count}``.

    No active subscription → returns counts since the org was created
    against a "no limit" reference so the UI can still show usage.
    """
    sub = (
        Subscription.objects.filter(
            organization_id=organization_id,
            status__in=[
                Subscription.Status.ACTIVE,
                Subscription.Status.TRIALING,
                Subscription.Status.PAST_DUE,
            ],
        )
        .select_related("plan")
        .order_by("-created_at")
        .first()
    )
    if sub is not None and sub.current_period_start is not None:
        period_start = sub.current_period_start
        period_end = sub.current_period_end
        limit = int(sub.plan.included_invoices_per_month or 0)
    else:
        from datetime import timedelta

        period_end = timezone.now()
        period_start = period_end - timedelta(days=30)
        limit = 0

    qs = UsageEvent.objects.filter(
        organization_id=organization_id,
        event_type=event_type,
        occurred_at__gte=period_start,
    )
    if period_end is not None:
        qs = qs.filter(occurred_at__lte=period_end)

    count = sum(qs.values_list("quantity", flat=True))
    overage = max(0, count - limit) if limit > 0 else 0
    return {
        "event_type": event_type,
        "period_start": period_start.isoformat() if period_start else None,
        "period_end": period_end.isoformat() if period_end else None,
        "count": int(count),
        "limit": int(limit),
        "overage_count": int(overage),
    }


def record_usage_event(
    *,
    organization_id: uuid.UUID | str,
    event_type: str,
    quantity: int = 1,
    related_entity_type: str = "",
    related_entity_id: str = "",
) -> UsageEvent:
    """Append a usage event. Snapshots active subscription + plan."""
    sub = (
        Subscription.objects.filter(
            organization_id=organization_id,
            status__in=[
                Subscription.Status.ACTIVE,
                Subscription.Status.TRIALING,
                Subscription.Status.PAST_DUE,
            ],
        )
        .select_related("plan")
        .order_by("-created_at")
        .first()
    )
    return UsageEvent.objects.create(
        organization_id=organization_id,
        event_type=event_type,
        quantity=int(quantity),
        related_entity_type=related_entity_type[:64],
        related_entity_id=related_entity_id[:128],
        subscription_id=sub.id if sub else None,
        plan_slug=sub.plan.slug if sub else "",
        plan_version=sub.plan.version if sub else 0,
    )


def is_feature_enabled(
    *,
    organization_id: uuid.UUID | str,
    flag_slug: str,
) -> bool:
    """Resolve a feature flag for an org. Order: org override → plan → default.

    Per PRODUCT_REQUIREMENTS.md Domain 11: flags can be set at the
    global, plan, or customer level — the customer override wins, then
    the plan default, then the global default. An undeclared slug
    returns False (fail-closed).

    Cheap: one indexed lookup against the override table, one
    join-less read of the active subscription. Caching is intentionally
    not added here — feature gates are read on individual requests in
    contexts that already do per-request work; a hot-path gate that
    needs caching can wrap this with ``functools.cache``-per-request.
    """
    from .models import FeatureFlag, FeatureFlagOverride

    flag = FeatureFlag.objects.filter(slug=flag_slug).first()
    if flag is None:
        return False  # undeclared flag → fail closed

    # 1. Per-org override wins. Auto-expired overrides are ignored.
    now = timezone.now()
    override = (
        FeatureFlagOverride.objects.filter(
            organization_id=organization_id,
            flag_id=flag.id,
        )
        .first()
    )
    if override is not None:
        if override.expires_at is None or override.expires_at > now:
            return bool(override.enabled)

    # 2. Plan-level default from Plan.features JSON. The active
    #    subscription's plan is the source of truth.
    sub = (
        Subscription.objects.filter(
            organization_id=organization_id,
            status__in=[
                Subscription.Status.ACTIVE,
                Subscription.Status.TRIALING,
                Subscription.Status.PAST_DUE,
            ],
        )
        .select_related("plan")
        .order_by("-created_at")
        .first()
    )
    if sub is not None and isinstance(sub.plan.features, dict):
        if flag_slug in sub.plan.features:
            return bool(sub.plan.features[flag_slug])

    # 3. Global default declared on the flag row.
    return bool(flag.default_enabled)


def resolved_feature_flags(
    *,
    organization_id: uuid.UUID | str,
) -> dict[str, bool]:
    """Return ``{slug: enabled}`` for every declared flag, resolved for an org.

    The customer-facing ``/identity/feature-flags/`` endpoint serves
    this; the frontend uses the map to hide/show features without
    asking per-flag.
    """
    from .models import FeatureFlag

    return {
        flag.slug: is_feature_enabled(
            organization_id=organization_id, flag_slug=flag.slug
        )
        for flag in FeatureFlag.objects.all()
    }


def bootstrap_trial_subscription(*, organization_id: uuid.UUID | str) -> Subscription | None:
    """Create a 14-day trial subscription on the trial plan.

    Idempotent — returns the existing subscription if one already
    exists. Called by registration to put new tenants on the trial
    automatically; can be called manually by the admin too.
    """
    from datetime import timedelta

    existing = Subscription.objects.filter(organization_id=organization_id).first()
    if existing:
        return existing

    trial_plan = get_plan("trial")
    if trial_plan is None:
        return None

    now = timezone.now()
    trial_end = now + timedelta(days=14)
    return Subscription.objects.create(
        organization_id=organization_id,
        plan=trial_plan,
        status=Subscription.Status.TRIALING,
        billing_cycle=Subscription.BillingCycle.MONTHLY,
        current_period_start=now,
        current_period_end=trial_end,
        trial_started_at=now,
        trial_ends_at=trial_end,
    )
