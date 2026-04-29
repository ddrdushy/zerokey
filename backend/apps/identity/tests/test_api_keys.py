"""Tests for the customer-side API keys surface (Slice 46)."""

from __future__ import annotations

import hashlib
import json

import pytest
from django.test import Client

from apps.audit.models import AuditEvent
from apps.identity.api_keys import _hash, create_api_key
from apps.identity.models import (
    APIKey,
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
def org_user(seeded) -> tuple[Organization, User]:
    org = Organization.objects.create(
        legal_name="Acme", tin="C10000000001", contact_email="ops@acme"
    )
    user = User.objects.create_user(email="o@a.test", password="x")
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name="owner")
    )
    return org, user


def _client(org_user) -> Client:
    org, user = org_user
    client = Client()
    client.force_login(user)
    session = client.session
    session["organization_id"] = str(org.id)
    session.save()
    return client


@pytest.mark.django_db
class TestCreateAPIKey:
    def test_unauthenticated_rejected(self) -> None:
        response = Client().post(
            "/api/v1/identity/organization/api-keys/",
            data=json.dumps({"label": "x"}),
            content_type="application/json",
        )
        assert response.status_code in (401, 403)

    def test_create_returns_plaintext_once(self, org_user) -> None:
        org, user = org_user
        client = _client(org_user)
        response = client.post(
            "/api/v1/identity/organization/api-keys/",
            data=json.dumps({"label": "ci-pipeline"}),
            content_type="application/json",
        )
        assert response.status_code == 201
        body = response.json()
        plaintext = body["plaintext"]
        assert plaintext.startswith("zk_live_")
        assert len(plaintext) > 20  # random body present
        prefix = body["key_prefix"]
        assert prefix == plaintext[: len(prefix)]

        # Row exists with the hash; plaintext is NOT stored.
        row = APIKey.objects.get(id=body["id"])
        assert row.label == "ci-pipeline"
        assert row.key_prefix == prefix
        assert row.key_hash == _hash(plaintext)
        assert plaintext not in row.key_hash  # sanity

        # Audit event records label + prefix, never plaintext.
        event = (
            AuditEvent.objects.filter(action_type="identity.api_key.created")
            .order_by("-sequence")
            .first()
        )
        assert event.payload["label"] == "ci-pipeline"
        assert event.payload["key_prefix"] == prefix
        assert plaintext not in json.dumps(event.payload)

    def test_list_does_not_return_plaintext(self, org_user) -> None:
        org, user = org_user
        row, plaintext = create_api_key(organization_id=org.id, label="ci", actor_user=user)
        client = _client(org_user)
        response = client.get("/api/v1/identity/organization/api-keys/")
        assert response.status_code == 200
        body = response.json()
        text = json.dumps(body)
        # Plaintext never reappears in any list response.
        assert plaintext not in text
        # But the prefix does — that's the public identifier.
        assert row.key_prefix in text
        assert "key_hash" not in text  # raw hash also not exposed

    def test_label_required(self, org_user) -> None:
        client = _client(org_user)
        response = client.post(
            "/api/v1/identity/organization/api-keys/",
            data=json.dumps({"label": ""}),
            content_type="application/json",
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestRevoke:
    def test_revoke_flips_is_active(self, org_user) -> None:
        org, user = org_user
        row, _ = create_api_key(organization_id=org.id, label="ci", actor_user=user)
        client = _client(org_user)
        response = client.delete(f"/api/v1/identity/organization/api-keys/{row.id}/")
        assert response.status_code == 200
        row.refresh_from_db()
        assert row.is_active is False
        assert row.revoked_at is not None
        assert row.revoked_by_user_id == user.id

    def test_revoke_emits_audit(self, org_user) -> None:
        org, user = org_user
        row, _ = create_api_key(organization_id=org.id, label="ci", actor_user=user)
        before = AuditEvent.objects.filter(action_type="identity.api_key.revoked").count()
        client = _client(org_user)
        client.delete(f"/api/v1/identity/organization/api-keys/{row.id}/")
        after = AuditEvent.objects.filter(action_type="identity.api_key.revoked").count()
        assert after == before + 1

    def test_revoke_idempotent(self, org_user) -> None:
        org, user = org_user
        row, _ = create_api_key(organization_id=org.id, label="ci", actor_user=user)
        client = _client(org_user)
        client.delete(f"/api/v1/identity/organization/api-keys/{row.id}/")
        # Second revoke is a no-op (200, no extra audit).
        before = AuditEvent.objects.filter(action_type="identity.api_key.revoked").count()
        response = client.delete(f"/api/v1/identity/organization/api-keys/{row.id}/")
        assert response.status_code == 200
        after = AuditEvent.objects.filter(action_type="identity.api_key.revoked").count()
        assert after == before

    def test_revoke_unknown_404(self, org_user) -> None:
        client = _client(org_user)
        response = client.delete(
            "/api/v1/identity/organization/api-keys/00000000-0000-0000-0000-000000000000/"
        )
        assert response.status_code == 404

    def test_cross_org_revoke_404(self, seeded) -> None:
        """Revoking another tenant's key isn't possible — RLS-style isolation."""
        a_org = Organization.objects.create(legal_name="A", tin="C10000000001", contact_email="a@a")
        a_user = User.objects.create_user(email="a@a.test", password="x")
        OrganizationMembership.objects.create(
            user=a_user,
            organization=a_org,
            role=Role.objects.get(name="owner"),
        )
        a_row, _ = create_api_key(organization_id=a_org.id, label="A-key", actor_user=a_user)

        b_org = Organization.objects.create(legal_name="B", tin="C99999999999", contact_email="b@b")
        b_user = User.objects.create_user(email="b@b.test", password="x")
        OrganizationMembership.objects.create(
            user=b_user,
            organization=b_org,
            role=Role.objects.get(name="owner"),
        )
        client = Client()
        client.force_login(b_user)
        session = client.session
        session["organization_id"] = str(b_org.id)
        session.save()

        response = client.delete(f"/api/v1/identity/organization/api-keys/{a_row.id}/")
        assert response.status_code == 404


@pytest.mark.django_db
class TestServiceContract:
    def test_hash_is_deterministic_sha256(self) -> None:
        plaintext = "zk_live_AbCdEf"
        assert _hash(plaintext) == hashlib.sha256(plaintext.encode()).hexdigest()
        assert len(_hash(plaintext)) == 64

    def test_two_creates_produce_different_plaintexts(self, org_user) -> None:
        org, user = org_user
        _, p1 = create_api_key(organization_id=org.id, label="a", actor_user=user)
        _, p2 = create_api_key(organization_id=org.id, label="b", actor_user=user)
        assert p1 != p2
