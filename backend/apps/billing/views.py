"""Billing endpoints — read-mostly for the customer Settings → Billing tab.

Write paths (subscription create / cancel / upgrade) ship with the
Stripe wiring slice; today the customer sees their plan + usage but
can't change billing state from here.
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.identity import services as identity_services

from . import services


@api_view(["GET"])
@permission_classes([AllowAny])
def public_plans(request: Request) -> Response:
    """Public pricing-page plan catalog. No auth required."""
    return Response({"results": services.list_public_plans()})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def billing_overview(request: Request) -> Response:
    """Customer's current subscription + usage for the active org."""
    organization_id = request.session.get("organization_id")
    if not organization_id:
        return Response(
            {"detail": "No active organization."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not identity_services.can_user_act_for_organization(
        request.user, organization_id
    ):
        return Response(
            {"detail": "You are not a member of that organization."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return Response(
        {
            "subscription": services.get_active_subscription(
                organization_id=organization_id
            ),
            "usage": services.current_period_usage(
                organization_id=organization_id
            ),
            "available_plans": services.list_public_plans(),
        }
    )


# --- Slice 63: Stripe checkout + webhook ----------------------------------


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def start_checkout_view(request: Request) -> Response:
    """Start a Stripe Checkout Session for the active org.

    Body:
        {
          "plan_id": "<uuid>",
          "billing_cycle": "monthly|annual",
          "success_url": "https://app.zerokey.../subscribe-success",
          "cancel_url":  "https://app.zerokey.../settings/billing"
        }

    Returns ``{"checkout_url": "...", "session_id": "...",
    "stripe_customer_id": "..."}``. The FE redirects the user to
    ``checkout_url``; on completion Stripe fires the webhook +
    we activate the Subscription.
    """
    organization_id = request.session.get("organization_id")
    if not organization_id:
        return Response(
            {"detail": "No active organization."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not identity_services.can_user_act_for_organization(
        request.user, organization_id
    ):
        return Response(
            {"detail": "You are not a member of that organization."},
            status=status.HTTP_403_FORBIDDEN,
        )

    body = request.data or {}
    plan_id = str(body.get("plan_id") or "").strip()
    billing_cycle = str(body.get("billing_cycle") or "monthly").strip()
    success_url = str(body.get("success_url") or "").strip()
    cancel_url = str(body.get("cancel_url") or "").strip()
    if not plan_id or not success_url or not cancel_url:
        return Response(
            {
                "detail": (
                    "plan_id, success_url, and cancel_url are required."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    from . import checkout, stripe_client

    try:
        result = checkout.start_checkout(
            organization_id=organization_id,
            plan_id=plan_id,
            billing_cycle=billing_cycle,
            success_url=success_url,
            cancel_url=cancel_url,
        )
    except checkout.CheckoutError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except stripe_client.StripeAuthError as exc:
        return Response(
            {"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY
        )
    except stripe_client.StripeError as exc:
        return Response(
            {"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY
        )
    return Response(result)


from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import authentication_classes


@csrf_exempt
@api_view(["POST"])
@permission_classes([])
@authentication_classes([])
def stripe_webhook_view(request: Request) -> Response:
    """Stripe webhook receiver.

    Stripe POSTs raw JSON with a ``Stripe-Signature`` header.
    No CSRF / session auth (Stripe is the caller, identified by
    HMAC). The signature header is the auth.

    On success: returns 200. Stripe retries indefinitely on any
    non-2xx, so we 200 even on unsupported event types (those are
    just logged + dropped).
    """
    from . import checkout, stripe_client

    signature = request.headers.get("Stripe-Signature", "")
    raw_body = request.body if hasattr(request, "body") else b""

    try:
        event = stripe_client.verify_webhook_signature(
            payload=raw_body, signature_header=signature
        )
    except stripe_client.StripeWebhookError as exc:
        # 400 — malformed / unverifiable. Stripe will retry; if the
        # signature is genuinely bad they'll keep retrying forever
        # (operator should rotate the signing secret).
        return Response(
            {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST
        )
    except stripe_client.StripeError as exc:
        return Response(
            {"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY
        )

    try:
        result = checkout.handle_webhook(event=event)
    except Exception:  # noqa: BLE001
        # If our handler crashes, return 500 so Stripe retries —
        # but log the actual stack so we can fix it.
        import logging

        logging.getLogger(__name__).exception(
            "billing.webhook.handler_error",
            extra={"event_id": event.get("id", "")},
        )
        return Response(
            {"detail": "Internal error processing webhook."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return Response(result)
