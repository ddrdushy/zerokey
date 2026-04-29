"""Tests for membership invitations (Slice 56)."""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import Client
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.identity.invitations import (
    INVITATION_TTL_DAYS,
    InvitationError,
    accept_invitation,
    create_invitation,
    revoke_invitation,
)
from apps.identity.models import (
    MembershipInvitation,
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
def org_owner(seeded) -> tuple[Organization, User]:
    org = Organization.objects.create(
        legal_name="Acme Sdn Bhd",
        tin="C10000000001",
        contact_email="o@acme.example",
    )
    user = User.objects.create_user(
        email="owner@acme.example", password="long-enough-password"
    )
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name="owner")
    )
    return org, user


@pytest.fixture
def authed_owner(org_owner) -> tuple[Client, Organization, User]:
    org, user = org_owner
    client = Client()
    client.force_login(user)
    session = client.session
    session["organization_id"] = str(org.id)
    session.save()
    return client, org, user


@pytest.mark.django_db
class TestCreateInvitation:
    def test_creates_pending_row(self, org_owner) -> None:
        org, user = org_owner
        invitation, plaintext = create_invitation(
            organization_id=org.id,
            email="newhire@acme.example",
            role_name="viewer",
            actor_user_id=user.id,
        )
        assert invitation.status == "pending"
        assert invitation.role.name == "viewer"
        assert invitation.expires_at > timezone.now()
        assert plaintext  # non-empty plaintext token returned

    def test_plaintext_never_persists(self, org_owner) -> None:
        org, user = org_owner
        invitation, plaintext = create_invitation(
            organization_id=org.id,
            email="x@y.com",
            role_name="viewer",
            actor_user_id=user.id,
        )
        # Plaintext token must NOT appear on the row.
        assert plaintext not in invitation.token_hash
        # Hash is sha256 hex (64 chars).
        assert len(invitation.token_hash) == 64

    def test_audit_email_masked(self, org_owner) -> None:
        org, user = org_owner
        create_invitation(
            organization_id=org.id,
            email="distinctivename@acme.example",
            role_name="viewer",
            actor_user_id=user.id,
        )
        event = (
            AuditEvent.objects.filter(action_type="identity.invitation.created")
            .order_by("-sequence")
            .first()
        )
        assert event is not None
        # Email is masked in the audit payload — full address must NOT
        # appear in the chain (PII-clean).
        payload_text = json.dumps(event.payload)
        assert "distinctivename" not in payload_text
        assert event.payload["email_masked"].endswith("@acme.example")

    def test_invalid_email_rejected(self, org_owner) -> None:
        org, user = org_owner
        with pytest.raises(InvitationError, match="valid email"):
            create_invitation(
                organization_id=org.id,
                email="not-an-email",
                role_name="viewer",
                actor_user_id=user.id,
            )

    def test_unknown_role_rejected(self, org_owner) -> None:
        org, user = org_owner
        with pytest.raises(InvitationError, match="role"):
            create_invitation(
                organization_id=org.id,
                email="x@y.com",
                role_name="evil-overlord",
                actor_user_id=user.id,
            )

    def test_existing_member_rejected(self, org_owner) -> None:
        org, user = org_owner
        with pytest.raises(InvitationError, match="already an active"):
            create_invitation(
                organization_id=org.id,
                email=user.email,
                role_name="admin",
                actor_user_id=user.id,
            )

    def test_duplicate_pending_rejected(self, org_owner) -> None:
        org, user = org_owner
        create_invitation(
            organization_id=org.id,
            email="x@y.com",
            role_name="viewer",
            actor_user_id=user.id,
        )
        with pytest.raises(InvitationError, match="pending"):
            create_invitation(
                organization_id=org.id,
                email="x@y.com",
                role_name="viewer",
                actor_user_id=user.id,
            )


@pytest.mark.django_db
class TestAcceptInvitation:
    def test_creates_membership(self, org_owner) -> None:
        org, user = org_owner
        _, plaintext = create_invitation(
            organization_id=org.id,
            email="newhire@acme.example",
            role_name="submitter",
            actor_user_id=user.id,
        )
        # Invitee user must already exist (sign-up + accept lands as
        # a follow-up; for now, assume the user signed up).
        invitee = User.objects.create_user(
            email="newhire@acme.example", password="long-enough-password"
        )
        membership = accept_invitation(
            token=plaintext, accepting_user_id=invitee.id
        )
        assert membership.organization_id == org.id
        assert membership.role.name == "submitter"
        assert membership.user_id == invitee.id

    def test_invalid_token_rejected(self, org_owner) -> None:
        invitee = User.objects.create_user(
            email="x@y.com", password="long-enough-password"
        )
        with pytest.raises(InvitationError, match="not valid"):
            accept_invitation(
                token="not-a-real-token", accepting_user_id=invitee.id
            )

    def test_email_mismatch_rejected(self, org_owner) -> None:
        org, user = org_owner
        _, plaintext = create_invitation(
            organization_id=org.id,
            email="alice@acme.example",
            role_name="viewer",
            actor_user_id=user.id,
        )
        # Sign in as a DIFFERENT user.
        bob = User.objects.create_user(
            email="bob@acme.example", password="long-enough-password"
        )
        with pytest.raises(InvitationError, match="different email"):
            accept_invitation(token=plaintext, accepting_user_id=bob.id)

    def test_expired_invitation_rejected(self, org_owner) -> None:
        org, user = org_owner
        invitation, plaintext = create_invitation(
            organization_id=org.id,
            email="x@y.com",
            role_name="viewer",
            actor_user_id=user.id,
        )
        # Time-travel: backdate expiry.
        invitation.expires_at = timezone.now() - timedelta(seconds=1)
        invitation.save(update_fields=["expires_at"])

        invitee = User.objects.create_user(
            email="x@y.com", password="long-enough-password"
        )
        with pytest.raises(InvitationError, match="expired"):
            accept_invitation(token=plaintext, accepting_user_id=invitee.id)

        invitation.refresh_from_db()
        assert invitation.status == "expired"

    def test_double_accept_rejected(self, org_owner) -> None:
        org, user = org_owner
        _, plaintext = create_invitation(
            organization_id=org.id,
            email="x@y.com",
            role_name="viewer",
            actor_user_id=user.id,
        )
        invitee = User.objects.create_user(
            email="x@y.com", password="long-enough-password"
        )
        accept_invitation(token=plaintext, accepting_user_id=invitee.id)
        with pytest.raises(InvitationError, match="cannot accept"):
            accept_invitation(token=plaintext, accepting_user_id=invitee.id)


@pytest.mark.django_db
class TestRevoke:
    def test_revoke_flips_status(self, org_owner) -> None:
        org, user = org_owner
        invitation, _ = create_invitation(
            organization_id=org.id,
            email="x@y.com",
            role_name="viewer",
            actor_user_id=user.id,
        )
        revoked = revoke_invitation(
            organization_id=org.id,
            invitation_id=invitation.id,
            actor_user_id=user.id,
        )
        assert revoked.status == "revoked"
        assert revoked.revoked_at is not None

    def test_revoke_idempotent(self, org_owner) -> None:
        org, user = org_owner
        invitation, _ = create_invitation(
            organization_id=org.id,
            email="x@y.com",
            role_name="viewer",
            actor_user_id=user.id,
        )
        revoke_invitation(
            organization_id=org.id,
            invitation_id=invitation.id,
            actor_user_id=user.id,
        )
        # Second call returns the same row, no error.
        again = revoke_invitation(
            organization_id=org.id,
            invitation_id=invitation.id,
            actor_user_id=user.id,
        )
        assert again.status == "revoked"


@pytest.mark.django_db
class TestEndpoints:
    def test_owner_creates_via_endpoint(self, authed_owner) -> None:
        client, _, _ = authed_owner
        response = client.post(
            "/api/v1/identity/organization/invitations/",
            data=json.dumps(
                {"email": "newhire@acme.example", "role_name": "viewer"}
            ),
            content_type="application/json",
        )
        assert response.status_code == 201
        body = response.json()
        # Plaintext token returned ONCE.
        assert body["plaintext_token"]
        assert "/accept-invitation?token=" in body["invitation_url"]

    def test_non_admin_403(self, seeded) -> None:
        org = Organization.objects.create(
            legal_name="X", tin="C10000000002", contact_email="o@x"
        )
        viewer = User.objects.create_user(
            email="viewer@x", password="long-enough-password"
        )
        OrganizationMembership.objects.create(
            user=viewer, organization=org, role=Role.objects.get(name="viewer")
        )
        client = Client()
        client.force_login(viewer)
        session = client.session
        session["organization_id"] = str(org.id)
        session.save()

        response = client.post(
            "/api/v1/identity/organization/invitations/",
            data=json.dumps({"email": "x@y.com", "role_name": "viewer"}),
            content_type="application/json",
        )
        assert response.status_code == 403

    def test_list_returns_pending(self, authed_owner) -> None:
        client, org, user = authed_owner
        create_invitation(
            organization_id=org.id,
            email="x@y.com",
            role_name="viewer",
            actor_user_id=user.id,
        )
        response = client.get("/api/v1/identity/organization/invitations/")
        assert response.status_code == 200
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["status"] == "pending"

    def test_revoke_endpoint(self, authed_owner) -> None:
        client, org, user = authed_owner
        invitation, _ = create_invitation(
            organization_id=org.id,
            email="x@y.com",
            role_name="viewer",
            actor_user_id=user.id,
        )
        response = client.delete(
            f"/api/v1/identity/organization/invitations/{invitation.id}/"
        )
        assert response.status_code == 200
        assert response.json()["status"] == "revoked"

    def test_preview_returns_org_name(self, authed_owner) -> None:
        client, org, user = authed_owner
        _, plaintext = create_invitation(
            organization_id=org.id,
            email="x@y.com",
            role_name="viewer",
            actor_user_id=user.id,
        )
        # Preview is anonymous-accessible — but we use the authed
        # client here for convenience; the result is the same.
        response = client.post(
            "/api/v1/identity/invitations/preview/",
            data=json.dumps({"token": plaintext}),
            content_type="application/json",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["organization_legal_name"] == org.legal_name
        assert body["role"] == "viewer"

    def test_accept_via_endpoint(self, authed_owner) -> None:
        client, org, user = authed_owner
        _, plaintext = create_invitation(
            organization_id=org.id,
            email="newhire@acme.example",
            role_name="submitter",
            actor_user_id=user.id,
        )
        invitee = User.objects.create_user(
            email="newhire@acme.example", password="long-enough-password"
        )
        invitee_client = Client()
        invitee_client.force_login(invitee)
        response = invitee_client.post(
            "/api/v1/identity/invitations/accept/",
            data=json.dumps({"token": plaintext}),
            content_type="application/json",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["organization_id"] == str(org.id)
        assert body["role"] == "submitter"

    def test_email_send_attempted(self, authed_owner) -> None:
        """Best-effort email send — invite still creates if SMTP down."""
        client, _, _ = authed_owner
        with patch("apps.notifications.email.is_email_configured", return_value=True), \
             patch("apps.notifications.email.send_email") as send_mock:
            response = client.post(
                "/api/v1/identity/organization/invitations/",
                data=json.dumps({"email": "x@y.com", "role_name": "viewer"}),
                content_type="application/json",
            )
        assert response.status_code == 201
        assert send_mock.called

    def test_email_failure_does_not_block_invite(self, authed_owner) -> None:
        client, _, _ = authed_owner
        with patch("apps.notifications.email.is_email_configured", return_value=True), \
             patch(
                 "apps.notifications.email.send_email",
                 side_effect=Exception("smtp down"),
             ):
            response = client.post(
                "/api/v1/identity/organization/invitations/",
                data=json.dumps({"email": "x@y.com", "role_name": "viewer"}),
                content_type="application/json",
            )
        # Invite is created even though email failed.
        assert response.status_code == 201
        assert MembershipInvitation.objects.filter(email="x@y.com").exists()


def test_ttl_constant_sane() -> None:
    """Defensive: TTL should be in days, not seconds."""
    assert 1 <= INVITATION_TTL_DAYS <= 60
