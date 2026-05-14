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
    # Slice 118 — TIN uniqueness only against active (non-soft-deleted)
    # orgs. A deleted org's TIN is free for re-registration; the
    # original audit history stays attached to the deleted row.
    if Organization.objects.filter(tin=organization_tin, deleted_at__isnull=True).exists():
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

    # Auto-bootstrap a 14-day trial subscription so the customer
    # lands on a known billing state. Idempotent — if billing's
    # bootstrap helper finds an existing subscription it returns
    # that. Wrapped in try so a billing-app outage doesn't block
    # registration.
    try:
        from apps.billing.services import bootstrap_trial_subscription

        bootstrap_trial_subscription(organization_id=organization.id)
    except Exception:
        # Registration must not fail because billing fell over;
        # operations can backfill via admin or shell.
        pass

    return RegistrationResult(user=user, organization=organization, membership=membership)


def user_org_portal_summary(user: User) -> list[dict]:
    """Phase 4 of PORTAL_PLAN — accountant portal landing payload.

    Returns one row per active org the user is a member of, with the
    pills the multi-org landing surfaces: ERP connection status,
    MyInvois registration (TIN + BRN), signing mode, and last activity.

    Cross-tenant by design (same reason as ``memberships_for`` —
    answers "which orgs can this user open?"). Cheap: one query per
    section, all behind a single super-admin elevation. RLS would
    otherwise hide every row before we got to filter.
    """
    from datetime import timedelta

    from django.db.models import Max
    from django.utils import timezone

    from apps.connectors.models import IntegrationConfig
    from apps.ingestion.models import IngestionJob

    with super_admin_context(reason="identity.user_org_portal_summary"):
        memberships = list(
            OrganizationMembership.objects.filter(
                user=user,
                is_active=True,
                organization__deleted_at__isnull=True,
            )
            .select_related("organization", "role")
            .order_by("organization__legal_name")
        )

        if not memberships:
            return []

        org_ids = [m.organization_id for m in memberships]

        # ERP connectors per org — at most one row needed.
        connector_by_org: dict = {}
        for cfg in IntegrationConfig.objects.filter(
            organization_id__in=org_ids,
            deleted_at__isnull=True,
        ):
            current = connector_by_org.get(cfg.organization_id)
            if current is None:
                connector_by_org[cfg.organization_id] = cfg

        # Last activity = most recent IngestionJob in the last 30 days.
        thirty_days_ago = timezone.now() - timedelta(days=30)
        last_activity = (
            IngestionJob.objects.filter(
                organization_id__in=org_ids,
                created_at__gte=thirty_days_ago,
            )
            .values("organization_id")
            .annotate(last=Max("created_at"))
        )
        last_activity_by_org = {row["organization_id"]: row["last"] for row in last_activity}

    out = []
    for m in memberships:
        org = m.organization
        cfg = connector_by_org.get(org.id)
        out.append(
            {
                "organization_id": str(org.id),
                "legal_name": org.legal_name,
                "tin": org.tin,
                "registration_number": org.registration_number,
                "signing_mode": org.signing_mode,
                "intermediary_consent_at": (
                    org.intermediary_consent_at.isoformat()
                    if org.intermediary_consent_at
                    else None
                ),
                "auto_submit_default": bool(org.auto_submit_default),
                "subscription_state": org.subscription_state,
                "trial_state": org.trial_state,
                "role": m.role.name if m.role else "",
                "connector_type": cfg.connector_type if cfg else "",
                "connector_last_sync_at": (
                    cfg.last_sync_at.isoformat() if cfg and cfg.last_sync_at else None
                ),
                "last_activity_at": (
                    last_activity_by_org.get(org.id).isoformat()
                    if last_activity_by_org.get(org.id)
                    else None
                ),
            }
        )
    return out


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
        # Slice 118 — filter out memberships whose organization has
        # been soft-deleted. The membership row itself stays (audit
        # trail), but a deleted org shouldn't appear in the user's
        # workspace switcher / /me response.
        return list(
            OrganizationMembership.objects.filter(
                user=user,
                is_active=True,
                organization__deleted_at__isnull=True,
            )
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
        # Slice 114 — TIN is now customer-editable. Was locked with
        # a "Contact support to change" hint historically, on the
        # theory that LHDN-issued TINs shouldn't move. In practice
        # (a) support couldn't actually change it either (admin
        # allowlist also excluded it), (b) sign-up typos and tenant
        # restructures legitimately need to update it, and (c) we
        # already had a separate per-integration TIN field that the
        # user could edit, producing a confusing two-stores split.
        # Now: one canonical TIN, edit-from-the-org-page,
        # write-through from the integration credentials path.
        "tin",
        # Slice 115 — BRN + MSIC editable on the org page. The
        # supplier-from-tenant autofill reads these to populate
        # supplier_registration_number / supplier_msic_code on
        # every sales invoice the tenant issues, mirroring the
        # buyer-from-CustomerMaster pattern.
        "registration_number",
        "msic_code",
        "sst_number",
        "registered_address",
        "contact_email",
        "contact_phone",
        "language_preference",
        "timezone",
        "logo_url",
        # Slice 54 — pick the extraction lane (AI vs OCR-only).
        "extraction_mode",
    }
)

# LHDN TIN format — letter prefix (C corporate, IG/OG/G individual)
# followed by 11 digits. Same regex as the structuring sanitiser in
# apps/enrichment/services.py; duplicated to preserve the bounded-
# context boundary.
_TIN_RE = __import__("re").compile(r"^(C|IG|OG|G)\d{11}$")

# extraction_mode is constrained to one of these literal values; the
# update path validates explicitly so an attacker can't poke through
# arbitrary strings (the model field is choices-constrained but
# Django's ORM doesn't enforce that on .save()).
_EXTRACTION_MODE_VALUES: frozenset[str] = frozenset({"ai_vision", "ocr_only"})


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
        if field_name == "extraction_mode" and new_value not in _EXTRACTION_MODE_VALUES:
            raise OrganizationUpdateError(
                f"extraction_mode must be one of {sorted(_EXTRACTION_MODE_VALUES)}; "
                f"got {new_value!r}."
            )
        if field_name == "msic_code":
            # Slice 115 — exactly 5 digits or empty. Mirrors the
            # apply-boundary gate in apps/submission/services.py so a
            # malformed value never lands here either.
            normalized = new_value.strip()
            if normalized and not __import__("re").match(r"^\d{5}$", normalized):
                raise OrganizationUpdateError(
                    f"msic_code must be empty or exactly 5 digits "
                    f"(LHDN industry classification, e.g. 62010); got "
                    f"{new_value!r}."
                )
            new_value = normalized
        if field_name == "registration_number":
            # Slice 115 — BRN is 12 digits for Malaysian corporates;
            # allow any digit-string up to 64 chars so unusual cases
            # (foreign-business numbers via SSM) don't false-fail.
            normalized = new_value.strip()
            if normalized and not __import__("re").match(r"^[0-9A-Z\-]{6,32}$", normalized.upper()):
                raise OrganizationUpdateError(
                    f"registration_number must be 6-32 chars "
                    f"(digits / letters / dash); got {new_value!r}."
                )
            new_value = normalized
        if field_name == "tin":
            # Slice 114 — format validation. Empty is allowed (tenant
            # may not yet have a TIN issued, e.g. mid-onboarding); any
            # non-empty value must match the LHDN shape.
            normalized = new_value.strip().upper()
            if normalized and not _TIN_RE.match(normalized):
                raise OrganizationUpdateError(
                    f"tin must be empty or LHDN-format ({{C,IG,OG,G}}+11 "
                    f"digits, e.g. C20880050010 or IG12345678901); got "
                    f"{new_value!r}."
                )
            # Also enforce the unique constraint on tin (Organization
            # has it indexed) up-front so the error message is clean
            # rather than an IntegrityError at .save() time.
            if normalized:
                taken = (
                    Organization.objects.filter(tin=normalized)
                    .exclude(id=organization_id)
                    .exists()
                )
                if taken:
                    raise OrganizationUpdateError(
                        f"TIN {normalized} is already registered to another "
                        "tenant. If you believe this is yours, contact support."
                    )
            new_value = normalized
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

    # Slice 114 — reverse-sync. When the user edits the TIN here, also
    # update the LHDN integration's credentials.tin so the two surfaces
    # never disagree. The forward direction (integration → org) lives
    # in apps.identity.integrations.upsert_credentials; together they
    # make the two stores feel like one logical field.
    if "tin" in changed:
        _sync_tin_to_lhdn_integration(
            organization_id=organization_id,
            tin=org.tin or "",
            actor_user_id=actor_user_id,
        )

        # Slice 117 — regenerate the self-signed dev cert under the new
        # TIN. The cert subject's OU encodes the TIN; LHDN validates
        # cert.subject.TIN against the document's supplier_tin at
        # submission. A stale cert silently breaks every submission
        # with "authenticated TIN and documents TIN is not matching".
        # Skipped for customer-uploaded certs — those are bound to a
        # real LHDN identity we mustn't tamper with.
        from apps.submission.certificates import regenerate_self_signed_for_tin_change

        if regenerate_self_signed_for_tin_change(organization_id=organization_id):
            record_event(
                action_type="submission.cert.regenerated",
                actor_type=AuditEvent.ActorType.SERVICE,
                actor_id="identity.tin_change",
                organization_id=str(organization_id),
                affected_entity_type="Organization",
                affected_entity_id=str(organization_id),
                payload={
                    "reason": "tin_change",
                    "kind": "self_signed_dev",
                },
            )

    return org


def _sync_tin_to_lhdn_integration(
    *, organization_id: uuid.UUID | str, tin: str, actor_user_id: uuid.UUID | str
) -> None:
    """Mirror Organization.tin onto the lhdn_myinvois integration credentials.

    Applies the value to BOTH environment blobs (sandbox + production) —
    the org's TIN is the same legal identity regardless of which LHDN
    endpoint the tenant is currently targeting. Best-effort: a malformed
    integration row or missing crypto key logs a warning and returns
    rather than rolling back the Organization save.
    """
    from apps.administration.crypto import (
        decrypt_dict_values,
        encrypt_dict_values,
    )
    from apps.identity.models import OrganizationIntegration

    # OrganizationIntegration is TenantScopedModel — RLS-scoped.
    # update_organization runs under whichever context the user's
    # request landed in (typically their tenant), but a fix-up call
    # from a management command may run with no tenant set. Lift
    # the cross-table writes under super-admin so we hit the row
    # regardless of caller context.
    with super_admin_context(reason="identity.tin_reverse_sync"):
        try:
            row = OrganizationIntegration.objects.filter(
                organization_id=organization_id,
                integration_key="lhdn_myinvois",
            ).first()
        except Exception:
            return
        if row is None:
            return
        dirty = False
        for column in ("sandbox_credentials", "production_credentials"):
            plain = decrypt_dict_values(getattr(row, column) or {})
            if (plain.get("tin") or "") == tin:
                continue
            if tin:
                plain["tin"] = tin
            else:
                plain.pop("tin", None)
            setattr(row, column, encrypt_dict_values(plain))
            dirty = True
        if dirty:
            row.updated_by_user_id = actor_user_id
            row.save(
                update_fields=[
                    "sandbox_credentials",
                    "production_credentials",
                    "updated_by_user_id",
                    "updated_at",
                ]
            )


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


def list_organization_members(*, organization_id: uuid.UUID | str) -> list[dict]:
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
        raise MembershipManagementError("At least one of is_active or role_name must be supplied.")

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
        raise MembershipManagementError("You are not a member of this organization.")
    actor_role = actor_membership.role.name
    if actor_role not in {"owner", "admin"}:
        raise MembershipManagementError("Only owners and admins can change member access.")

    try:
        membership = OrganizationMembership.objects.select_related("role", "user").get(
            id=membership_id, organization_id=organization_id
        )
    except OrganizationMembership.DoesNotExist as exc:
        raise MembershipManagementError(
            f"Membership {membership_id} not found in this organization."
        ) from exc

    if membership.user_id == actor_user.id:
        raise MembershipManagementError(
            "You cannot change your own membership through this endpoint."
        )
    if membership.role.name == "owner" and actor_role != "owner":
        raise MembershipManagementError("Only owners can change another owner's membership.")

    changes: dict = {}
    if is_active is not None and bool(is_active) != bool(membership.is_active):
        membership.is_active = bool(is_active)
        changes["is_active"] = bool(is_active)

    if role_name is not None:
        try:
            new_role = Role.objects.get(name=role_name)
        except Role.DoesNotExist as exc:
            raise MembershipManagementError(f"Unknown role {role_name!r}.") from exc
        if new_role.name == "owner" and actor_role != "owner":
            raise MembershipManagementError("Only owners can promote another member to owner.")
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
        "joined_date": membership.joined_date.isoformat() if membership.joined_date else None,
    }
