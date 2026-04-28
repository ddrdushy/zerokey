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
]
