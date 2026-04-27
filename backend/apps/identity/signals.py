"""Audit-emitting signal handlers for Django auth events.

Every authentication outcome — success, failure, logout — is recorded so the
audit log captures the full session lifecycle. Putting this here (rather than
inside the login view) means every code path that triggers Django auth gets
audited, including ``login()`` calls from tests and management commands.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from apps.audit.models import AuditEvent
from apps.audit.services import record_event


def _client_metadata(request: Any) -> dict[str, str]:
    if request is None:
        return {}
    return {
        "ip": request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", "")),
        "user_agent": request.META.get("HTTP_USER_AGENT", "")[:255],
    }


@receiver(user_logged_in)
def on_user_logged_in(sender, request, user, **kwargs: Any) -> None:
    organization_id = None
    session = getattr(request, "session", None)
    if session is not None:
        organization_id = session.get("organization_id")

    record_event(
        action_type="auth.login_success",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(user.id),
        organization_id=organization_id,
        affected_entity_type="User",
        affected_entity_id=str(user.id),
        payload=_client_metadata(request),
    )


@receiver(user_logged_out)
def on_user_logged_out(sender, request, user, **kwargs: Any) -> None:
    if user is None:
        # Anonymous logout — nothing to record.
        return
    organization_id = None
    session = getattr(request, "session", None)
    if session is not None:
        organization_id = session.get("organization_id")

    record_event(
        action_type="auth.logout",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(user.id),
        organization_id=organization_id,
        affected_entity_type="User",
        affected_entity_id=str(user.id),
        payload=_client_metadata(request),
    )


@receiver(user_login_failed)
def on_user_login_failed(sender, credentials, request=None, **kwargs: Any) -> None:
    # Never log the password (CLAUDE.md). The credentials dict may contain it;
    # we extract only the email for the payload.
    email = (credentials or {}).get("email") or (credentials or {}).get("username") or ""
    record_event(
        action_type="auth.login_failed",
        actor_type=AuditEvent.ActorType.EXTERNAL,
        actor_id="",
        affected_entity_type="User",
        affected_entity_id="",
        payload={"email_attempted": email, **_client_metadata(request)},
    )
