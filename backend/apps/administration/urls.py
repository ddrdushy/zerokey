"""Platform-administration URL routes.

Mounted at ``/api/v1/admin/`` from the project urls. The ``admin/``
prefix in the URL is intentionally distinct from Django's built-in
``/admin/`` (which is the framework's auto-generated model admin) —
the project urls put Django's admin at a different path so this
namespace can be the customer-facing platform-admin surface.
"""

from __future__ import annotations

from django.urls import path

from . import views

app_name = "administration"

urlpatterns = [
    path("me/", views.admin_me, name="me"),
    path("audit/events/", views.platform_audit_events, name="platform-audit-events"),
    path(
        "audit/action-types/",
        views.platform_action_types,
        name="platform-action-types",
    ),
    path("tenants/", views.platform_tenants, name="platform-tenants"),
]
