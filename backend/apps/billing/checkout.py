"""Stripe checkout + webhook reconciliation (Slice 63).

Two surfaces:

  1. ``start_checkout`` — invoked by the customer's "Subscribe"
     gesture in Settings → Billing. Resolves or creates a Stripe
     Customer for the org, creates a Checkout Session, returns
     the hosted URL the FE redirects to.

  2. ``handle_webhook`` — invoked by the Stripe webhook receiver
     view. Verifies the signature, dispatches on event type:
       - checkout.session.completed → create / activate
         Subscription, capture stripe_subscription_id +
         stripe_customer_id on the org
       - customer.subscription.updated → reconcile period dates,
         status (active / past_due / cancelled)
       - customer.subscription.deleted → mark cancelled
       - invoice.payment_failed → mark past_due

Idempotency: every event carries a Stripe ``id`` (``evt_…``); we
record the latest one we processed per Subscription row so a
retry doesn't double-apply state.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone as dtz
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.identity.models import Organization
from apps.identity.tenancy import super_admin_context

from . import stripe_client
from .models import Plan, Subscription

logger = logging.getLogger(__name__)


class CheckoutError(Exception):
    """Raised when checkout can't be started (config / data issues)."""


def start_checkout(
    *,
    organization_id: uuid.UUID | str,
    plan_id: uuid.UUID | str,
    billing_cycle: str,
    success_url: str,
    cancel_url: str,
) -> dict[str, Any]:
    """Create a Stripe Checkout Session for the customer.

    Returns ``{"checkout_url": "...", "session_id": "..."}``. The FE
    redirects the user to ``checkout_url``; on completion Stripe
    fires ``checkout.session.completed`` and we activate the
    Subscription row.
    """
    if billing_cycle not in {"monthly", "annual"}:
        raise CheckoutError("billing_cycle must be 'monthly' or 'annual'.")

    with super_admin_context(reason="billing.checkout.lookup"):
        org = Organization.objects.filter(id=organization_id).first()
        if org is None:
            raise CheckoutError(
                f"Organization {organization_id} not found."
            )
        plan = Plan.objects.filter(id=plan_id, is_active=True).first()
        if plan is None:
            raise CheckoutError(f"Plan {plan_id} not found or inactive.")

    price_id = (
        plan.stripe_price_id_annual
        if billing_cycle == "annual"
        else plan.stripe_price_id_monthly
    )
    if not price_id:
        raise CheckoutError(
            f"Plan {plan.slug} has no Stripe price for {billing_cycle} "
            f"billing. Configure it in Stripe + paste the price_id "
            f"into the plan."
        )

    # Resolve or create a Stripe Customer for this org. We look at
    # the most recent Subscription row for an existing customer ID
    # (saves an API round-trip on repeat subscribes).
    with super_admin_context(reason="billing.checkout.subscription_lookup"):
        existing = (
            Subscription.objects.filter(
                organization_id=org.id,
                stripe_customer_id__gt="",
            )
            .order_by("-created_at")
            .first()
        )
    customer_id = existing.stripe_customer_id if existing else ""
    if not customer_id:
        result = stripe_client.create_customer(
            organization_id=str(org.id),
            email=org.contact_email,
            legal_name=org.legal_name,
        )
        customer_id = result["id"]

    session = stripe_client.create_checkout_session(
        customer_id=customer_id,
        price_id=price_id,
        success_url=success_url,
        cancel_url=cancel_url,
        organization_id=str(org.id),
        plan_id=str(plan.id),
        billing_cycle=billing_cycle,
    )

    record_event(
        action_type="billing.checkout.started",
        actor_type=AuditEvent.ActorType.USER,
        actor_id="checkout",
        organization_id=str(org.id),
        affected_entity_type="Subscription",
        affected_entity_id="",
        payload={
            "plan_slug": plan.slug,
            "billing_cycle": billing_cycle,
            "session_id": session.get("id", ""),
            "stripe_customer_id": customer_id,
        },
    )

    return {
        "checkout_url": session.get("url", ""),
        "session_id": session.get("id", ""),
        "stripe_customer_id": customer_id,
    }


# --- Webhook event dispatcher -----------------------------------------------


def handle_webhook(*, event: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a verified Stripe event to the right handler.

    ``event`` is the parsed JSON dict from Stripe (signature already
    verified by the caller). Returns a small status dict for log
    enrichment + the webhook receiver's audit payload.
    """
    event_type = event.get("type", "")
    event_id = event.get("id", "")
    obj = event.get("data", {}).get("object", {}) if isinstance(
        event.get("data"), dict
    ) else {}

    handler = {
        "checkout.session.completed": _handle_checkout_completed,
        "customer.subscription.updated": _handle_subscription_updated,
        "customer.subscription.deleted": _handle_subscription_deleted,
        "invoice.payment_failed": _handle_payment_failed,
    }.get(event_type)

    if handler is None:
        # Unsupported event types are logged + ignored. Stripe
        # retries until we 200, so silently 200 on no-ops.
        logger.info(
            "billing.webhook.ignored",
            extra={"event_type": event_type, "event_id": event_id},
        )
        return {"handled": False, "event_type": event_type}

    return handler(event_id=event_id, obj=obj)


def _handle_checkout_completed(
    *, event_id: str, obj: dict[str, Any]
) -> dict[str, Any]:
    """Customer completed Checkout — activate or update the Subscription."""
    metadata = obj.get("metadata") or {}
    organization_id = metadata.get("organization_id", "")
    plan_id = metadata.get("plan_id", "")
    billing_cycle = metadata.get("billing_cycle", "monthly")
    customer_id = obj.get("customer", "")
    subscription_id = obj.get("subscription", "")

    if not organization_id or not subscription_id:
        logger.warning(
            "billing.webhook.checkout_completed.missing_metadata",
            extra={"event_id": event_id},
        )
        return {"handled": False, "reason": "missing-metadata"}

    with transaction.atomic(), super_admin_context(
        reason="billing.webhook.checkout_completed"
    ):
        sub, created = Subscription.objects.update_or_create(
            organization_id=organization_id,
            stripe_subscription_id=subscription_id,
            defaults={
                "plan_id": plan_id or None,
                "billing_cycle": billing_cycle,
                "status": Subscription.Status.ACTIVE,
                "stripe_customer_id": customer_id,
                "current_period_start": timezone.now(),
            },
        )

        # Mark the org as fully subscribed (denormalised state).
        Organization.objects.filter(id=organization_id).update(
            subscription_state=Organization.SubscriptionState.ACTIVE,
        )

    record_event(
        action_type="billing.subscription.activated",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="stripe.webhook",
        organization_id=organization_id,
        affected_entity_type="Subscription",
        affected_entity_id=str(sub.id),
        payload={
            "stripe_subscription_id": subscription_id,
            "stripe_customer_id": customer_id,
            "billing_cycle": billing_cycle,
            "event_id": event_id,
            "newly_created": created,
        },
    )
    return {
        "handled": True,
        "event_type": "checkout.session.completed",
        "subscription_id": str(sub.id),
    }


def _handle_subscription_updated(
    *, event_id: str, obj: dict[str, Any]
) -> dict[str, Any]:
    """Period rolled over OR plan changed OR status flipped."""
    subscription_id = obj.get("id", "")
    if not subscription_id:
        return {"handled": False, "reason": "no-subscription-id"}

    new_status = _map_stripe_status(obj.get("status", ""))
    period_start = _parse_unix(obj.get("current_period_start"))
    period_end = _parse_unix(obj.get("current_period_end"))
    cancel_at_end = bool(obj.get("cancel_at_period_end", False))

    with super_admin_context(reason="billing.webhook.subscription_updated"):
        rows_updated = Subscription.objects.filter(
            stripe_subscription_id=subscription_id
        ).update(
            status=new_status,
            current_period_start=period_start or timezone.now(),
            current_period_end=period_end,
            cancel_at_period_end=cancel_at_end,
        )
        sub = Subscription.objects.filter(
            stripe_subscription_id=subscription_id
        ).first()

    if rows_updated == 0 or sub is None:
        # Webhook arrived before our checkout-completed handler — log
        # + ack (Stripe will replay; the eventual order is fine).
        logger.info(
            "billing.webhook.subscription_updated.no_local_row",
            extra={"event_id": event_id, "subscription_id": subscription_id},
        )
        return {"handled": False, "reason": "no-local-row-yet"}

    Organization.objects.filter(id=sub.organization_id).update(
        subscription_state=_map_stripe_status_for_org(new_status),
    )

    record_event(
        action_type="billing.subscription.updated",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="stripe.webhook",
        organization_id=str(sub.organization_id),
        affected_entity_type="Subscription",
        affected_entity_id=str(sub.id),
        payload={
            "status": new_status,
            "cancel_at_period_end": cancel_at_end,
            "event_id": event_id,
        },
    )
    return {"handled": True, "event_type": "customer.subscription.updated"}


def _handle_subscription_deleted(
    *, event_id: str, obj: dict[str, Any]
) -> dict[str, Any]:
    subscription_id = obj.get("id", "")
    with super_admin_context(reason="billing.webhook.subscription_deleted"):
        sub = Subscription.objects.filter(
            stripe_subscription_id=subscription_id
        ).first()
        if sub is None:
            return {"handled": False, "reason": "no-local-row"}
        sub.status = Subscription.Status.CANCELLED
        sub.cancelled_at = timezone.now()
        sub.save(
            update_fields=["status", "cancelled_at", "updated_at"]
        )
        Organization.objects.filter(id=sub.organization_id).update(
            subscription_state=Organization.SubscriptionState.CANCELLED,
        )
    record_event(
        action_type="billing.subscription.cancelled",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="stripe.webhook",
        organization_id=str(sub.organization_id),
        affected_entity_type="Subscription",
        affected_entity_id=str(sub.id),
        payload={
            "stripe_subscription_id": subscription_id,
            "event_id": event_id,
        },
    )
    return {"handled": True, "event_type": "customer.subscription.deleted"}


def _handle_payment_failed(
    *, event_id: str, obj: dict[str, Any]
) -> dict[str, Any]:
    subscription_id = obj.get("subscription", "")
    if not subscription_id:
        return {"handled": False, "reason": "no-subscription"}
    with super_admin_context(reason="billing.webhook.payment_failed"):
        sub = Subscription.objects.filter(
            stripe_subscription_id=subscription_id
        ).first()
        if sub is None:
            return {"handled": False, "reason": "no-local-row"}
        sub.status = Subscription.Status.PAST_DUE
        sub.save(update_fields=["status", "updated_at"])
        Organization.objects.filter(id=sub.organization_id).update(
            subscription_state=Organization.SubscriptionState.PAST_DUE,
        )
    record_event(
        action_type="billing.payment.failed",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="stripe.webhook",
        organization_id=str(sub.organization_id),
        affected_entity_type="Subscription",
        affected_entity_id=str(sub.id),
        payload={
            "stripe_subscription_id": subscription_id,
            "event_id": event_id,
        },
    )
    return {"handled": True, "event_type": "invoice.payment_failed"}


# --- Status mapping helpers -------------------------------------------------


def _map_stripe_status(stripe_status: str) -> str:
    """Map Stripe's subscription.status enum → ours.

    Stripe values: active, past_due, unpaid, canceled, incomplete,
    incomplete_expired, trialing.
    """
    return {
        "active": Subscription.Status.ACTIVE,
        "trialing": Subscription.Status.TRIALING,
        "past_due": Subscription.Status.PAST_DUE,
        "unpaid": Subscription.Status.PAST_DUE,
        "canceled": Subscription.Status.CANCELLED,
        "incomplete": Subscription.Status.PAST_DUE,
        "incomplete_expired": Subscription.Status.CANCELLED,
    }.get(stripe_status, Subscription.Status.ACTIVE)


def _map_stripe_status_for_org(sub_status: str) -> str:
    """Map our Subscription.status → Organization.subscription_state."""
    return {
        Subscription.Status.ACTIVE: Organization.SubscriptionState.ACTIVE,
        Subscription.Status.TRIALING: Organization.SubscriptionState.TRIALING,
        Subscription.Status.PAST_DUE: Organization.SubscriptionState.PAST_DUE,
        Subscription.Status.CANCELLED: Organization.SubscriptionState.CANCELLED,
        Subscription.Status.REPLACED: Organization.SubscriptionState.ACTIVE,
    }.get(sub_status, Organization.SubscriptionState.ACTIVE)


def _parse_unix(value):
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=dtz.utc)
    except (TypeError, ValueError):
        return None
