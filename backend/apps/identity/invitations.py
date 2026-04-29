"""Membership invitation service (Slice 56).

Owners + admins invite a future user by email. The invite carries
a one-time token (plaintext shown ONCE in the email link, only the
SHA-256 hash persisted). Recipient clicks the link, signs in (or
signs up if new), and the accept handler creates the
OrganizationMembership row.

Why a separate row from OrganizationMembership rather than creating
the membership in ``inactive`` state at invite time: invitees may
not have a User row yet, and pre-creating one with no password is
a footgun for the rest of the auth path. Modelling pending invites
distinctly is honest about the lifecycle.

Audit:
- ``identity.invitation.created`` — payload includes role + inviter
  + masked email (left-of-@ masked to first char + asterisks). Email
  is arguably PII; masking lets operators correlate invites without
  leaking the address.
- ``identity.invitation.accepted`` — payload: invitation_id, role,
  accepter_user_id.
- ``identity.invitation.revoked`` — payload: invitation_id, reason.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import record_event

from .models import (
    MembershipInvitation,
    Organization,
    OrganizationMembership,
    Role,
    User,
)


# How long an invite stays valid. 14 days is the industry-standard
# default — long enough that "I'll get to it tomorrow" works, short
# enough that an old link in an inbox doesn't enable a stale account
# from a year ago.
INVITATION_TTL_DAYS = 14


class InvitationError(Exception):
    """Raised when an invitation can't be created or accepted."""


def _hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def _mask_email(email: str) -> str:
    """Reduce an email to first-char + asterisks + domain.

    Used in audit payloads so a bad-actor reading the chain can't
    enumerate invitee addresses but operators can still correlate
    "this row is the invite to a@example.com" given context.
    """
    if "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    if not local:
        return f"@{domain}"
    return f"{local[0]}{'*' * max(len(local) - 1, 1)}@{domain}"


@transaction.atomic
def create_invitation(
    *,
    organization_id: uuid.UUID | str,
    email: str,
    role_name: str,
    actor_user_id: uuid.UUID | str,
) -> tuple[MembershipInvitation, str]:
    """Mint an invite, return ``(row, plaintext_token)``.

    Plaintext is embedded in the invite-link URL once; only the hash
    persists. Caller (the view) is responsible for sending the email.
    """
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise InvitationError("Provide a valid email address.")

    try:
        role = Role.objects.get(name=role_name)
    except Role.DoesNotExist as exc:
        raise InvitationError(
            f"Unknown role {role_name!r}. Valid: owner|admin|approver|submitter|viewer"
        ) from exc

    org = Organization.objects.filter(id=organization_id).first()
    if org is None:
        raise InvitationError(f"Organization {organization_id} not found.")

    # If the email is already an active member, refuse — sending an
    # invite to an existing teammate is at best confusing and at worst
    # a phishing pattern (an attacker who knows the org's domain could
    # spam member-looking emails to gather password-reset signal).
    existing_member = OrganizationMembership.objects.filter(
        organization_id=organization_id,
        user__email__iexact=email,
        is_active=True,
    ).exists()
    if existing_member:
        raise InvitationError(
            f"{email} is already an active member of this organization."
        )

    # Refuse duplicate pending invite to the same email.
    duplicate = MembershipInvitation.objects.filter(
        organization_id=organization_id,
        email__iexact=email,
        status=MembershipInvitation.Status.PENDING,
    ).first()
    if duplicate is not None:
        raise InvitationError(
            f"There's already a pending invitation for {email}. "
            f"Revoke it first if you need to re-issue."
        )

    plaintext = secrets.token_urlsafe(32)
    token_hash = _hash_token(plaintext)

    expires_at = timezone.now() + timedelta(days=INVITATION_TTL_DAYS)

    inviter = User.objects.filter(id=actor_user_id).first()
    invitation = MembershipInvitation.objects.create(
        organization_id=organization_id,
        email=email,
        role=role,
        invited_by=inviter,
        token_hash=token_hash,
        expires_at=expires_at,
        status=MembershipInvitation.Status.PENDING,
    )

    record_event(
        action_type="identity.invitation.created",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(organization_id),
        affected_entity_type="MembershipInvitation",
        affected_entity_id=str(invitation.id),
        payload={
            "role": role_name,
            "email_masked": _mask_email(email),
            "expires_at": expires_at.isoformat(),
        },
    )

    return invitation, plaintext


def accept_invitation(
    *, token: str, accepting_user_id: uuid.UUID | str
) -> OrganizationMembership:
    """Match the token (by hash), create the OrganizationMembership.

    NOT wrapped in a single ``@transaction.atomic`` — the expired-
    invitation status flip needs to commit even when the function
    raises. The membership creation block has its own atomic
    boundary internally.
    """
    if not token:
        raise InvitationError("Missing invitation token.")
    token_hash = _hash_token(token)

    user = User.objects.filter(id=accepting_user_id).first()
    if user is None:
        raise InvitationError("Accepting user not found.")

    # Lookup under super-admin elevation: the user accepting the
    # invite has no tenant context yet (they're being added to the
    # org by this very call), so RLS on the invitation table would
    # block the read.
    from .tenancy import super_admin_context

    with super_admin_context(reason="invitations.accept_lookup"):
        invitation = MembershipInvitation.objects.filter(
            token_hash=token_hash
        ).first()

    if invitation is None:
        raise InvitationError("Invitation token is not valid.")

    if invitation.status != MembershipInvitation.Status.PENDING:
        raise InvitationError(
            f"Invitation is {invitation.status} — cannot accept."
        )

    if invitation.expires_at <= timezone.now():
        # Auto-mark expired so future accept attempts surface the
        # state cleanly + the listing reflects reality. Done OUTSIDE
        # any wrapping atomic block of the caller so the status flip
        # commits even though we then raise.
        with super_admin_context(reason="invitations.mark_expired"):
            MembershipInvitation.objects.filter(id=invitation.id).update(
                status=MembershipInvitation.Status.EXPIRED
            )
        raise InvitationError("Invitation has expired.")

    # Email match is intentional: the link could be forwarded but the
    # accepting user must own the invited address. (Open question:
    # do we want to allow "invite a@x.com but b@x.com accepts"? Not
    # today — tightening is conservative.)
    if user.email.lower() != invitation.email.lower():
        raise InvitationError(
            "This invitation was issued for a different email address."
        )

    # Now we're in the success path — wrap the actual writes in atomic
    # so the membership + invitation status flip are all-or-nothing.
    with transaction.atomic(), super_admin_context(
        reason="invitations.create_membership"
    ):
        # Re-fetch under FOR UPDATE for the race guard.
        invitation = (
            MembershipInvitation.objects.select_for_update()
            .filter(id=invitation.id)
            .first()
        )
        if invitation is None or invitation.status != MembershipInvitation.Status.PENDING:
            raise InvitationError("Invitation is no longer pending.")

        membership, created = OrganizationMembership.objects.get_or_create(
            user=user,
            organization_id=invitation.organization_id,
            defaults={
                "role": invitation.role,
                "is_active": True,
                "invited_by": invitation.invited_by,
            },
        )
        if not created and not membership.is_active:
            # Re-activate; e.g. user was removed and re-invited.
            membership.is_active = True
            membership.role = invitation.role
            membership.save(update_fields=["is_active", "role", "joined_date"])

        invitation.status = MembershipInvitation.Status.ACCEPTED
        invitation.accepted_at = timezone.now()
        invitation.accepted_by_user_id = user.id
        invitation.save(
            update_fields=[
                "status",
                "accepted_at",
                "accepted_by_user_id",
                "updated_at",
            ]
        )

    record_event(
        action_type="identity.invitation.accepted",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(user.id),
        organization_id=str(invitation.organization_id),
        affected_entity_type="MembershipInvitation",
        affected_entity_id=str(invitation.id),
        payload={
            "role": invitation.role.name,
            "membership_id": str(membership.id),
        },
    )

    return membership


@transaction.atomic
def revoke_invitation(
    *,
    organization_id: uuid.UUID | str,
    invitation_id: uuid.UUID | str,
    actor_user_id: uuid.UUID | str,
    reason: str = "",
) -> MembershipInvitation:
    """Cancel a pending invitation. Idempotent on already-revoked rows."""
    try:
        invitation = MembershipInvitation.objects.get(
            id=invitation_id, organization_id=organization_id
        )
    except MembershipInvitation.DoesNotExist as exc:
        raise InvitationError(
            f"Invitation {invitation_id} not found in this organization."
        ) from exc

    if invitation.status != MembershipInvitation.Status.PENDING:
        return invitation

    invitation.status = MembershipInvitation.Status.REVOKED
    invitation.revoked_at = timezone.now()
    invitation.revoked_by_user_id = actor_user_id
    invitation.save(
        update_fields=["status", "revoked_at", "revoked_by_user_id", "updated_at"]
    )

    record_event(
        action_type="identity.invitation.revoked",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(organization_id),
        affected_entity_type="MembershipInvitation",
        affected_entity_id=str(invitation.id),
        payload={
            "email_masked": _mask_email(invitation.email),
            "reason": reason[:255],
        },
    )
    return invitation


def list_pending_invitations(
    *, organization_id: uuid.UUID | str
) -> list[dict[str, Any]]:
    """List rows visible in Settings → Members → Pending invites."""
    qs = MembershipInvitation.objects.filter(
        organization_id=organization_id
    ).select_related("role", "invited_by").order_by("-created_at")
    return [_invitation_dict(r) for r in qs]


def _invitation_dict(row: MembershipInvitation) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "email": row.email,
        "role": row.role.name,
        "status": row.status,
        "invited_by_email": row.invited_by.email if row.invited_by else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "accepted_at": row.accepted_at.isoformat() if row.accepted_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
