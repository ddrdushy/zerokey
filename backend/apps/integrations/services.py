"""Integrations services — webhook endpoints + deliveries.

Customer-facing today: register/list/test/revoke webhook endpoints.
The actual outbound delivery worker lands in a follow-up; this slice
gives customers a place to register endpoints + see the (synthetic
test) delivery history while the worker bakes.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from urllib.parse import urlparse

from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import record_event

from .models import WebhookDelivery, WebhookEndpoint, generate_secret


# Canonical list of event keys customers may subscribe to. The future
# delivery worker fans out events of these types; the customer
# registration UI shows this list as checkboxes.
WEBHOOK_EVENT_KEYS: list[tuple[str, str]] = [
    ("invoice.created", "Invoice created"),
    ("invoice.validated", "Invoice validated"),
    ("invoice.lhdn_rejected", "LHDN rejection"),
    ("invoice.submitted", "Invoice submitted to MyInvois"),
    ("inbox.item_opened", "Inbox item opened"),
]


class WebhookError(Exception):
    """Raised when a webhook operation can't be applied."""


def _validate_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise WebhookError("URL is required.")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise WebhookError("URL must be http:// or https://.")
    if not parsed.netloc:
        raise WebhookError("URL must include a hostname.")
    return url


def _validate_event_types(event_types: list[str] | None) -> list[str]:
    if event_types is None:
        return []
    if not isinstance(event_types, list):
        raise WebhookError("event_types must be an array.")
    valid = {key for key, _ in WEBHOOK_EVENT_KEYS}
    invalid = [t for t in event_types if t not in valid]
    if invalid:
        raise WebhookError(
            f"Unknown event types: {sorted(invalid)}. "
            f"Allowed: {sorted(valid)}"
        )
    return list(event_types)


def create_webhook(
    *,
    organization_id: uuid.UUID | str,
    label: str,
    url: str,
    event_types: list[str] | None,
    actor_user_id: uuid.UUID | str,
) -> tuple[WebhookEndpoint, str]:
    """Mint a webhook endpoint, return ``(row, plaintext_secret)``.

    Plaintext is shown ONCE to the customer at the call site and never
    persisted. Audited as ``integrations.webhook.created``.
    """
    label = (label or "").strip()
    if not label:
        raise WebhookError("Label is required.")
    if len(label) > 64:
        raise WebhookError("Label must be 64 characters or fewer.")

    url = _validate_url(url)
    events = _validate_event_types(event_types)

    plaintext, prefix, sha = generate_secret()

    row = WebhookEndpoint.objects.create(
        organization_id=organization_id,
        label=label,
        url=url,
        event_types=events,
        secret_prefix=prefix,
        secret_hash=sha,
        created_by_user_id=actor_user_id,
        is_active=True,
    )
    record_event(
        action_type="integrations.webhook.created",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(organization_id),
        affected_entity_type="WebhookEndpoint",
        affected_entity_id=str(row.id),
        payload={
            "label": label,
            "url_host": urlparse(url).netloc,
            "event_types": sorted(events),
        },
    )
    return row, plaintext


def list_webhooks(
    *, organization_id: uuid.UUID | str
) -> list[dict[str, Any]]:
    qs = WebhookEndpoint.objects.filter(
        organization_id=organization_id
    ).order_by("-created_at")
    return [_endpoint_dict(r) for r in qs]


def revoke_webhook(
    *,
    organization_id: uuid.UUID | str,
    webhook_id: uuid.UUID | str,
    actor_user_id: uuid.UUID | str,
) -> dict[str, Any]:
    try:
        row = WebhookEndpoint.objects.get(
            id=webhook_id, organization_id=organization_id
        )
    except WebhookEndpoint.DoesNotExist as exc:
        raise WebhookError(
            f"Webhook {webhook_id} not found in this organization."
        ) from exc

    if not row.is_active:
        return _endpoint_dict(row)

    row.is_active = False
    row.revoked_at = timezone.now()
    row.revoked_by_user_id = actor_user_id
    row.save(update_fields=["is_active", "revoked_at", "revoked_by_user_id", "updated_at"])

    record_event(
        action_type="integrations.webhook.revoked",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(organization_id),
        affected_entity_type="WebhookEndpoint",
        affected_entity_id=str(row.id),
        payload={"label": row.label},
    )
    return _endpoint_dict(row)


def send_test_delivery(
    *,
    organization_id: uuid.UUID | str,
    webhook_id: uuid.UUID | str,
    actor_user_id: uuid.UUID | str,
) -> dict[str, Any]:
    """Create a synthetic delivery row for the test-delivery button.

    Today this DOES NOT fire HTTP — the actual delivery worker isn't
    wired yet. The row exists so the customer sees their endpoint is
    registered correctly + the deliveries surface has data to render.
    Replace the ``outcome=SUCCESS`` line with a real send when the
    worker lands.
    """
    try:
        endpoint = WebhookEndpoint.objects.get(
            id=webhook_id,
            organization_id=organization_id,
            is_active=True,
        )
    except WebhookEndpoint.DoesNotExist as exc:
        raise WebhookError(
            f"Active webhook {webhook_id} not found in this organization."
        ) from exc

    payload = {
        "type": "ping",
        "delivered_at": timezone.now().isoformat(),
        "endpoint_label": endpoint.label,
        "note": "Test delivery — no real HTTP request was made.",
    }
    delivery = WebhookDelivery.objects.create(
        organization_id=organization_id,
        endpoint=endpoint,
        event_type="ping",
        payload=payload,
        attempt=1,
        outcome=WebhookDelivery.Outcome.SUCCESS,
        response_status=200,
        response_body_excerpt="(synthetic — worker not yet wired)",
        delivered_at=timezone.now(),
        duration_ms=0,
    )
    endpoint.last_succeeded_at = delivery.delivered_at
    endpoint.save(update_fields=["last_succeeded_at", "updated_at"])

    record_event(
        action_type="integrations.webhook.test_sent",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(organization_id),
        affected_entity_type="WebhookEndpoint",
        affected_entity_id=str(endpoint.id),
        payload={"delivery_id": str(delivery.id)},
    )

    return _delivery_dict(delivery)


def list_recent_deliveries(
    *,
    organization_id: uuid.UUID | str,
    webhook_id: uuid.UUID | str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    qs = WebhookDelivery.objects.filter(organization_id=organization_id)
    if webhook_id is not None:
        qs = qs.filter(endpoint_id=webhook_id)
    rows = qs.order_by("-queued_at")[:limit]
    return [_delivery_dict(r) for r in rows]


def _endpoint_dict(row: WebhookEndpoint) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "label": row.label,
        "url": row.url,
        "event_types": list(row.event_types or []),
        "secret_prefix": row.secret_prefix,
        "is_active": bool(row.is_active),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "last_succeeded_at": row.last_succeeded_at.isoformat()
        if row.last_succeeded_at
        else None,
        "last_failed_at": row.last_failed_at.isoformat()
        if row.last_failed_at
        else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
    }


def _delivery_dict(row: WebhookDelivery) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "endpoint_id": str(row.endpoint_id),
        "event_id": str(row.event_id),
        "event_type": row.event_type,
        "attempt": int(row.attempt),
        "outcome": row.outcome,
        "response_status": row.response_status,
        "response_body_excerpt": row.response_body_excerpt,
        "error_class": row.error_class,
        "duration_ms": row.duration_ms,
        "queued_at": row.queued_at.isoformat() if row.queued_at else None,
        "delivered_at": row.delivered_at.isoformat()
        if row.delivered_at
        else None,
        "payload_excerpt": json.dumps(row.payload)[:200] if row.payload else "",
    }
