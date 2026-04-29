"""High-level notification dispatch.

The single cross-context entry point. A producing context (e.g.
``submission`` after an invoice validates) calls
``deliver_for_event(organization_id, event_key, context)`` and the
notifications app:

  1. Looks up active members of the org.
  2. Reads each member's NotificationPreference row.
  3. Per-channel: queues the right delivery task (email today, push
     / SMS later).
  4. The in-app bell is already populated by other audit events; this
     module doesn't send in-app notifications because the bell is a
     glanceable aggregator, not a delivery channel.

Templates live as constants here today — when more events land they
move to a ``templates/`` directory or jinja files. For now keeping
them inline keeps the app tiny.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


# Subject + body templates per event_key. ``{var}`` placeholders are
# filled from ``context``. New events: add an entry here.
_EMAIL_TEMPLATES: dict[str, dict[str, str]] = {
    "invoice.validated": {
        "subject": "Invoice {invoice_number} is ready to submit",
        "body": (
            "Good news — the invoice you uploaded ({filename}) has passed "
            "all LHDN-shape checks and is ready to submit.\n\n"
            "Open it: {invoice_url}\n\n"
            "— ZeroKey"
        ),
    },
    "invoice.lhdn_rejected": {
        "subject": "LHDN rejected invoice {invoice_number}",
        "body": (
            "MyInvois rejected an invoice you submitted "
            "({invoice_number}). The rejection details are in the "
            "inbox.\n\nOpen the inbox: {inbox_url}\n\n— ZeroKey"
        ),
    },
    "test.ping": {
        "subject": "ZeroKey test email",
        "body": (
            "This is a test email from your ZeroKey platform admin. "
            "If you received this, your SMTP credentials are working.\n\n"
            "— ZeroKey"
        ),
    },
}


def render_email_template(event_key: str, context: dict[str, Any]) -> tuple[str, str] | None:
    """Returns (subject, body) for the event, or None if no template."""
    tpl = _EMAIL_TEMPLATES.get(event_key)
    if tpl is None:
        return None
    safe_ctx: dict[str, str] = {}
    for k, v in context.items():
        safe_ctx[k] = "" if v is None else str(v)
    try:
        return tpl["subject"].format_map(_SafeFormatDict(safe_ctx)), tpl["body"].format_map(
            _SafeFormatDict(safe_ctx)
        )
    except Exception:
        # Template typo? Fall back to the raw template string rather
        # than crashing the dispatcher — better to send a bad email
        # than send no email.
        return tpl["subject"], tpl["body"]


class _SafeFormatDict(dict):
    """Replaces missing keys with empty string instead of KeyError."""

    def __missing__(self, key: str) -> str:
        return ""


def deliver_for_event(
    *,
    organization_id: uuid.UUID | str,
    event_key: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch one event to every member of the org per their preferences.

    Returns a summary ``{recipients_email_queued, no_template, no_recipients}``
    so the caller can log or surface in audit.

    Cross-context: imports identity models under super_admin elevation
    because the caller is typically a service path (Celery task) that
    doesn't have a session-org context. Same pattern the audit chain
    uses for cross-tenant reads.
    """
    template = render_email_template(event_key, context)
    if template is None:
        return {
            "recipients_email_queued": 0,
            "no_template": True,
            "no_recipients": False,
        }
    subject, body = template

    # Find every active member + their email-channel preference for
    # this event_key. Lazy import to avoid circular at app load.
    from apps.identity.models import (
        NotificationPreference,
        OrganizationMembership,
    )
    from apps.identity.tenancy import super_admin_context

    queued = 0
    with super_admin_context(reason="notifications:fanout"):
        members = list(
            OrganizationMembership.objects.filter(
                organization_id=organization_id, is_active=True
            ).select_related("user")
        )
        prefs_by_user = {
            p.user_id: p
            for p in NotificationPreference.objects.filter(
                organization_id=organization_id,
                user__in=[m.user for m in members],
            )
        }

    for membership in members:
        user = membership.user
        prefs = prefs_by_user.get(user.id)
        # Default = on if no preferences row exists yet (matches the
        # auto-materialise contract in Slice 47).
        wants_email = True
        if prefs is not None and isinstance(prefs.preferences, dict):
            event_prefs = prefs.preferences.get(event_key, {})
            wants_email = event_prefs.get("email", True)

        if not wants_email:
            continue

        # Queue delivery. Use ``.delay()`` so failures don't block
        # the producing request; the task module audits success +
        # failure independently.
        from .tasks import send_email_task

        send_email_task.delay(
            to=user.email,
            subject=subject,
            body=body,
            organization_id=str(organization_id),
            event_key=event_key,
        )
        queued += 1

    return {
        "recipients_email_queued": queued,
        "no_template": False,
        "no_recipients": queued == 0,
    }


def send_test_email(*, to: str, actor_user_id: uuid.UUID | str | None = None) -> dict[str, Any]:
    """Synchronous ``test.ping`` email — used by the admin "send test"
    button. Bypasses preferences (the admin is verifying SMTP
    works, not asking the recipient).
    """
    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event

    from .email import send_email

    template = render_email_template("test.ping", {})
    assert template is not None
    subject, body = template

    result = send_email(to=to, subject=subject, body=body)

    record_event(
        action_type="notifications.email.test_sent"
        if result.ok
        else "notifications.email.test_failed",
        actor_type=AuditEvent.ActorType.USER if actor_user_id else AuditEvent.ActorType.SERVICE,
        actor_id=str(actor_user_id) if actor_user_id else "notifications.test",
        organization_id=None,
        affected_entity_type="EmailDelivery",
        affected_entity_id="",
        payload={"ok": bool(result.ok), "detail": result.detail[:120]},
    )
    return {
        "ok": result.ok,
        "detail": result.detail,
        "duration_ms": result.duration_ms,
    }
