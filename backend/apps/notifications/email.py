"""SMTP send service.

Reads platform-wide SMTP credentials from
``SystemSetting('email').values`` (Slice 41) and sends one email via
``smtplib``. No new dependencies — Python's stdlib SMTP client is
fine for transactional volume.

Returns an ``EmailDeliveryResult`` describing what happened. Errors
DO NOT raise — the caller (a Celery task) prefers a structured
result so retries and audit can be applied uniformly.
"""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailDeliveryResult:
    ok: bool
    detail: str
    duration_ms: int = 0
    smtp_response_code: int | None = None


class EmailNotConfigured(Exception):
    """Raised when SMTP creds aren't populated and the caller wants a hard fail."""


def _resolve_smtp_config() -> dict[str, Any]:
    """Pull SMTP creds from SystemSetting('email'). Returns dict or {}."""
    # Lazy import to avoid circular: administration imports identity which
    # may import notifications via reverse import chains.
    from apps.administration.services import system_setting

    return {
        "host": system_setting(namespace="email", key="smtp_host", default=""),
        "port": system_setting(namespace="email", key="smtp_port", default=""),
        "user": system_setting(namespace="email", key="smtp_user", default=""),
        "password": system_setting(namespace="email", key="smtp_password", default=""),
        "from_address": system_setting(
            namespace="email", key="from_address", default=""
        ),
        "from_name": system_setting(
            namespace="email", key="from_name", default="ZeroKey"
        ),
        "use_tls": system_setting(
            namespace="email", key="use_tls", default="true"
        ),
    }


def is_email_configured() -> bool:
    """Cheap precheck — every email-needing surface uses this to know
    whether to render a "not configured" notice instead of trying."""
    cfg = _resolve_smtp_config()
    return bool(cfg["host"] and cfg["from_address"])


def send_email(
    *,
    to: str,
    subject: str,
    body: str,
    html_body: str | None = None,
) -> EmailDeliveryResult:
    """Send one transactional email.

    Returns an ``EmailDeliveryResult`` instead of raising on failure.
    Callers (Celery task) decide whether to retry vs mark failed.
    Network / auth errors → ok=False with the smtplib error class
    name in ``detail`` (no message text in case the SMTP server
    echoes credentials in errors).
    """
    import time

    cfg = _resolve_smtp_config()
    if not cfg["host"]:
        return EmailDeliveryResult(
            ok=False,
            detail="SMTP host not configured (set System settings → Email).",
        )
    if not cfg["from_address"]:
        return EmailDeliveryResult(
            ok=False,
            detail="SMTP from_address not configured.",
        )
    if not to or "@" not in to:
        return EmailDeliveryResult(ok=False, detail=f"Invalid recipient: {to!r}")

    try:
        port = int(cfg["port"]) if cfg["port"] else 587
    except ValueError:
        port = 587
    use_tls = str(cfg["use_tls"]).strip().lower() in {"1", "true", "yes", "on"}

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = (
        f"{cfg['from_name']} <{cfg['from_address']}>"
        if cfg["from_name"]
        else cfg["from_address"]
    )
    msg["To"] = to
    msg.set_content(body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    started = time.perf_counter()
    try:
        with smtplib.SMTP(cfg["host"], port, timeout=20) as smtp:
            if use_tls:
                smtp.starttls()
            if cfg["user"] and cfg["password"]:
                smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(msg)
    except smtplib.SMTPException as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        # Don't echo the exception MESSAGE — some SMTP servers include
        # the prompt text which carries credentials. Class name only.
        return EmailDeliveryResult(
            ok=False,
            detail=f"SMTP error: {type(exc).__name__}",
            duration_ms=duration_ms,
            smtp_response_code=getattr(exc, "smtp_code", None),
        )
    except OSError as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        return EmailDeliveryResult(
            ok=False,
            detail=f"Network error: {type(exc).__name__}",
            duration_ms=duration_ms,
        )

    duration_ms = int((time.perf_counter() - started) * 1000)
    return EmailDeliveryResult(ok=True, detail="sent", duration_ms=duration_ms)
