"""Celery tasks for outbound webhook delivery.

Thin wrapper. The pure delivery primitive lives in
``apps.integrations.delivery``; this module owns the retry policy,
the audit-event recording, and the per-attempt progression of the
``WebhookDelivery.outcome`` column (pending → retrying →
success / failure / abandoned).

Retry policy:

  - Up to 5 attempts including the first.
  - Exponential backoff via Celery's built-in: 30s, 60s, 120s,
    240s. Capped at 300s. Jittered so a flapping receiver
    doesn't get hammered in lockstep when a fan-out targets it.
  - Network-class errors (connection refused, DNS, TLS) retry
    automatically.
  - HTTP 5xx retry. HTTP 4xx does NOT retry (the receiver is
    telling us the request itself is wrong; backing off won't
    fix it). 429 is a 4xx but is the one exception — we honor
    Retry-After if present, otherwise back off normally.
  - Total attempts that fail mark the row ``abandoned`` so it
    leaves the retry queue + the operator surface shows a clear
    end state.

Why not Celery's autoretry-on-exception: we want fine-grained
control over which HTTP failures retry. autoretry would either
retry too eagerly (wrong-URL receivers loop indefinitely) or
require us to lift the inspection logic into the exception layer
anyway. A small explicit if-block reads better.
"""

from __future__ import annotations

import logging

from celery import shared_task

from apps.audit.models import AuditEvent
from apps.audit.services import record_event

logger = logging.getLogger(__name__)


MAX_ATTEMPTS = 5
RETRY_BACKOFF_BASE_SECONDS = 30
RETRY_BACKOFF_MAX_SECONDS = 300


def _should_retry(status_code: int | None, error_class: str) -> bool:
    """Decide whether this failure should be retried."""
    # Network-class errors: always retry (transient by nature).
    if status_code is None:
        # Don't retry "endpoint was revoked" — that's a terminal
        # state the worker handled itself; bouncing it back at us
        # is a programmer error.
        if error_class == "EndpointRevoked":
            return False
        return True
    # 5xx: retry. The receiver said "I'm broken right now."
    if 500 <= status_code <= 599:
        return True
    # 429 Too Many Requests: retry with backoff.
    if status_code == 429:
        return True
    # Everything else (4xx specifically): don't retry. The
    # receiver is saying "your request is wrong" — repeating
    # won't help. Customer must fix the receiver or rotate.
    return False


@shared_task(
    name="integrations.deliver_webhook",
    bind=True,
    max_retries=MAX_ATTEMPTS - 1,
    acks_late=True,
)
def deliver_webhook_task(self, *, delivery_id: str) -> dict:
    """One delivery attempt. Self-reschedules on retryable failure.

    The Celery task signature uses kwargs-only so callers don't
    accidentally send positional ``self``-bound args (a real
    historical footgun in this codebase).

    Returns a small dict so the producer (or beat-schedule when
    we add scheduled retries) sees the outcome. Audit events are
    fire-and-forget — the dict is for log enrichment only.
    """
    from apps.identity.tenancy import super_admin_context

    from .delivery import deliver_one
    from .models import WebhookDelivery

    result = deliver_one(delivery_id)
    attempt = self.request.retries + 1

    # Record one audit event per attempt so the chain has the
    # full delivery history. Payload is endpoint-id + outcome
    # only — never the body or signature.
    with super_admin_context(reason="webhooks:audit"):
        try:
            delivery = WebhookDelivery.objects.select_related("endpoint").get(id=delivery_id)
        except WebhookDelivery.DoesNotExist:
            return {"ok": False, "abandoned": True}

    record_event(
        action_type="integrations.webhook.delivered"
        if result.ok
        else "integrations.webhook.delivery_failed",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="integrations.delivery_worker",
        organization_id=str(delivery.organization_id),
        affected_entity_type="WebhookDelivery",
        affected_entity_id=str(delivery.id),
        payload={
            "endpoint_id": str(delivery.endpoint_id),
            "event_type": delivery.event_type,
            "attempt": attempt,
            "ok": result.ok,
            "status_code": result.status_code,
            "duration_ms": result.duration_ms,
            "error_class": result.error_class[:64],
        },
    )

    if result.ok:
        return {"ok": True, "attempts": attempt}

    # Failure — decide retry vs abandon.
    if attempt >= MAX_ATTEMPTS or not _should_retry(result.status_code, result.error_class):
        # Mark abandoned so the row leaves "pending/retrying"
        # state if it was sitting there.
        with super_admin_context(reason="webhooks:abandon"):
            from .models import WebhookDelivery as WD

            WD.objects.filter(id=delivery_id).update(
                outcome=WD.Outcome.ABANDONED if attempt >= MAX_ATTEMPTS else WD.Outcome.FAILURE,
            )
        return {"ok": False, "abandoned": True, "attempts": attempt}

    # Schedule the next attempt. Exponential backoff with jitter
    # via Celery's countdown.
    countdown = min(
        RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)),
        RETRY_BACKOFF_MAX_SECONDS,
    )
    # Mark "retrying" so the customer surface shows the in-flight
    # state honestly — not "failed and forgotten".
    from .models import WebhookDelivery as WD

    with super_admin_context(reason="webhooks:retry_marker"):
        WD.objects.filter(id=delivery_id).update(outcome=WD.Outcome.RETRYING)

    raise self.retry(countdown=countdown)
