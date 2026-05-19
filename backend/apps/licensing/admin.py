"""Django admin registration for License / LicenseHeartbeat.

Used by the operator at ``/django-admin/`` for emergency reads when the
custom super-admin UI isn't available (e.g. during incidents). The
canonical operator UX is the Next.js super admin pages — those go
through the REST API, which goes through the service layer, which
emits audit events. Don't make destructive changes here.
"""

from __future__ import annotations

from django.contrib import admin

from .models import License, LicenseHeartbeat


@admin.register(License)
class LicenseAdmin(admin.ModelAdmin):
    list_display = (
        "organization_legal_name",
        "organization_tin",
        "plan",
        "status",
        "expires_at",
        "last_heartbeat_at",
    )
    list_filter = ("status", "plan")
    search_fields = ("organization_legal_name", "organization_tin", "owner_user__email")
    readonly_fields = (
        "id",
        "key_hash",
        "issued_at",
        "bound_at",
        "last_heartbeat_at",
        "last_heartbeat_ip",
        "last_desktop_version",
        "revoked_at",
        "created_at",
        "updated_at",
    )


@admin.register(LicenseHeartbeat)
class LicenseHeartbeatAdmin(admin.ModelAdmin):
    list_display = ("at", "license", "event_type", "result", "ip", "desktop_version")
    list_filter = ("event_type", "result")
    search_fields = ("license__organization_tin", "ip")
    readonly_fields = tuple(
        f.name for f in LicenseHeartbeat._meta.get_fields() if hasattr(f, "name")
    )
