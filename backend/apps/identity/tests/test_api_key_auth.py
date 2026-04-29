"""Tests for API-key authentication (Slice 51).

Closes the loop on Slice 46: customers can mint keys, and now an
``Authorization: Bearer zk_live_…`` header authenticates the request
against the org the key belongs to. Tenant-scoped reads work as if
the user signed into a session, but no Django session is persisted.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.identity.api_keys import create_api_key
from apps.identity.models import APIKey, Organization, OrganizationMembership, Role, User


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org_user_key(seeded) -> tuple[Organization, User, str]:
    org = Organization.objects.create(legal_name="Acme", tin="C10000000001", contact_email="o@a")
    user = User.objects.create_user(email="o@a.test", password="x")
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name="owner")
    )
    _, plaintext = create_api_key(organization_id=org.id, label="ci", actor_user=user)
    return org, user, plaintext


@pytest.mark.django_db
class TestAPIKeyAuth:
    def test_no_header_falls_through(self) -> None:
        """With no Authorization header, request is unauthenticated."""
        response = Client().get("/api/v1/identity/me/")
        assert response.status_code in (401, 403)

    def test_valid_bearer_authenticates(self, org_user_key) -> None:
        org, user, plaintext = org_user_key
        response = Client().get(
            "/api/v1/identity/me/",
            HTTP_AUTHORIZATION=f"Bearer {plaintext}",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["email"] == user.email
        assert body["active_organization_id"] == str(org.id)

    def test_invalid_bearer_401(self, org_user_key) -> None:
        # Wrong plaintext but with the right shape.
        response = Client().get(
            "/api/v1/identity/me/",
            HTTP_AUTHORIZATION="Bearer zk_live_TotallyFakeWrongValueXxxxxxxxxxxxxxxxxxxxxxxxxx",
        )
        assert response.status_code in (401, 403)

    def test_revoked_key_rejected(self, org_user_key) -> None:
        org, user, plaintext = org_user_key
        # Revoke the key, then try to use it.
        APIKey.objects.filter(organization_id=org.id).update(is_active=False)
        response = Client().get(
            "/api/v1/identity/me/",
            HTTP_AUTHORIZATION=f"Bearer {plaintext}",
        )
        assert response.status_code in (401, 403)

    def test_non_bearer_token_falls_through_to_session(self, org_user_key) -> None:
        """A bearer that doesn't start with zk_live_ should fall
        through to session auth (which has none) → 401, not blow up
        with 500."""
        response = Client().get(
            "/api/v1/identity/me/",
            HTTP_AUTHORIZATION="Bearer some-other-jwt.like.thing",
        )
        assert response.status_code in (401, 403)

    def test_last_used_at_updated(self, org_user_key) -> None:
        """Successful auth populates ``last_used_at`` on the key row."""
        org, _, plaintext = org_user_key
        before = APIKey.objects.get(organization_id=org.id).last_used_at
        assert before is None
        Client().get(
            "/api/v1/identity/me/",
            HTTP_AUTHORIZATION=f"Bearer {plaintext}",
        )
        after = APIKey.objects.get(organization_id=org.id).last_used_at
        assert after is not None

    def test_tenant_scoped_query_works_under_api_key_auth(self, org_user_key) -> None:
        """Tenant-scoped endpoint resolves correctly when authenticated
        via API key — proves the session-org pointer is being set so
        the middleware activates RLS."""
        org, _, plaintext = org_user_key
        response = Client().get(
            "/api/v1/identity/organization/members/",
            HTTP_AUTHORIZATION=f"Bearer {plaintext}",
        )
        assert response.status_code == 200
        results = response.json()["results"]
        # Should see the seeded membership, not zero rows.
        assert len(results) == 1


@pytest.mark.django_db
class TestAPIKeyAuthIsolation:
    def test_key_only_authorises_its_own_org(self, seeded) -> None:
        """A key for org A cannot query org B's data even if B is
        the user's other org."""
        a_org = Organization.objects.create(legal_name="A", tin="C10000000001", contact_email="a")
        b_org = Organization.objects.create(legal_name="B", tin="C99999999999", contact_email="b")
        u = User.objects.create_user(email="dual@x", password="x")
        OrganizationMembership.objects.create(
            user=u, organization=a_org, role=Role.objects.get(name="owner")
        )
        OrganizationMembership.objects.create(
            user=u, organization=b_org, role=Role.objects.get(name="owner")
        )
        # Mint key for org A.
        _, plaintext_a = create_api_key(organization_id=a_org.id, label="a-key", actor_user=u)
        # /me/ should report A as active because the key is org A's.
        response = Client().get(
            "/api/v1/identity/me/",
            HTTP_AUTHORIZATION=f"Bearer {plaintext_a}",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["active_organization_id"] == str(a_org.id)
