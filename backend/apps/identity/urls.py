"""URL routes for the identity context.

Authentication, organizations, memberships, sessions, SSO. Phase 1 is intentionally
a single placeholder endpoint; real routes land as the auth flows are implemented.
"""

from django.urls import path

from . import views

app_name = "identity"

urlpatterns = [
    path("ping/", views.ping, name="ping"),
]
