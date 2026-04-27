"""Service-layer interface for the identity context.

Anything outside this app that needs to read or mutate identity data calls a
function in this module. Cross-context model imports are forbidden.

Audit events are emitted from this layer (not from views or signals) so that
every mutation, regardless of origin, produces a record. The chain hashing is
a side effect that callers do not need to think about.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from django.db import transaction

from apps.audit.models import AuditEvent
from apps.audit.services import record_event

from .models import Organization, OrganizationMembership, Role, User
from .tenancy import set_tenant


class RegistrationError(Exception):
    """Raised when registration cannot proceed (duplicate email/TIN, missing role)."""


@dataclass(frozen=True)
class RegistrationResult:
    user: User
    organization: Organization
    membership: OrganizationMembership


@transaction.atomic
def register_owner(
    *,
    email: str,
    password: str,
    organization_legal_name: str,
    organization_tin: str,
    contact_email: str,
) -> RegistrationResult:
    """Atomically create a User, Organization and Owner Membership.

    Audit events emitted, in order:
      - ``identity.user.registered``
      - ``identity.organization.created``
      - ``identity.membership.created``

    All three live inside the same DB transaction; on rollback no events are
    written and the chain is unaffected.
    """
    if User.objects.filter(email__iexact=email).exists():
        raise RegistrationError(f"User with email {email!r} already exists.")
    if Organization.objects.filter(tin=organization_tin).exists():
        raise RegistrationError(f"Organization with TIN {organization_tin!r} already exists.")

    try:
        owner_role = Role.objects.get(name=Role.SystemRole.OWNER)
    except Role.DoesNotExist as exc:
        raise RegistrationError(
            "Owner role missing — has the seed migration been applied?"
        ) from exc

    user = User.objects.create_user(email=email, password=password)
    organization = Organization.objects.create(
        legal_name=organization_legal_name,
        tin=organization_tin,
        contact_email=contact_email,
    )

    # Registration is the bootstrap moment for a tenant: the User is created in
    # system scope, then the new Organization establishes a tenant, then the
    # first OrganizationMembership is inserted *within* that tenant's context.
    # We set the tenant variable so the RLS WITH CHECK on identity_membership
    # passes for the membership insert and for any subsequent tenant-scoped
    # write inside this transaction.
    set_tenant(organization.id)

    membership = OrganizationMembership.objects.create(
        user=user,
        organization=organization,
        role=owner_role,
    )

    record_event(
        action_type="identity.user.registered",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(user.id),
        organization_id=str(organization.id),
        affected_entity_type="User",
        affected_entity_id=str(user.id),
        payload={"email": user.email},
    )
    record_event(
        action_type="identity.organization.created",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(user.id),
        organization_id=str(organization.id),
        affected_entity_type="Organization",
        affected_entity_id=str(organization.id),
        payload={
            "legal_name": organization.legal_name,
            "tin": organization.tin,
        },
    )
    record_event(
        action_type="identity.membership.created",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(user.id),
        organization_id=str(organization.id),
        affected_entity_type="OrganizationMembership",
        affected_entity_id=str(membership.id),
        payload={"user_id": str(user.id), "role": owner_role.name},
    )

    return RegistrationResult(user=user, organization=organization, membership=membership)


def memberships_for(user: User) -> list[OrganizationMembership]:
    """Active memberships for ``user``, eager-loaded with organization + role."""
    return list(
        OrganizationMembership.objects.filter(user=user, is_active=True)
        .select_related("organization", "role")
        .order_by("organization__legal_name")
    )


def can_user_act_for_organization(user: User, organization_id: uuid.UUID | str) -> bool:
    """True if ``user`` has an active membership in ``organization_id``."""
    return OrganizationMembership.objects.filter(
        user=user,
        organization_id=organization_id,
        is_active=True,
    ).exists()
