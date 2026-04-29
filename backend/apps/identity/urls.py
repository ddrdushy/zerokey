"""URL routes for the identity context.

Phase 1 surface:
  POST  /register                — create user + organization + owner membership
  POST  /login                   — session login
  POST  /logout                  — session logout
  GET   /me                      — current user, memberships, active org
  POST  /switch-organization     — switch active org for users with multiple memberships
  GET   /ping                    — placeholder healthcheck
"""

from django.urls import path

from . import views

app_name = "identity"

urlpatterns = [
    path("ping/", views.ping, name="ping"),
    path("csrf/", views.csrf, name="csrf"),
    path("register/", views.register, name="register"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("me/", views.me, name="me"),
    path("switch-organization/", views.switch_organization, name="switch-organization"),
    path("organization/", views.organization_detail, name="organization-detail"),
    path(
        "organization/members/",
        views.organization_members,
        name="organization-members",
    ),
    path(
        "organization/members/<uuid:membership_id>/",
        views.patch_organization_member,
        name="organization-member-patch",
    ),
    path(
        "organization/api-keys/",
        views.organization_api_keys,
        name="organization-api-keys",
    ),
    path(
        "organization/api-keys/<uuid:api_key_id>/",
        views.revoke_organization_api_key,
        name="organization-api-key-revoke",
    ),
    path(
        "organization/notification-preferences/",
        views.notification_preferences,
        name="notification-preferences",
    ),
    # Slice 56 — invitations
    path(
        "organization/invitations/",
        views.organization_invitations,
        name="organization-invitations",
    ),
    path(
        "organization/invitations/<uuid:invitation_id>/",
        views.revoke_organization_invitation,
        name="organization-invitation-revoke",
    ),
    path(
        "invitations/accept/",
        views.accept_invitation_view,
        name="invitation-accept",
    ),
    path(
        "invitations/preview/",
        views.preview_invitation_view,
        name="invitation-preview",
    ),
    # Slice 57 — per-org integrations (sandbox/prod toggle + test)
    path(
        "organization/integrations/",
        views.organization_integrations,
        name="organization-integrations",
    ),
    path(
        "organization/integrations/<str:integration_key>/credentials/",
        views.organization_integration_credentials,
        name="organization-integration-credentials",
    ),
    path(
        "organization/integrations/<str:integration_key>/active-environment/",
        views.organization_integration_active_environment,
        name="organization-integration-active-environment",
    ),
    path(
        "organization/integrations/<str:integration_key>/test/",
        views.organization_integration_test,
        name="organization-integration-test",
    ),
]
