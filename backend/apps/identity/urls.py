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
    # Slice 89 — TOTP second factor on login.
    path("login/2fa/", views.login_2fa_view, name="login-2fa"),
    # Slice 97 — SSO via OpenID Connect.
    path("sso/initiate/", views.sso_initiate_view, name="sso-initiate"),
    path("sso/callback/", views.sso_callback_view, name="sso-callback"),
    # Owner/Admin-only configuration of the active org's OIDC provider.
    path("sso/provider/", views.sso_provider_view, name="sso-provider"),
    path("logout/", views.logout_view, name="logout"),
    path("me/", views.me, name="me"),
    # Slice 86 — UI preferences (preferred_language for now).
    path("me/preferences/", views.update_preferences, name="me-preferences"),
    # Slice 92 — post-signup onboarding checklist (GET state, POST dismiss).
    path("me/onboarding/", views.onboarding_view, name="me-onboarding"),
    # Slice 89 — TOTP enrollment / disable.
    path("me/2fa/enroll/", views.two_factor_enroll, name="me-2fa-enroll"),
    path("me/2fa/confirm/", views.two_factor_confirm, name="me-2fa-confirm"),
    path("me/2fa/disable/", views.two_factor_disable, name="me-2fa-disable"),
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
    # Slice 59B — LHDN signing certificate
    path(
        "organization/certificate/",
        views.organization_certificate,
        name="organization-certificate",
    ),
    # Slice 99 — feature-flag map for the active org (resolved server-side)
    path(
        "feature-flags/",
        views.feature_flags_view,
        name="feature-flags",
    ),
    # Slice 101 — global search across invoices + customers + audit
    path("search/", views.global_search_view, name="global-search"),
]
