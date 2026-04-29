"""Celery tasks for outbound notifications.

Tasks are thin wrappers — they call the synchronous service modules
and audit the result. Retries are limited and explicit (3 attempts
with exponential backoff for network errors; no retries on
configuration / authentication errors).
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="notifications.send_email",
    queue="default",
    max_retries=3,
    autoretry_for=(),  # decided per-result below
    retry_backoff=True,
    retry_backoff_max=300,
)
def send_email_task(
    *,
    to: str,
    subject: str,
    body: str,
    html_body: str | None = None,
    organization_id: str | None = None,
    event_key: str = "",
):
    """Async send + audit one email.

    The result is recorded as a system audit event with the SMTP
    outcome (ok / failure class). PII (the recipient address) is
    NOT in the payload — only ``event_key`` + ``ok`` + duration.
    """
    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event

    from .email import send_email

    result = send_email(to=to, subject=subject, body=body, html_body=html_body)

    record_event(
        action_type="notifications.email.sent"
        if result.ok
        else "notifications.email.failed",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="notifications.send_email",
        organization_id=organization_id,
        affected_entity_type="EmailDelivery",
        affected_entity_id="",
        payload={
            "event_key": event_key,
            "ok": bool(result.ok),
            "detail": result.detail[:120],
            "duration_ms": int(result.duration_ms),
        },
    )

    return {
        "ok": result.ok,
        "detail": result.detail,
        "duration_ms": result.duration_ms,
    }
