"""Notifications app config — outbound delivery (email, future push/SMS).

This app is purely service-and-task; no models. The persistence
layer lives in ``apps.identity`` (NotificationPreference) and
``apps.audit`` (delivery is audited via the regular chain). The app
exists so the cross-context import boundary stays clean — every
caller that wants to deliver a notification goes through
``apps.notifications.services.deliver_for_event(...)``.
"""

from __future__ import annotations

from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.notifications"
    verbose_name = "Notifications"
