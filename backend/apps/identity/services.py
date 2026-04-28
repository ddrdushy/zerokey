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
from .tenancy import set_tenant, super_admin_context


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
    """Active memberships for ``user``, eager-loaded with organization + role.

    This query is *fundamentally cross-tenant* — its job is to answer "which
    tenants can this user act for?", which is exactly the question we ask
    *before* a tenant context is set (during login, during /me when the
    session has no active org yet, during organization-switch). RLS on
    ``identity_membership`` would otherwise filter every row out because
    ``app.current_tenant_id`` is unset, leaving the user unable to see
    their own memberships.

    The super-admin elevation here is narrowly scoped to one read query —
    the caller never receives a connection in elevated state.
    """
    with super_admin_context(reason="identity.memberships_for:user_org_lookup"):
        return list(
            OrganizationMembership.objects.filter(user=user, is_active=True)
            .select_related("organization", "role")
            .order_by("organization__legal_name")
        )


# Editable fields on the Organization detail surface. Settings page edits.
# Excluded by design:
#   - tin: LHDN-issued canonical identifier; changing it would invalidate
#     every signed invoice that referenced the old TIN. If a customer's
#     LHDN-issued TIN actually changes, that's a fresh-tenant operation
#     handled by support, not a self-serve edit.
#   - billing_currency / trial_state / subscription_state / certificate_*:
#     system-managed (billing flow / signing service own these).
EDITABLE_ORGANIZATION_FIELDS: frozenset[str] = frozenset(
    {
        "legal_name",
        "sst_number",
        "registered_address",
        "contact_email",
        "contact_phone",
        "language_preference",
        "timezone",
        "logo_url",
    }
)


class OrganizationUpdateError(Exception):
    """Raised when an org update violates the editable-fields allowlist."""


def get_organization(*, organization_id: uuid.UUID | str) -> Organization | None:
    return Organization.objects.filter(id=organization_id).first()


@transaction.atomic
def update_organization(
    *,
    organization_id: uuid.UUID | str,
    updates: dict[str, str],
    actor_user_id: uuid.UUID | str,
) -> Organization:
    """Apply Settings → Organization edits, audit-logged.

    Same shape as the Invoice / CustomerMaster updaters: strict
    allowlist, single audit event, NO values in the audit payload
    (PII).
    """
    unknown = set(updates.keys()) - EDITABLE_ORGANIZATION_FIELDS
    if unknown:
        raise OrganizationUpdateError(
            f"Cannot edit non-editable organization fields: {sorted(unknown)}. "
            f"Editable: {sorted(EDITABLE_ORGANIZATION_FIELDS)}"
        )

    org = Organization.objects.get(id=organization_id)
    changed: list[str] = []
    for field_name, raw_value in updates.items():
        new_value = "" if raw_value is None else str(raw_value)
        if field_name == "legal_name" and not new_value.strip():
            raise OrganizationUpdateError("legal_name cannot be empty.")
        previous = getattr(org, field_name) or ""
        if previous == new_value:
            continue
        setattr(org, field_name, new_value)
        changed.append(field_name)

    if not changed:
        return org

    org.save()
    record_event(
        action_type="identity.organization.updated",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(organization_id),
        affected_entity_type="Organization",
        affected_entity_id=str(organization_id),
        payload={
            # Field names only — values can be PII (legal name, address, etc.).
            "changed_fields": sorted(changed),
        },
    )
    return org


def can_user_act_for_organization(user: User, organization_id: uuid.UUID | str) -> bool:
    """True if ``user`` has an active membership in ``organization_id``.

    Same cross-tenant rationale as ``memberships_for``: this is the access
    check we run *before* switching the tenant variable, so RLS on
    ``identity_membership`` would block it. Wrapped in the same super-admin
    elevation; the elevation does not leak to the caller.
    """
    with super_admin_context(reason="identity.can_user_act_for_organization:access_check"):
        return OrganizationMembership.objects.filter(
            user=user,
            organization_id=organization_id,
            is_active=True,
        ).exists()


# --- Customer-side membership management (Slice 45) -------------------------------


class MembershipManagementError(Exception):
    """Raised when a customer-side membership update is invalid."""


def list_organization_members(
    *, organization_id: uuid.UUID | str
) -> list[dict]:
    """Return active + inactive memberships for one organization.

    Customer-facing — caller's tenant context is the org being listed.
    Includes inactive rows so a customer-side admin can re-activate a
    deactivated employee. Sorted oldest first so founders lead.
    """
    qs = (
        OrganizationMembership.objects.filter(organization_id=organization_id)
        .select_related("user", "role")
        .order_by("joined_date")
    )
    return [
        {
            "id": str(m.id),
            "user_id": str(m.user_id),
            "email": m.user.email,
            "role": m.role.name,
            "is_active": bool(m.is_active),
            "joined_date": m.joined_date.isoformat() if m.joined_date else None,
        }
        for m in qs
    ]


def update_organization_member(
    *,
    organization_id: uuid.UUID | str,
    membership_id: uuid.UUID | str,
    actor_user: User,
    is_active: bool | None = None,
    role_name: str | None = None,
) -> dict:
    """Customer owner/admin updates a membership in their own org.

    Authorisation: only OWNER or ADMIN roles may change other rows.
    ADMIN cannot change an OWNER (preserves the "owners are top of
    the food chain" invariant). A user cannot change their OWN role
    or deactivate themselves through this endpoint — accidentally
    demoting yourself can lock the org out, so self-changes go
    through a dedicated profile flow (not in scope yet); cross-user
    changes are. Owners can promote others to owner; admins cannot.

    Customer-side audit: ``organization.membership.updated`` records
    actor + field-names. Distinct from admin-side
    ``admin.membership_updated`` so analytics can split self-service
    vs. operator-driven changes.
    """
    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event

    if is_active is None and role_name is None:
        raise MembershipManagementError(
            "At least one of is_active or role_name must be supplied."
        )

    actor_membership = (
        OrganizationMembership.objects.filter(
            user=actor_user,
            organization_id=organization_id,
            is_active=True,
        )
        .select_related("role")
        .first()
    )
    if actor_membership is None:
        raise MembershipManagementError(
            "You are not a member of this organization."
        )
    actor_role = actor_membership.role.name
    if actor_role not in {"owner", "admin"}:
        raise MembershipManagementError(
            "Only owners and admins can change member access."
        )

    try:
        membership = OrganizationMembership.objects.select_related(
            "role", "user"
        ).get(id=membership_id, organization_id=organization_id)
    except OrganizationMembership.DoesNotExist as exc:
        raise MembershipManagementError(
            f"Membership {membership_id} not found in this organization."
        ) from exc

    if membership.user_id == actor_user.id:
        raise MembershipManagementError(
            "You cannot change your own membership through this endpoint."
        )
    if membership.role.name == "owner" and actor_role != "owner":
        raise MembershipManagementError(
            "Only owners can change another owner's membership."
        )

    changes: dict = {}
    if is_active is not None and bool(is_active) != bool(membership.is_active):
        membership.is_active = bool(is_active)
        changes["is_active"] = bool(is_active)

    if role_name is not None:
        try:
            new_role = Role.objects.get(name=role_name)
        except Role.DoesNotExist as exc:
            raise MembershipManagementError(
                f"Unknown role {role_name!r}."
            ) from exc
        if new_role.name == "owner" and actor_role != "owner":
            raise MembershipManagementError(
                "Only owners can promote another member to owner."
            )
        if new_role.id != membership.role_id:
            membership.role = new_role
            changes["role"] = role_name

    if changes:
        membership.save()
        record_event(
            action_type="organization.membership.updated",
            actor_type=AuditEvent.ActorType.USER,
            actor_id=str(actor_user.id),
            organization_id=str(organization_id),
            affected_entity_type="OrganizationMembership",
            affected_entity_id=str(membership.id),
            payload={"fields_changed": sorted(changes.keys())},
        )

    return {
        "id": str(membership.id),
        "user_id": str(membership.user_id),
        "email": membership.user.email,
        "role": membership.role.name,
        "is_active": bool(membership.is_active),
        "joined_date": membership.joined_date.isoformat()
        if membership.joined_date
        else None,
    }
