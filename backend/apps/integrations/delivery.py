"""Webhook outbound delivery — HMAC signing + HTTP POST.

Pure delivery primitive. Given a queued ``WebhookDelivery`` row,
this module signs the payload, POSTs to the registered endpoint
URL, and writes the outcome back into the row in place. The retry
+ fan-out policy lives in ``apps.integrations.tasks``; the
fan-out planner lives in ``apps.integrations.services``. Keeping
those separate matches the same shape as
``apps.notifications.email`` (low-level send) /
``apps.notifications.tasks`` (retry policy) /
``apps.notifications.services`` (dispatcher). The pattern is
consistent across the two delivery channels we ship.

Signature shape (Stripe-style, easier to recreate in any
language than naked HMAC headers):

    X-ZeroKey-Signature: t=<unix>,v1=<sha256-hex>

…where ``v1`` is ``HMAC-SHA256(secret, f"{t}.{body}")``. The
timestamp prefix lets receivers reject stale replays without
needing a clock-sync.

The signing secret is the plaintext value the customer was
shown ONCE at create time. We persist it encrypted at rest in
``WebhookEndpoint.secret_encrypted`` (Fernet-AEAD via the
SECRET_KEY-derived key in ``apps.integrations.crypto``) and
decrypt it on demand here for signing. Endpoints created before
this column existed have an empty value — those deliveries go
out unsigned and the operator surface flags them so the
customer can rotate.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass

import httpx
from django.utils import timezone

from .crypto import decrypt_secret
from .models import WebhookDelivery, WebhookEndpoint

logger = logging.getLogger(__name__)

# HTTP timeout per attempt. Receivers that take longer than this
# are treated as failures; retry policy decides whether to give
# up. 10s matches the Stripe + GitHub conventions — long enough
# for warm endpoints, short enough that one bad receiver doesn't
# starve the worker.
REQUEST_TIMEOUT_SECONDS = 10.0

# How much of the response body we keep on the WebhookDelivery row
# for diagnostic surfacing. Bigger than this is a nuisance on the
# UI + costs Postgres pages; receivers that return more should
# trim themselves.
RESPONSE_EXCERPT_LIMIT = 512

# We want the user agent to be fingerprintable for receivers (so
# a customer can build allowlists or differentiate retries from
# fresh sends in their logs) but not fluffy.
USER_AGENT = "ZeroKey-Webhooks/1.0"


@dataclass
class DeliveryResult:
    """Outcome of one HTTP attempt against a webhook endpoint."""

    ok: bool
    status_code: int | None
    body_excerpt: str
    error_class: str
    duration_ms: int


def _resolve_secret_for_signing(endpoint: WebhookEndpoint) -> str | None:
    """Return the plaintext signing secret for outbound HMAC.

    Decrypts ``secret_encrypted`` via Fernet (see
    ``apps.integrations.crypto``). Returns ``None`` if the column
    is empty (legacy row pre-Slice 53) or tampered. The caller
    sends the delivery unsigned in that case + we surface the
    state in audit so the operator can prompt the customer to
    rotate.
    """
    if not endpoint.secret_encrypted:
        return None
    return decrypt_secret(endpoint.secret_encrypted)


def _compute_signature(secret: str, timestamp: int, body: bytes) -> str:
    """Stripe-style ``t=<unix>,v1=<hex>`` signature header value."""
    signed_body = f"{timestamp}.".encode() + body
    digest = hmac.new(
        secret.encode("utf-8"), signed_body, hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


def _truncate(text: str, limit: int = RESPONSE_EXCERPT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def deliver_one(delivery_id: str) -> DeliveryResult:
    """Sign + POST one queued WebhookDelivery row, write outcome back.

    Updates the row's outcome / response_status / body excerpt /
    error_class / duration_ms / delivered_at in place, and bumps
    the parent endpoint's last_succeeded_at / last_failed_at
    cursors so the UI can show "last delivered N minutes ago".

    Does NOT raise on HTTP errors — the caller (Celery task)
    inspects ``DeliveryResult.ok`` to decide whether to retry. We
    DO raise on missing-row / not-active because those are
    programmer errors, not delivery failures.
    """
    from apps.identity.tenancy import super_admin_context

    with super_admin_context(reason="webhooks:delivery"):
        try:
            delivery = WebhookDelivery.objects.select_related(
                "endpoint"
            ).get(id=delivery_id)
        except WebhookDelivery.DoesNotExist as exc:
            raise RuntimeError(
                f"WebhookDelivery {delivery_id} not found"
            ) from exc
        endpoint = delivery.endpoint

    if not endpoint.is_active:
        # Race: endpoint was revoked between fan-out + worker
        # pickup. Mark abandoned so it doesn't sit in pending
        # forever; not a retry.
        _record_outcome(
            delivery,
            outcome=WebhookDelivery.Outcome.ABANDONED,
            status_code=None,
            body_excerpt="",
            error_class="EndpointRevoked",
            duration_ms=0,
        )
        return DeliveryResult(
            ok=False,
            status_code=None,
            body_excerpt="",
            error_class="EndpointRevoked",
            duration_ms=0,
        )

    secret = _resolve_secret_for_signing(endpoint)
    timestamp = int(time.time())
    body_dict = {
        "id": str(delivery.event_id),
        "type": delivery.event_type,
        "created": timestamp,
        "data": delivery.payload,
    }
    body = json.dumps(body_dict, separators=(",", ":"), default=str).encode()
    headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "X-ZeroKey-Event-Id": str(delivery.event_id),
        "X-ZeroKey-Event-Type": delivery.event_type,
        "X-ZeroKey-Delivery-Id": str(delivery.id),
        "X-ZeroKey-Attempt": str(delivery.attempt),
    }
    if secret:
        headers["X-ZeroKey-Signature"] = _compute_signature(
            secret, timestamp, body
        )

    started = time.perf_counter()
    try:
        response = httpx.post(
            endpoint.url,
            content=body,
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
            follow_redirects=False,
        )
    except httpx.HTTPError as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        # Do NOT include str(exc) in the surfaced detail — httpx
        # error messages can leak the request URL fragment back
        # to the customer's UI which is fine, but they sometimes
        # echo TLS handshake bytes which look unhelpful + noisy.
        # Class name is enough to triage.
        error_class = type(exc).__name__
        logger.info(
            "webhooks.delivery.http_error",
            extra={
                "delivery_id": str(delivery.id),
                "endpoint_id": str(endpoint.id),
                "error_class": error_class,
                "duration_ms": duration_ms,
            },
        )
        _record_outcome(
            delivery,
            outcome=WebhookDelivery.Outcome.FAILURE,
            status_code=None,
            body_excerpt="",
            error_class=error_class,
            duration_ms=duration_ms,
        )
        return DeliveryResult(
            ok=False,
            status_code=None,
            body_excerpt="",
            error_class=error_class,
            duration_ms=duration_ms,
        )

    duration_ms = int((time.perf_counter() - started) * 1000)
    # Treat 2xx as success; everything else fails. 3xx is on the
    # failure side because we set follow_redirects=False — a
    # receiver redirecting our POST is misconfigured.
    ok = 200 <= response.status_code < 300
    excerpt = _truncate(response.text or "")
    _record_outcome(
        delivery,
        outcome=WebhookDelivery.Outcome.SUCCESS
        if ok
        else WebhookDelivery.Outcome.FAILURE,
        status_code=response.status_code,
        body_excerpt=excerpt,
        error_class="" if ok else f"HTTP {response.status_code}",
        duration_ms=duration_ms,
    )
    return DeliveryResult(
        ok=ok,
        status_code=response.status_code,
        body_excerpt=excerpt,
        error_class="" if ok else f"HTTP {response.status_code}",
        duration_ms=duration_ms,
    )


def _record_outcome(
    delivery: WebhookDelivery,
    *,
    outcome: str,
    status_code: int | None,
    body_excerpt: str,
    error_class: str,
    duration_ms: int,
) -> None:
    """Persist the outcome onto the delivery row + bump endpoint cursor."""
    from apps.identity.tenancy import super_admin_context

    with super_admin_context(reason="webhooks:delivery_record"):
        now = timezone.now()
        delivery.outcome = outcome
        delivery.response_status = status_code
        delivery.response_body_excerpt = body_excerpt
        delivery.error_class = error_class
        delivery.duration_ms = duration_ms
        delivery.delivered_at = now
        delivery.save(
            update_fields=[
                "outcome",
                "response_status",
                "response_body_excerpt",
                "error_class",
                "duration_ms",
                "delivered_at",
                "updated_at",
            ]
        )

        endpoint = delivery.endpoint
        update_fields = ["updated_at"]
        if outcome == WebhookDelivery.Outcome.SUCCESS:
            endpoint.last_succeeded_at = now
            update_fields.append("last_succeeded_at")
        elif outcome in (
            WebhookDelivery.Outcome.FAILURE,
            WebhookDelivery.Outcome.ABANDONED,
        ):
            endpoint.last_failed_at = now
            update_fields.append("last_failed_at")
        endpoint.save(update_fields=update_fields)
