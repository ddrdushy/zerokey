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
    path("overview/", views.platform_overview, name="platform-overview"),
    path("audit/events/", views.platform_audit_events, name="platform-audit-events"),
    path(
        "audit/action-types/",
        views.platform_action_types,
        name="platform-action-types",
    ),
    path("tenants/", views.platform_tenants, name="platform-tenants"),
    path(
        "tenants/<uuid:organization_id>/",
        views.platform_tenant_detail,
        name="platform-tenant-detail",
    ),
    path(
        "tenants/<uuid:organization_id>/edit/",
        views.admin_update_tenant,
        name="admin-update-tenant",
    ),
    path(
        "memberships/<uuid:membership_id>/",
        views.admin_update_membership,
        name="admin-update-membership",
    ),
    path(
        "tenants/<uuid:organization_id>/impersonate/",
        views.admin_start_impersonation,
        name="admin-start-impersonation",
    ),
    path(
        "impersonation/end/",
        views.admin_end_impersonation,
        name="admin-end-impersonation",
    ),
    path(
        "system-settings/",
        views.admin_list_system_settings,
        name="admin-list-system-settings",
    ),
    path(
        "system-settings/email/test/",
        views.admin_test_email,
        name="admin-test-email",
    ),
    path(
        "system-settings/<slug:namespace>/",
        views.admin_update_system_setting,
        name="admin-update-system-setting",
    ),
    path("engines/", views.admin_list_engines, name="admin-list-engines"),
    path(
        "engines/<uuid:engine_id>/",
        views.admin_update_engine,
        name="admin-update-engine",
    ),
    # --- Slice 99: plans + flags + support tools + routing + health ---
    path("plans/", views.admin_list_plans, name="admin-list-plans"),
    path(
        "plans/<uuid:plan_id>/revise/",
        views.admin_revise_plan,
        name="admin-revise-plan",
    ),
    path(
        "feature-flags/",
        views.admin_list_feature_flags,
        name="admin-list-feature-flags",
    ),
    path(
        "feature-flags/<slug:slug>/",
        views.admin_update_feature_flag,
        name="admin-update-feature-flag",
    ),
    path(
        "tenants/<uuid:organization_id>/feature-flags/",
        views.admin_list_org_overrides,
        name="admin-list-org-overrides",
    ),
    path(
        "tenants/<uuid:organization_id>/feature-flags/<slug:slug>/",
        views.admin_set_feature_flag_override,
        name="admin-set-feature-flag-override",
    ),
    path(
        "tenants/<uuid:organization_id>/feature-flags/<slug:slug>/clear/",
        views.admin_clear_feature_flag_override,
        name="admin-clear-feature-flag-override",
    ),
    path(
        "tenants/<uuid:organization_id>/assign-plan/",
        views.admin_assign_plan,
        name="admin-assign-plan",
    ),
    path(
        "tenants/<uuid:organization_id>/waive-overage/",
        views.admin_waive_overage,
        name="admin-waive-overage",
    ),
    path(
        "users/<uuid:user_id>/reset-2fa/",
        views.admin_reset_2fa,
        name="admin-reset-2fa",
    ),
    path(
        "invoices/<uuid:invoice_id>/retry/",
        views.admin_retry_invoice,
        name="admin-retry-invoice",
    ),
    path(
        "routing-rules/",
        views.admin_list_routing_rules,
        name="admin-list-routing-rules",
    ),
    path(
        "routing-rules/<uuid:rule_id>/",
        views.admin_update_routing_rule,
        name="admin-update-routing-rule",
    ),
    path("health/", views.admin_system_health, name="admin-system-health"),
]
