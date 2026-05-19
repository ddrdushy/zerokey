"""Licensing service-layer.

Other contexts (super admin, API views, tests) call these functions;
nothing else writes to License / LicenseHeartbeat.

The verbs:
  - ``issue_license``      — operator creates a new license, returns
                             the plaintext key (shown once).
  - ``validate_license``   — desktop's first call after activation.
                             Binds the machine fingerprint.
  - ``heartbeat_license``  — desktop's daily ping. Refreshes the
                             entitlement TTL.
  - ``revoke_license``     — operator kills a license. Terminal.
  - ``regenerate_license_key`` — operator issues a new key for the
                             same License row; old key is dead.
  - ``renew_license``      — operator (or future Stripe webhook) bumps
                             ``expires_at`` by N days.

All of these emit audit events. The audit chain remains the cloud's
source of truth for "did the operator actually do this?".
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import record_event

from .entitlements import EntitlementError, issue_entitlement
from .models import License, LicenseHeartbeat

logger = logging.getLogger(__name__)


# --- Plan catalog -------------------------------------------------------------------
#
# Source of truth for what each plan unlocks. Lives here (not in the DB)
# because plan definitions don't change per-customer and the desktop has
# to match the same shape when it gates features locally. If we ever
# want operator-editable plan definitions, this moves to a Plan model.

PLAN_FEATURES: dict[str, list[str]] = {
    License.Plan.STARTER: [
        "ingest.manual",
        "ingest.csv",
        "submission.lhdn",
        "consolidation.monthly",
    ],
    License.Plan.PROFESSIONAL: [
        "ingest.manual",
        "ingest.csv",
        "ingest.connectors",
        "submission.lhdn",
        "submission.auto",
        "consolidation.monthly",
        "consolidation.b2c",
    ],
    License.Plan.ENTERPRISE: [
        "ingest.manual",
        "ingest.csv",
        "ingest.connectors",
        "submission.lhdn",
        "submission.auto",
        "consolidation.monthly",
        "consolidation.b2c",
        "audit.export",
        "approvals.workflow",
    ],
}

# Which signing modes each plan permits. Starter is intermediary-only
# (the simplest sale — Symprio signs, no LHDN cert paperwork for the
# customer). Professional/Enterprise unlock self_signed so larger
# customers can bring their own cert if policy requires it.
PLAN_SIGNING_MODES: dict[str, list[str]] = {
    License.Plan.STARTER: ["intermediary"],
    License.Plan.PROFESSIONAL: ["intermediary", "self_signed"],
    License.Plan.ENTERPRISE: ["intermediary", "self_signed"],
}


# --- Errors -------------------------------------------------------------------------


class LicensingError(Exception):
    """Base for any licensing-service failure."""


class DuplicateTinError(LicensingError):
    """A license for this TIN already exists and is not REVOKED."""


class UnknownLicenseKeyError(LicensingError):
    """The supplied key doesn't match any License row."""


class FingerprintMismatchError(LicensingError):
    """A validate call came from a different machine than the bound one."""


class LicenseNotActiveError(LicensingError):
    """The license exists but its current status forbids further use.

    ``status`` carries the actual state so callers can format the
    right user message ("revoked", "expired", etc.).
    """

    def __init__(self, status: str) -> None:
        super().__init__(f"License is {status}")
        self.status = status


# --- Result dataclasses -------------------------------------------------------------


@dataclass(frozen=True)
class IssueResult:
    license_id: uuid.UUID
    plaintext_key: str  # Show once. Never persisted.


@dataclass(frozen=True)
class ActivationResult:
    license_id: uuid.UUID
    organization_legal_name: str
    plan: str
    status: str
    expires_at: datetime
    entitlement_wire: str  # The signed blob the desktop caches.


# --- Helpers ------------------------------------------------------------------------


def _generate_key() -> str:
    """Generate a 32-char URL-safe license key.

    Format: ``ZK-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX`` (dashes added for
    readability when the operator emails it to a customer). The hash
    we store is computed over the dashed form to avoid normalisation
    confusion.
    """
    raw = secrets.token_urlsafe(24)
    # Strip non-alphanumeric, take 28 chars, group by 4.
    cleaned = "".join(c for c in raw if c.isalnum()).upper()[:28]
    groups = "-".join(cleaned[i : i + 4] for i in range(0, 28, 4))
    return f"ZK-{groups}"


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.strip().encode("utf-8")).hexdigest()


def _normalise_fingerprint(raw: str) -> str:
    """Hash whatever the desktop sent so we never store raw machine ids."""
    if not raw:
        return ""
    return hashlib.sha256(raw.strip().encode("utf-8")).hexdigest()


def _refresh_status_if_expired(lic: License) -> License:
    """If the license window closed without anyone noticing, flip it.

    Cheap to do on read paths so the inventory page doesn't lie. We
    save the flip so subsequent reads are consistent.
    """
    if lic.status == License.Status.ACTIVE and lic.expires_at <= timezone.now():
        lic.status = License.Status.EXPIRED
        lic.save(update_fields=["status", "updated_at"])
    return lic


# --- Verbs --------------------------------------------------------------------------


def issue_license(
    *,
    owner_user_id: uuid.UUID,
    organization_legal_name: str,
    organization_tin: str,
    plan: str,
    validity_days: int = 365,
    actor_user_id: uuid.UUID | None = None,
) -> IssueResult:
    """Create a brand-new license. Returns the plaintext key once.

    The TIN must be globally unique among non-revoked licenses — one
    LHDN organisation, one active license. Repeat TINs are how
    customers try to extend their seat count for free, so we block
    here rather than at activate-time.
    """
    organization_tin = organization_tin.strip().upper()
    if not organization_tin:
        raise LicensingError("organization_tin is required")
    if plan not in PLAN_FEATURES:
        raise LicensingError(f"Unknown plan: {plan}")

    existing = (
        License.objects.filter(organization_tin=organization_tin)
        .exclude(status=License.Status.REVOKED)
        .first()
    )
    if existing is not None:
        raise DuplicateTinError(
            f"License {existing.id} already covers TIN {organization_tin} "
            f"(status: {existing.status})"
        )

    plaintext = _generate_key()
    key_hash = _hash_key(plaintext)
    now = timezone.now()

    with transaction.atomic():
        lic = License.objects.create(
            owner_user_id=owner_user_id,
            organization_legal_name=organization_legal_name.strip(),
            organization_tin=organization_tin,
            plan=plan,
            key_hash=key_hash,
            status=License.Status.ACTIVE,
            issued_at=now,
            expires_at=now + timedelta(days=validity_days),
        )
        record_event(
            action_type="licensing.license.issued",
            actor_type=AuditEvent.ActorType.USER
            if actor_user_id
            else AuditEvent.ActorType.SERVICE,
            actor_id=str(actor_user_id) if actor_user_id else "licensing",
            affected_entity_type="License",
            affected_entity_id=str(lic.id),
            payload={
                "organization_tin": organization_tin,
                "plan": plan,
                "validity_days": validity_days,
                "owner_user_id": str(owner_user_id),
            },
        )

    return IssueResult(license_id=lic.id, plaintext_key=plaintext)


def validate_license(
    *,
    key: str,
    machine_fingerprint: str,
    desktop_version: str = "",
    ip: str | None = None,
) -> ActivationResult:
    """First-call from the desktop after the user enters their key.

    Binds the fingerprint on first success. Subsequent calls from a
    different fingerprint hit ``FingerprintMismatchError``.
    """
    key_hash = _hash_key(key)
    fingerprint_hash = _normalise_fingerprint(machine_fingerprint)
    lic = License.objects.filter(key_hash=key_hash).first()
    if lic is None:
        _log_heartbeat(
            None,
            event_type=LicenseHeartbeat.EventType.VALIDATE,
            result=LicenseHeartbeat.Result.UNKNOWN_KEY,
            ip=ip,
            desktop_version=desktop_version,
            fingerprint_hash=fingerprint_hash,
        )
        raise UnknownLicenseKeyError("No such license key.")

    lic = _refresh_status_if_expired(lic)

    # Status gate.
    if lic.status == License.Status.REVOKED:
        _log_heartbeat(
            lic,
            event_type=LicenseHeartbeat.EventType.VALIDATE,
            result=LicenseHeartbeat.Result.REVOKED,
            ip=ip,
            desktop_version=desktop_version,
            fingerprint_hash=fingerprint_hash,
        )
        raise LicenseNotActiveError(lic.status)
    if lic.status == License.Status.SUSPENDED:
        _log_heartbeat(
            lic,
            event_type=LicenseHeartbeat.EventType.VALIDATE,
            result=LicenseHeartbeat.Result.SUSPENDED,
            ip=ip,
            desktop_version=desktop_version,
            fingerprint_hash=fingerprint_hash,
        )
        raise LicenseNotActiveError(lic.status)
    if lic.status == License.Status.EXPIRED:
        _log_heartbeat(
            lic,
            event_type=LicenseHeartbeat.EventType.VALIDATE,
            result=LicenseHeartbeat.Result.EXPIRED,
            ip=ip,
            desktop_version=desktop_version,
            fingerprint_hash=fingerprint_hash,
        )
        raise LicenseNotActiveError(lic.status)

    # Fingerprint gate — bind on first activation, then enforce.
    if lic.bound_fingerprint_hash:
        if fingerprint_hash != lic.bound_fingerprint_hash:
            _log_heartbeat(
                lic,
                event_type=LicenseHeartbeat.EventType.VALIDATE,
                result=LicenseHeartbeat.Result.FINGERPRINT_MISMATCH,
                ip=ip,
                desktop_version=desktop_version,
                fingerprint_hash=fingerprint_hash,
            )
            raise FingerprintMismatchError(
                "This license is already activated on another machine. "
                "Contact support to transfer it."
            )
    else:
        if not fingerprint_hash:
            raise LicensingError("machine_fingerprint is required on first activation")
        lic.bound_fingerprint_hash = fingerprint_hash
        lic.bound_at = timezone.now()
        lic.save(update_fields=["bound_fingerprint_hash", "bound_at", "updated_at"])
        record_event(
            action_type="licensing.license.bound",
            actor_type=AuditEvent.ActorType.SERVICE,
            actor_id="licensing",
            affected_entity_type="License",
            affected_entity_id=str(lic.id),
            payload={"fingerprint_hash_prefix": fingerprint_hash[:12]},
        )

    entitlement, wire = issue_entitlement(
        license_id=lic.id,
        organization_tin=lic.organization_tin,
        organization_legal_name=lic.organization_legal_name,
        plan=lic.plan,
        status=lic.status,
        features=PLAN_FEATURES[lic.plan],
        signing_modes_allowed=PLAN_SIGNING_MODES[lic.plan],
        machine_fingerprint_hash=fingerprint_hash,
    )

    _bump_heartbeat_columns(lic, ip=ip, desktop_version=desktop_version)
    _log_heartbeat(
        lic,
        event_type=LicenseHeartbeat.EventType.VALIDATE,
        result=LicenseHeartbeat.Result.OK,
        ip=ip,
        desktop_version=desktop_version,
        fingerprint_hash=fingerprint_hash,
        entitlement_id=entitlement.entitlement_id,
    )

    return ActivationResult(
        license_id=lic.id,
        organization_legal_name=lic.organization_legal_name,
        plan=lic.plan,
        status=lic.status,
        expires_at=lic.expires_at,
        entitlement_wire=wire,
    )


def heartbeat_license(
    *,
    license_id: uuid.UUID,
    machine_fingerprint: str,
    desktop_version: str = "",
    ip: str | None = None,
) -> ActivationResult:
    """Daily ping from the desktop. Re-mints the entitlement.

    Unlike ``validate_license``, this doesn't bind a fingerprint — it
    expects one already bound and just checks for match. A revoked
    license here returns the same error shape so the desktop can react
    immediately.
    """
    fingerprint_hash = _normalise_fingerprint(machine_fingerprint)
    lic = License.objects.filter(id=license_id).first()
    if lic is None:
        raise UnknownLicenseKeyError("No such license.")

    lic = _refresh_status_if_expired(lic)

    if lic.status != License.Status.ACTIVE:
        result_map = {
            License.Status.REVOKED: LicenseHeartbeat.Result.REVOKED,
            License.Status.EXPIRED: LicenseHeartbeat.Result.EXPIRED,
            License.Status.SUSPENDED: LicenseHeartbeat.Result.SUSPENDED,
        }
        _log_heartbeat(
            lic,
            event_type=LicenseHeartbeat.EventType.HEARTBEAT,
            result=result_map[lic.status],
            ip=ip,
            desktop_version=desktop_version,
            fingerprint_hash=fingerprint_hash,
        )
        raise LicenseNotActiveError(lic.status)

    if lic.bound_fingerprint_hash and fingerprint_hash != lic.bound_fingerprint_hash:
        _log_heartbeat(
            lic,
            event_type=LicenseHeartbeat.EventType.HEARTBEAT,
            result=LicenseHeartbeat.Result.FINGERPRINT_MISMATCH,
            ip=ip,
            desktop_version=desktop_version,
            fingerprint_hash=fingerprint_hash,
        )
        raise FingerprintMismatchError(
            "Heartbeat from an unbound machine. Re-activate via support."
        )

    entitlement, wire = issue_entitlement(
        license_id=lic.id,
        organization_tin=lic.organization_tin,
        organization_legal_name=lic.organization_legal_name,
        plan=lic.plan,
        status=lic.status,
        features=PLAN_FEATURES[lic.plan],
        signing_modes_allowed=PLAN_SIGNING_MODES[lic.plan],
        machine_fingerprint_hash=lic.bound_fingerprint_hash,
    )
    _bump_heartbeat_columns(lic, ip=ip, desktop_version=desktop_version)
    _log_heartbeat(
        lic,
        event_type=LicenseHeartbeat.EventType.HEARTBEAT,
        result=LicenseHeartbeat.Result.OK,
        ip=ip,
        desktop_version=desktop_version,
        fingerprint_hash=fingerprint_hash,
        entitlement_id=entitlement.entitlement_id,
    )

    return ActivationResult(
        license_id=lic.id,
        organization_legal_name=lic.organization_legal_name,
        plan=lic.plan,
        status=lic.status,
        expires_at=lic.expires_at,
        entitlement_wire=wire,
    )


def revoke_license(
    *,
    license_id: uuid.UUID,
    reason: str,
    actor_user_id: uuid.UUID | None = None,
) -> License:
    """Operator action. Terminal; the row stays for the audit trail."""
    with transaction.atomic():
        lic = License.objects.select_for_update().get(id=license_id)
        if lic.status == License.Status.REVOKED:
            return lic
        lic.status = License.Status.REVOKED
        lic.revoked_at = timezone.now()
        lic.revoke_reason = reason.strip()
        lic.save(update_fields=["status", "revoked_at", "revoke_reason", "updated_at"])
        record_event(
            action_type="licensing.license.revoked",
            actor_type=AuditEvent.ActorType.USER
            if actor_user_id
            else AuditEvent.ActorType.SERVICE,
            actor_id=str(actor_user_id) if actor_user_id else "licensing",
            affected_entity_type="License",
            affected_entity_id=str(lic.id),
            payload={"reason": reason.strip(), "organization_tin": lic.organization_tin},
        )
    return lic


def regenerate_license_key(
    *,
    license_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
) -> IssueResult:
    """Issue a fresh key for an existing License row.

    The old key hash is overwritten; any cached entitlement still
    works until its TTL passes (the desktop's binding is fingerprint
    + license_id, not the raw key). After regeneration the user
    re-enters the new key on their desktop.

    We also reset the fingerprint binding — the typical reason for
    regeneration is "I'm moving to a new laptop" or "I lost my key".
    """
    plaintext = _generate_key()
    new_hash = _hash_key(plaintext)
    with transaction.atomic():
        lic = License.objects.select_for_update().get(id=license_id)
        if lic.status == License.Status.REVOKED:
            raise LicensingError("Cannot regenerate a revoked license.")
        lic.key_hash = new_hash
        lic.bound_fingerprint_hash = ""
        lic.bound_at = None
        lic.save(
            update_fields=[
                "key_hash",
                "bound_fingerprint_hash",
                "bound_at",
                "updated_at",
            ]
        )
        record_event(
            action_type="licensing.license.key_regenerated",
            actor_type=AuditEvent.ActorType.USER
            if actor_user_id
            else AuditEvent.ActorType.SERVICE,
            actor_id=str(actor_user_id) if actor_user_id else "licensing",
            affected_entity_type="License",
            affected_entity_id=str(lic.id),
            payload={"organization_tin": lic.organization_tin},
        )
    return IssueResult(license_id=lic.id, plaintext_key=plaintext)


def renew_license(
    *,
    license_id: uuid.UUID,
    days: int = 365,
    actor_user_id: uuid.UUID | None = None,
) -> License:
    """Bump ``expires_at`` and flip EXPIRED → ACTIVE if applicable."""
    with transaction.atomic():
        lic = License.objects.select_for_update().get(id=license_id)
        if lic.status == License.Status.REVOKED:
            raise LicensingError("Cannot renew a revoked license.")
        # Renew from the later of "now" and current expiry — paying
        # early should add to the customer's runway, not reset it.
        base = max(lic.expires_at, timezone.now())
        lic.expires_at = base + timedelta(days=days)
        if lic.status == License.Status.EXPIRED:
            lic.status = License.Status.ACTIVE
        lic.save(update_fields=["expires_at", "status", "updated_at"])
        record_event(
            action_type="licensing.license.renewed",
            actor_type=AuditEvent.ActorType.USER
            if actor_user_id
            else AuditEvent.ActorType.SERVICE,
            actor_id=str(actor_user_id) if actor_user_id else "licensing",
            affected_entity_type="License",
            affected_entity_id=str(lic.id),
            payload={
                "days_added": days,
                "new_expires_at": lic.expires_at.isoformat(),
            },
        )
    return lic


# --- Internal -----------------------------------------------------------------------


def _bump_heartbeat_columns(
    lic: License, *, ip: str | None, desktop_version: str
) -> None:
    lic.last_heartbeat_at = timezone.now()
    if ip:
        lic.last_heartbeat_ip = ip
    if desktop_version:
        lic.last_desktop_version = desktop_version
    lic.save(
        update_fields=[
            "last_heartbeat_at",
            "last_heartbeat_ip",
            "last_desktop_version",
            "updated_at",
        ]
    )


def _log_heartbeat(
    lic: License | None,
    *,
    event_type: str,
    result: str,
    ip: str | None,
    desktop_version: str,
    fingerprint_hash: str,
    entitlement_id: uuid.UUID | None = None,
) -> None:
    try:
        LicenseHeartbeat.objects.create(
            license=lic,
            event_type=event_type,
            result=result,
            ip=ip,
            desktop_version=desktop_version,
            machine_fingerprint_hash=fingerprint_hash,
            entitlement_id=entitlement_id,
        )
    except Exception:  # noqa: S110 — best-effort write, never block validate
        logger.exception("licensing.heartbeat.log_failed")
