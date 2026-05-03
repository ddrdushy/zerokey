"""Stripe API client (Slice 63).

Direct httpx wrapper rather than the official SDK — same pattern
we use for LHDN (apps.submission.lhdn_client). Lets us avoid a
new dependency + keeps the Stripe surface small + transparent.
We use exactly five Stripe endpoints today:

  - POST /v1/customers              create a Customer per organization
  - POST /v1/checkout/sessions      hosted-checkout URL for plan signup
  - POST /v1/billing_portal/sessions   self-service plan management
  - GET  /v1/subscriptions/{id}     status reconciliation on demand
  - Webhook signature verification  for inbound events

Webhook signature scheme (per Stripe docs):
  Stripe sends a header ``Stripe-Signature: t=<unix>,v1=<sig>``.
  ``v1`` is HMAC-SHA256 of ``f"{t}.{body}"`` keyed by the
  webhook signing secret (whsec_…). We accept events whose
  signature verifies AND whose timestamp is within a small
  window (5 min default) to bound replay risk.

Credentials live in ``SystemSetting('stripe')`` (Slice 41 schema)
and are encrypted at rest via Slice 55. The resolver here decrypts
on demand.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from apps.administration.services import system_setting

logger = logging.getLogger(__name__)


STRIPE_API_BASE = "https://api.stripe.com/v1"
REQUEST_TIMEOUT_SECONDS = 15.0

# Replay window for webhook signatures. Stripe's docs recommend
# 5 minutes; events older than this are rejected even if the
# signature otherwise verifies.
WEBHOOK_TOLERANCE_SECONDS = 5 * 60


class StripeError(Exception):
    """Base class for Stripe API errors."""


class StripeAuthError(StripeError):
    """401/403 from Stripe — bad secret key."""


class StripeWebhookError(StripeError):
    """Webhook signature failed verification or replay window expired."""


@dataclass
class StripeCredentials:
    secret_key: str
    publishable_key: str
    webhook_secret: str
    default_currency: str = "MYR"


def credentials() -> StripeCredentials:
    """Load Stripe creds from SystemSetting (encrypted at rest)."""
    secret = system_setting(namespace="stripe", key="secret_key", env_fallback="STRIPE_SECRET_KEY")
    if not secret:
        raise StripeError(
            "Stripe is not configured. Set the secret_key in admin "
            "Settings or the STRIPE_SECRET_KEY env var."
        )
    return StripeCredentials(
        secret_key=secret,
        publishable_key=system_setting(namespace="stripe", key="publishable_key") or "",
        webhook_secret=system_setting(namespace="stripe", key="webhook_secret") or "",
        default_currency=(system_setting(namespace="stripe", key="default_currency") or "MYR"),
    )


def _post(
    *,
    creds: StripeCredentials,
    path: str,
    data: dict[str, Any],
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {creds.secret_key}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    try:
        response = httpx.post(
            f"{STRIPE_API_BASE}{path}",
            data=_form_encode(data),
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise StripeError(f"Stripe request failed: {type(exc).__name__}") from exc

    if response.status_code in (401, 403):
        raise StripeAuthError("Stripe rejected the secret key.")
    if response.status_code >= 500:
        raise StripeError(f"Stripe server error: HTTP {response.status_code}")
    body = response.json()
    if response.status_code >= 400:
        err = body.get("error", {}) if isinstance(body, dict) else {}
        msg = err.get("message") or f"HTTP {response.status_code}"
        # Stripe error messages don't carry secrets — surfacing them
        # is fine. Cap length so a runaway message doesn't bloat
        # the error response.
        raise StripeError(msg[:500])
    return body


def _get(*, creds: StripeCredentials, path: str) -> dict[str, Any]:
    try:
        response = httpx.get(
            f"{STRIPE_API_BASE}{path}",
            headers={"Authorization": f"Bearer {creds.secret_key}"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise StripeError(f"Stripe request failed: {type(exc).__name__}") from exc

    if response.status_code in (401, 403):
        raise StripeAuthError("Stripe rejected the secret key.")
    if response.status_code == 404:
        raise StripeError("Stripe resource not found.")
    if response.status_code >= 500:
        raise StripeError(f"Stripe server error: HTTP {response.status_code}")
    return response.json()


def _form_encode(data: dict[str, Any]) -> dict[str, str]:
    """Stripe wants form-encoded bodies, with nested keys flattened
    via ``parent[child]`` notation. Most of our payloads are flat
    today; this handles the ``metadata[org_id]`` style we use for
    Customer creation.
    """
    out: dict[str, str] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            for sub, sub_value in value.items():
                out[f"{key}[{sub}]"] = str(sub_value)
        elif isinstance(value, list):
            for idx, item in enumerate(value):
                if isinstance(item, dict):
                    for sub, sub_value in item.items():
                        out[f"{key}[{idx}][{sub}]"] = str(sub_value)
                else:
                    out[f"{key}[{idx}]"] = str(item)
        elif value is None:
            continue
        elif isinstance(value, bool):
            out[key] = "true" if value else "false"
        else:
            out[key] = str(value)
    return out


# --- Customers --------------------------------------------------------------


def create_customer(
    *,
    organization_id: str,
    email: str,
    legal_name: str,
) -> dict[str, Any]:
    """Create a Stripe Customer for the given organization.

    The org id goes in metadata so webhooks can reverse-lookup
    which tenant a customer belongs to.
    """
    return _post(
        creds=credentials(),
        path="/customers",
        data={
            "email": email,
            "name": legal_name,
            "metadata": {"organization_id": organization_id},
        },
        idempotency_key=f"customer:{organization_id}",
    )


# --- Checkout sessions ------------------------------------------------------


def create_checkout_session(
    *,
    customer_id: str,
    price_id: str,
    success_url: str,
    cancel_url: str,
    organization_id: str,
    plan_id: str,
    billing_cycle: str,
) -> dict[str, Any]:
    """Create a Stripe-hosted checkout session for plan signup.

    Returns the session dict; the FE redirects the user to
    ``session.url``. On completion Stripe fires the
    ``checkout.session.completed`` webhook + we provision the
    Subscription server-side.
    """
    return _post(
        creds=credentials(),
        path="/checkout/sessions",
        data={
            "mode": "subscription",
            "customer": customer_id,
            "success_url": success_url,
            "cancel_url": cancel_url,
            "line_items": [
                {
                    "price": price_id,
                    "quantity": 1,
                }
            ],
            # FPX is a Malaysian local payment method. Enabling it
            # in the dashboard is a one-click toggle on Stripe's
            # side; here we just permit the method.
            "payment_method_types": ["card", "fpx"],
            "metadata": {
                "organization_id": organization_id,
                "plan_id": plan_id,
                "billing_cycle": billing_cycle,
            },
        },
    )


def get_subscription(*, subscription_id: str) -> dict[str, Any]:
    """Fetch subscription state + period dates."""
    return _get(creds=credentials(), path=f"/subscriptions/{subscription_id}")


def create_billing_portal_session(
    *,
    customer_id: str,
    return_url: str,
) -> dict[str, Any]:
    """Create a Stripe-hosted Customer Portal session.

    The portal handles plan changes, payment method updates, invoice
    history, and cancellation in one Stripe-managed surface — frees
    us from rebuilding any of that. The customer is redirected to
    ``session.url`` and bounced back to ``return_url`` when done.
    """
    return _post(
        creds=credentials(),
        path="/billing_portal/sessions",
        data={
            "customer": customer_id,
            "return_url": return_url,
        },
    )


def list_invoices(*, customer_id: str, limit: int = 24) -> dict[str, Any]:
    """List invoices for a Stripe customer.

    Slice 100 — the customer's "Invoice + receipt history" surface.
    Stripe issues + hosts these PDFs; we only present the list.
    """
    return _get(
        creds=credentials(),
        path=f"/invoices?customer={customer_id}&limit={int(limit)}",
    )


def cancel_stripe_subscription(
    *,
    subscription_id: str,
    immediate: bool,
) -> dict[str, Any]:
    """Cancel a Stripe Subscription either immediately or at period end."""
    if immediate:
        # Stripe's cancel endpoint is DELETE on /subscriptions/{id};
        # _post doesn't speak DELETE, so we fall back to httpx here.
        creds = credentials()
        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as c:
                r = c.delete(
                    f"{STRIPE_API_BASE}/subscriptions/{subscription_id}",
                    headers={"Authorization": f"Bearer {creds.secret_key}"},
                )
        except httpx.HTTPError as exc:
            raise StripeError(f"Stripe cancel failed: {exc}") from exc
        if r.status_code in (401, 403):
            raise StripeAuthError("Stripe rejected the API key.")
        if r.status_code >= 400:
            raise StripeError(f"Stripe returned {r.status_code}: {r.text[:200]}")
        return r.json()
    # period_end: POST update with cancel_at_period_end=true
    return _post(
        creds=credentials(),
        path=f"/subscriptions/{subscription_id}",
        data={"cancel_at_period_end": "true"},
    )


# --- Webhook signature verification -----------------------------------------


def verify_webhook_signature(*, payload: bytes, signature_header: str) -> dict[str, Any]:
    """Verify a Stripe-Signature header + return the parsed event.

    Header format: ``t=<unix>,v1=<hex-hmac>``. The signed payload is
    ``f"{t}.{body}"``. We support multiple ``v1`` entries (Stripe
    rotates webhook secrets via dual-issue) by accepting if any
    matches.

    Raises StripeWebhookError on:
      - missing/malformed header
      - timestamp older than WEBHOOK_TOLERANCE_SECONDS
      - no v1 signature matches the configured webhook_secret
    """
    creds = credentials()
    if not creds.webhook_secret:
        raise StripeWebhookError("Stripe webhook_secret is not configured.")

    if not signature_header:
        raise StripeWebhookError("Missing Stripe-Signature header.")

    parts = {}
    for kv in signature_header.split(","):
        if "=" not in kv:
            continue
        k, v = kv.strip().split("=", 1)
        parts.setdefault(k, []).append(v)

    timestamp_raw = (parts.get("t") or [""])[0]
    v1_signatures = parts.get("v1") or []
    if not timestamp_raw or not v1_signatures:
        raise StripeWebhookError("Malformed Stripe-Signature header.")

    try:
        timestamp = int(timestamp_raw)
    except ValueError as exc:
        raise StripeWebhookError("Bad timestamp in Stripe-Signature.") from exc

    age = abs(int(time.time()) - timestamp)
    if age > WEBHOOK_TOLERANCE_SECONDS:
        raise StripeWebhookError(f"Stripe webhook event is too old ({age}s).")

    signed_payload = f"{timestamp_raw}.".encode() + payload
    expected = hmac.new(
        creds.webhook_secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    if not any(hmac.compare_digest(expected, sig) for sig in v1_signatures):
        raise StripeWebhookError("Stripe-Signature did not verify.")

    # Signature verified — parse the event body.
    import json as _json

    try:
        return _json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, _json.JSONDecodeError) as exc:
        raise StripeWebhookError("Stripe webhook body is not valid JSON.") from exc
