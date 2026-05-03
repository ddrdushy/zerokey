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


# --- Slice 100: customer billing self-service -----------------------------------


class SubscriptionCancelError(Exception):
    """Raised on cancellation validation failure."""


def cancel_subscription(
    *,
    organization_id: uuid.UUID | str,
    actor_user_id: uuid.UUID | str,
    mode: str,
    reason: str = "",
) -> dict[str, Any]:
    """Cancel the org's active subscription.

    ``mode``:
      - ``"immediate"`` — sets status=CANCELLED, cancelled_at=now,
        flips Organization.subscription_state to CANCELLED. The
        prorated-refund handling lives in Stripe webhook land.
      - ``"period_end"`` — sets cancel_at_period_end=True, leaves
        status ACTIVE/TRIALING; the daily lifecycle sweep flips it
        to CANCELLED on the period boundary.

    Stripe sync is best-effort: if a `stripe_subscription_id` is
    present we forward the cancellation to Stripe; if not, we
    short-circuit (still cancels locally).

    Audited as ``billing.subscription_cancelled``.
    """
    from django.utils import timezone as _tz

    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event
    from apps.identity.models import Organization

    if mode not in {"immediate", "period_end"}:
        raise SubscriptionCancelError("mode must be 'immediate' or 'period_end'.")

    sub = (
        Subscription.objects.filter(
            organization_id=organization_id,
            status__in=[
                Subscription.Status.ACTIVE,
                Subscription.Status.TRIALING,
                Subscription.Status.PAST_DUE,
            ],
        )
        .order_by("-created_at")
        .first()
    )
    if sub is None:
        raise SubscriptionCancelError("No active subscription to cancel.")

    # Push to Stripe if we know the remote id.
    if sub.stripe_subscription_id:
        from . import stripe_client

        try:
            stripe_client.cancel_stripe_subscription(
                subscription_id=sub.stripe_subscription_id,
                immediate=(mode == "immediate"),
            )
        except stripe_client.StripeError:
            # Don't fail the local cancellation if Stripe is down —
            # the webhook reconciler will catch up. Log + continue.
            import logging

            logging.getLogger(__name__).warning(
                "billing.cancel.stripe_failed",
                extra={"subscription_id": str(sub.id)},
            )

    if mode == "immediate":
        sub.status = Subscription.Status.CANCELLED
        sub.cancelled_at = _tz.now()
        sub.cancellation_reason = (reason or "")[:255]
        sub.cancel_at_period_end = False
        sub.save(
            update_fields=[
                "status",
                "cancelled_at",
                "cancellation_reason",
                "cancel_at_period_end",
                "updated_at",
            ]
        )
        Organization.objects.filter(id=organization_id).update(
            subscription_state=Organization.SubscriptionState.CANCELLED
        )
    else:
        sub.cancel_at_period_end = True
        sub.cancellation_reason = (reason or "")[:255]
        sub.save(
            update_fields=["cancel_at_period_end", "cancellation_reason", "updated_at"]
        )

    record_event(
        action_type="billing.subscription_cancelled",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(organization_id),
        affected_entity_type="Subscription",
        affected_entity_id=str(sub.id),
        payload={"mode": mode, "reason": reason[:255]},
    )

    return _subscription_dict(sub)


def reactivate_subscription(
    *,
    organization_id: uuid.UUID | str,
    actor_user_id: uuid.UUID | str,
) -> dict[str, Any]:
    """Undo a pending period-end cancellation.

    Only valid while the sub is still ACTIVE/TRIALING with
    cancel_at_period_end=True.
    """
    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event

    sub = (
        Subscription.objects.filter(
            organization_id=organization_id,
            cancel_at_period_end=True,
            status__in=[
                Subscription.Status.ACTIVE,
                Subscription.Status.TRIALING,
                Subscription.Status.PAST_DUE,
            ],
        )
        .order_by("-created_at")
        .first()
    )
    if sub is None:
        raise SubscriptionCancelError(
            "No subscription with a pending cancellation to reactivate."
        )

    sub.cancel_at_period_end = False
    sub.cancellation_reason = ""
    sub.save(update_fields=["cancel_at_period_end", "cancellation_reason", "updated_at"])

    if sub.stripe_subscription_id:
        from . import stripe_client

        try:
            stripe_client._post(
                creds=stripe_client.credentials(),
                path=f"/subscriptions/{sub.stripe_subscription_id}",
                data={"cancel_at_period_end": "false"},
            )
        except stripe_client.StripeError:
            import logging

            logging.getLogger(__name__).warning(
                "billing.reactivate.stripe_failed",
                extra={"subscription_id": str(sub.id)},
            )

    record_event(
        action_type="billing.subscription_reactivated",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(organization_id),
        affected_entity_type="Subscription",
        affected_entity_id=str(sub.id),
        payload={},
    )
    return _subscription_dict(sub)


def list_billing_invoices(
    *,
    organization_id: uuid.UUID | str,
) -> list[dict[str, Any]]:
    """Return Stripe-issued invoice history for the org's subscription.

    Slice 100 — surfaces ZeroKey's *own* subscription invoices to the
    customer (we issue our own e-invoices for the SaaS subscription;
    the meta-loop is intentional). Empty list if Stripe isn't
    configured or the customer hasn't been provisioned in Stripe yet.
    """
    sub = (
        Subscription.objects.filter(
            organization_id=organization_id,
        )
        .exclude(stripe_customer_id="")
        .order_by("-created_at")
        .first()
    )
    if sub is None or not sub.stripe_customer_id:
        return []

    from . import stripe_client

    try:
        envelope = stripe_client.list_invoices(customer_id=sub.stripe_customer_id)
    except stripe_client.StripeError:
        return []

    invoices = envelope.get("data") or []
    return [
        {
            "id": inv.get("id", ""),
            "number": inv.get("number") or "",
            "amount_paid_cents": int(inv.get("amount_paid") or 0),
            "currency": (inv.get("currency") or "myr").upper(),
            "status": inv.get("status") or "",
            "created": inv.get("created") or 0,
            "hosted_invoice_url": inv.get("hosted_invoice_url") or "",
            "invoice_pdf": inv.get("invoice_pdf") or "",
        }
        for inv in invoices
    ]


def create_billing_portal_url(
    *,
    organization_id: uuid.UUID | str,
    return_url: str,
) -> str:
    """Open a Stripe Customer Portal session and return the URL.

    The portal handles payment-method management, plan changes, and
    invoice downloads. Three Domain-10 P0 promises live in Stripe's
    UI; we link out rather than rebuild.
    """
    sub = (
        Subscription.objects.filter(organization_id=organization_id)
        .exclude(stripe_customer_id="")
        .order_by("-created_at")
        .first()
    )
    if sub is None or not sub.stripe_customer_id:
        raise SubscriptionCancelError(
            "Set up a payment method first — no Stripe customer attached yet."
        )
    from . import stripe_client

    session = stripe_client.create_billing_portal_session(
        customer_id=sub.stripe_customer_id, return_url=return_url
    )
    return str(session.get("url") or "")


# --- Trial-to-paid lifecycle (PRD Domain 10 — trial-to-paid conversion) -------

# Per PRD: trial expires → read-only for 14 days → suspended → 30
# more days → data purge eligible. We model the in-between state as
# Organization.SubscriptionState.PAST_DUE (read-only with banner)
# and SUSPENDED (no access). The actual purge runs from a different
# beat task and only flags rows for deletion; the destructive sweep
# stays as a follow-up.

POST_TRIAL_GRACE_DAYS = 14
SUSPENDED_BEFORE_PURGE_DAYS = 30


def enforce_subscription_lifecycle() -> dict[str, int]:
    """Daily sweep — transition orgs through trial → grace → suspended.

    Called by celery beat. Idempotent: an org already in the target
    state is left alone. Audit-logged so the chain shows when each
    state change happened and what triggered it.
    """
    from datetime import timedelta

    from django.utils import timezone as _tz

    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event
    from apps.identity.models import Organization
    from apps.identity.tenancy import super_admin_context

    counts = {"to_grace": 0, "to_suspended": 0, "to_purge_pending": 0}
    now = _tz.now()
    grace_deadline = now - timedelta(days=POST_TRIAL_GRACE_DAYS)
    suspend_deadline = now - timedelta(days=SUSPENDED_BEFORE_PURGE_DAYS)

    with super_admin_context(reason="billing.lifecycle.sweep"):
        # Trial expired AND no paid sub took over → into grace (past_due).
        expired_trials = Subscription.objects.filter(
            status=Subscription.Status.TRIALING,
            trial_ends_at__lte=now,
        )
        for sub in expired_trials:
            sub.status = Subscription.Status.PAST_DUE
            sub.save(update_fields=["status", "updated_at"])
            Organization.objects.filter(id=sub.organization_id).update(
                subscription_state=Organization.SubscriptionState.PAST_DUE,
                trial_state=Organization.TrialState.EXPIRED,
            )
            record_event(
                action_type="billing.trial_expired",
                actor_type=AuditEvent.ActorType.SERVICE,
                actor_id="billing.lifecycle",
                organization_id=str(sub.organization_id),
                affected_entity_type="Subscription",
                affected_entity_id=str(sub.id),
                payload={"grace_days": POST_TRIAL_GRACE_DAYS},
            )
            counts["to_grace"] += 1

        # Past-due (grace) for >14 days → suspended.
        past_due_orgs = Organization.objects.filter(
            subscription_state=Organization.SubscriptionState.PAST_DUE,
            updated_at__lte=grace_deadline,
        )
        for org in past_due_orgs:
            org.subscription_state = Organization.SubscriptionState.SUSPENDED
            org.save(update_fields=["subscription_state", "updated_at"])
            record_event(
                action_type="billing.subscription_suspended",
                actor_type=AuditEvent.ActorType.SERVICE,
                actor_id="billing.lifecycle",
                organization_id=str(org.id),
                affected_entity_type="Organization",
                affected_entity_id=str(org.id),
                payload={"after_grace_days": POST_TRIAL_GRACE_DAYS},
            )
            counts["to_suspended"] += 1

        # Suspended for >30 days → flag for purge (does NOT delete; a
        # separate destructive sweep + admin sign-off does that).
        suspended_orgs = Organization.objects.filter(
            subscription_state=Organization.SubscriptionState.SUSPENDED,
            updated_at__lte=suspend_deadline,
        )
        for org in suspended_orgs:
            record_event(
                action_type="billing.purge_eligible",
                actor_type=AuditEvent.ActorType.SERVICE,
                actor_id="billing.lifecycle",
                organization_id=str(org.id),
                affected_entity_type="Organization",
                affected_entity_id=str(org.id),
                payload={"suspended_days": SUSPENDED_BEFORE_PURGE_DAYS},
            )
            counts["to_purge_pending"] += 1

    return counts
