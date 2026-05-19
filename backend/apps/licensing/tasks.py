"""Background tasks for the licensing app.

Phase 6 of DESKTOP_PIVOT_PLAN.md. Two jobs:

  - ``send_renewal_reminders`` — once a day, find licenses expiring
    in {30, 7, 1} days and email the owner. Idempotent: we record
    the reminder in the audit log and dedupe by (license, window) so
    re-running the same day is a no-op.
  - ``flip_expired_licenses`` — once a day, sweep ACTIVE licenses
    past their expires_at and flip status to EXPIRED. The validate /
    heartbeat paths already do this on-read, but the sweep makes the
    super admin inventory accurate without waiting for a heartbeat.

Wire-up: Celery beat in zerokey/celery.py invokes both at 08:00 MYT
daily. The Celery decorator is the standard one used elsewhere in
the codebase; if Celery isn't running these jobs simply never fire —
the desktop's own logic catches expiry on the next heartbeat anyway.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import record_event

from .models import License

logger = logging.getLogger(__name__)


# Days-out windows we send reminders for. Each window fires at most
# once per license (deduped via audit log).
REMINDER_WINDOWS_DAYS: tuple[int, ...] = (30, 7, 1)


@shared_task(name="apps.licensing.send_renewal_reminders")
def send_renewal_reminders() -> dict:
    """Email the license owner when expiry crosses a reminder window."""
    now = timezone.now()
    sent = 0
    skipped = 0

    for window_days in REMINDER_WINDOWS_DAYS:
        target_start = now + timedelta(days=window_days - 1)
        target_end = now + timedelta(days=window_days)
        licenses = (
            License.objects.filter(
                status=License.Status.ACTIVE,
                expires_at__gte=target_start,
                expires_at__lt=target_end,
            )
            .select_related("owner_user")
        )
        for lic in licenses:
            if _already_reminded(lic.id, window_days):
                skipped += 1
                continue
            _send_one(lic, window_days)
            record_event(
                action_type="licensing.renewal_reminder.sent",
                actor_type=AuditEvent.ActorType.SERVICE,
                actor_id="licensing.tasks",
                affected_entity_type="License",
                affected_entity_id=str(lic.id),
                payload={
                    "window_days": window_days,
                    "expires_at": lic.expires_at.isoformat(),
                    "owner_email": lic.owner_user.email,
                    "organization_tin": lic.organization_tin,
                },
            )
            sent += 1

    logger.info("licensing.renewal_reminders.swept sent=%d skipped=%d", sent, skipped)
    return {"sent": sent, "skipped": skipped}


def _already_reminded(license_id, window_days: int) -> bool:
    """True if we've audited a reminder for this (license, window) before.

    Reminder windows don't overlap calendar-wise, but a re-run on the
    same day could double-fire without this guard.
    """
    return AuditEvent.objects.filter(
        action_type="licensing.renewal_reminder.sent",
        affected_entity_type="License",
        affected_entity_id=str(license_id),
        payload__window_days=window_days,
    ).exists()


def _send_one(lic, window_days: int) -> None:
    """Send the renewal email. Uses the cloud's existing notifications
    pipeline (the SMTP relay configured in zerokey/settings/prod)."""
    # Lazy import — apps.notifications is loaded on the desktop too,
    # but the email sender there has no SMTP, so it would no-op.
    # In the cloud Celery worker it sends via Postfix→O365.
    try:
        from apps.notifications.services import send_transactional_email
    except ImportError:
        logger.warning("licensing.renewal_reminder.no_notifications_module")
        return

    subject = _subject_for_window(window_days)
    body_text = _body_for(lic, window_days)
    send_transactional_email(
        to_email=lic.owner_user.email,
        subject=subject,
        body_text=body_text,
        category="licensing.renewal_reminder",
    )


def _subject_for_window(window_days: int) -> str:
    if window_days == 30:
        return "Your ZeroKey license expires in 30 days"
    if window_days == 7:
        return "Your ZeroKey license expires in 7 days"
    return "Your ZeroKey license expires tomorrow"


def _body_for(lic, window_days: int) -> str:
    expires = lic.expires_at.strftime("%d %B %Y")
    return (
        f"Hi,\n\n"
        f"Your ZeroKey license for {lic.organization_legal_name} (TIN {lic.organization_tin}) "
        f"expires on {expires} — that's in {window_days} day{'s' if window_days != 1 else ''}.\n\n"
        f"After expiry your desktop drops to read-only mode (you keep "
        f"viewing your invoices but can't sign or submit new ones until you renew).\n\n"
        f"Renew at https://zerokey.symprio.com/dashboard/billing\n\n"
        f"— Symprio\n"
    )


@shared_task(name="apps.licensing.flip_expired_licenses")
def flip_expired_licenses() -> dict:
    """Sweep ACTIVE licenses past expires_at to status=EXPIRED."""
    now = timezone.now()
    affected = License.objects.filter(
        status=License.Status.ACTIVE, expires_at__lt=now
    ).update(status=License.Status.EXPIRED)
    if affected:
        logger.info("licensing.flip_expired_licenses.swept count=%d", affected)
    return {"flipped": affected}
