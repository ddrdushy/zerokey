from __future__ import annotations

from django.urls import path

from . import views

app_name = "licensing"

urlpatterns = [
    # Desktop endpoints — unauthenticated.
    path("public-key/", views.public_key_view, name="public-key"),
    path("validate/", views.validate_view, name="validate"),
    path("heartbeat/", views.heartbeat_view, name="heartbeat"),
    # Super admin endpoints.
    path("admin/issue/", views.admin_issue_view, name="admin-issue"),
    path("admin/", views.admin_list_view, name="admin-list"),
    path("admin/<uuid:license_id>/", views.admin_detail_view, name="admin-detail"),
    path(
        "admin/<uuid:license_id>/revoke/",
        views.admin_revoke_view,
        name="admin-revoke",
    ),
    path(
        "admin/<uuid:license_id>/regenerate/",
        views.admin_regenerate_view,
        name="admin-regenerate",
    ),
    path(
        "admin/<uuid:license_id>/renew/",
        views.admin_renew_view,
        name="admin-renew",
    ),
    # Customer self-serve.
    path("me/", views.me_list_view, name="me-list"),
    path(
        "me/<uuid:license_id>/regenerate/",
        views.me_regenerate_view,
        name="me-regenerate",
    ),
]
