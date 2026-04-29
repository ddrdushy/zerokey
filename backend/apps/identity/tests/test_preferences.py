"""Tests for the UI preferences endpoint (Slice 86)."""

from __future__ import annotations

import json

import pytest
from django.test import Client

from apps.identity.models import (
    Organization,
    OrganizationMembership,
    Role,
    User,
)


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def authed(seeded) -> tuple[Client, User]:
    org = Organization.objects.create(
        legal_name="Acme", tin="C1234567890", contact_email="o@a.example"
    )
    user = User.objects.create_user(email="o@a.example", password="long-enough-password")
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name="owner")
    )
    client = Client()
    client.force_login(user)
    return client, user


@pytest.mark.django_db
class TestUpdatePreferences:
    def test_owner_changes_language(self, authed) -> None:
        client, user = authed
        response = client.patch(
            "/api/v1/identity/me/preferences/",
            data=json.dumps({"preferred_language": "bm-MY"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["preferred_language"] == "bm-MY"
        assert "preferred_language" in body["changed_fields"]

        user.refresh_from_db()
        assert user.preferred_language == "bm-MY"

    def test_unsupported_locale_rejected(self, authed) -> None:
        client, _ = authed
        response = client.patch(
            "/api/v1/identity/me/preferences/",
            data=json.dumps({"preferred_language": "fr-FR"}),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "preferred_language" in response.json()["detail"]

    def test_no_change_when_same_value(self, authed) -> None:
        client, user = authed
        # Already en-MY by default.
        response = client.patch(
            "/api/v1/identity/me/preferences/",
            data=json.dumps({"preferred_language": "en-MY"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["changed_fields"] == []

    def test_unauthenticated_blocked(self, seeded) -> None:
        response = Client().patch(
            "/api/v1/identity/me/preferences/",
            data=json.dumps({"preferred_language": "bm-MY"}),
            content_type="application/json",
        )
        assert response.status_code in (401, 403)

    def test_all_supported_locales_accepted(self, authed) -> None:
        client, _ = authed
        for lang in ("en-MY", "bm-MY", "zh-MY", "ta-MY"):
            response = client.patch(
                "/api/v1/identity/me/preferences/",
                data=json.dumps({"preferred_language": lang}),
                content_type="application/json",
            )
            assert response.status_code == 200, f"failed for {lang}"
