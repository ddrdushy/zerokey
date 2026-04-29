"""Tests for the platform-admin auth gate (Slice 33).

The /api/v1/admin/ namespace is reachable only by users with
``is_staff=True``. Every other authenticated user gets 403; an
unauthenticated request gets 401/403 depending on DRF defaults.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.identity.models import Organization, OrganizationMembership, Role, User


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def customer_user(seeded) -> User:
    """A regular customer user — has a membership but is_staff=False."""
    org = Organization.objects.create(
        legal_name="Acme", tin="C10000000001", contact_email="ops@acme"
    )
    user = User.objects.create_user(email="customer@acme.example", password="long-enough-password")
    OrganizationMembership.objects.create(
        user=user,
        organization=org,
        role=Role.objects.get(name="owner"),
    )
    return user


@pytest.fixture
def staff_user(seeded) -> User:
    """A platform staff member — is_staff=True. Need NOT have an org membership."""
    return User.objects.create_user(
        email="staff@symprio.com",
        password="long-enough-password",
        is_staff=True,
    )


@pytest.mark.django_db
class TestAdminMe:
    def test_unauthenticated_rejected(self) -> None:
        response = Client().get("/api/v1/admin/me/")
        assert response.status_code in (401, 403)

    def test_customer_user_gets_403(self, customer_user) -> None:
        client = Client()
        client.force_login(customer_user)
        response = client.get("/api/v1/admin/me/")
        # Per IsPlatformStaff contract: 403 (not 404) so the frontend
        # can distinguish "not staff" from "endpoint missing".
        assert response.status_code == 403

    def test_staff_user_sees_self(self, staff_user) -> None:
        client = Client()
        client.force_login(staff_user)
        response = client.get("/api/v1/admin/me/")
        assert response.status_code == 200
        body = response.json()
        assert body["email"] == "staff@symprio.com"
        assert body["is_staff"] is True

    def test_staff_user_without_active_org_still_works(self, staff_user) -> None:
        """Platform staff don't need an organization membership.

        The customer-facing endpoints require an active org in session;
        the admin namespace is org-agnostic by design.
        """
        client = Client()
        client.force_login(staff_user)
        response = client.get("/api/v1/admin/me/")
        assert response.status_code == 200
