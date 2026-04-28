"""Service-layer interface for the administration context.

Two responsibilities live here today:

  1. ``system_setting`` — resolve a platform-wide configuration value with
     the canonical lookup order DB ⇒ environment fallback ⇒ explicit
     default ⇒ ``None``. This is the ONE resolver every integration
     adapter (LHDN, Stripe, etc.) goes through.

  2. ``upsert_system_setting`` — atomically write a namespace's values
     dict and emit an audit event. Used by the (future) super-admin
     console; also useful for migrations that seed defaults.

The DB-first / env-fallback ordering is deliberate: it lets a fresh
deployment boot from ``.env`` before the super-admin has populated the
table, but the moment the table is populated the env values stop
mattering. There is no third "code default" tier — defaults are seeded
into the DB at install time so the source of truth stays in one place.

Plaintext storage today; KMS-encrypted columns land alongside the
signing service. The resolver never logs the resolved value; redaction
of the credentials field on the model is enforced at the logging filter.
"""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID

from django.db import transaction

from apps.audit.models import AuditEvent
from apps.audit.services import record_event

from .models import (
    ClassificationCode,
    CountryCode,
    MsicCode,
    SystemSetting,
    TaxTypeCode,
    UnitOfMeasureCode,
)


class SettingNotConfigured(Exception):
    """Raised when a required setting has no value in DB, env, or default."""


def system_setting(
    *,
    namespace: str,
    key: str,
    env_fallback: str | None = None,
    default: str | None = None,
) -> str | None:
    """Resolve a single value from a SystemSetting namespace.

    Lookup order:
      1. ``SystemSetting.values[key]`` (DB, the super-admin's source of truth)
      2. ``os.environ[env_fallback]`` if ``env_fallback`` was provided
      3. ``default``
      4. ``None``

    Empty strings count as "not set" — a namespace with ``{"client_id": ""}``
    falls through to the env fallback. This is what the super-admin UI will
    do when an editor clears a field; the env should pick up where DB
    leaves off rather than the empty value being treated as authoritative.
    """
    setting = SystemSetting.objects.filter(namespace=namespace).first()
    if setting is not None:
        value = setting.values.get(key)
        if value not in (None, ""):
            return str(value)

    if env_fallback:
        env_value = os.environ.get(env_fallback, "").strip()
        if env_value:
            return env_value

    return default


def require_system_setting(
    *,
    namespace: str,
    key: str,
    env_fallback: str | None = None,
) -> str:
    """Same as ``system_setting`` but raises ``SettingNotConfigured`` if missing."""
    value = system_setting(namespace=namespace, key=key, env_fallback=env_fallback)
    if value is None:
        sources = ["SystemSetting"]
        if env_fallback:
            sources.append(f"env {env_fallback}")
        raise SettingNotConfigured(
            f"Setting {namespace}.{key} not configured (looked in {', '.join(sources)})"
        )
    return value


@transaction.atomic
def upsert_system_setting(
    *,
    namespace: str,
    values: dict[str, Any],
    description: str = "",
    updated_by_id: UUID | str | None = None,
) -> SystemSetting:
    """Replace a namespace's values atomically. Emits an audit event.

    The audit payload records WHICH keys changed (by name) but never the
    values themselves — credentials must not leak into the audit log.
    """
    setting, created = SystemSetting.objects.get_or_create(
        namespace=namespace,
        defaults={
            "values": values,
            "description": description,
            "updated_by_id": updated_by_id,
        },
    )
    if not created:
        previous_keys = set(setting.values.keys())
        setting.values = values
        if description:
            setting.description = description
        setting.updated_by_id = updated_by_id
        setting.save(update_fields=["values", "description", "updated_by_id", "updated_at"])
        new_keys = set(values.keys())
        affected_keys = sorted(previous_keys | new_keys)
    else:
        affected_keys = sorted(values.keys())

    record_event(
        action_type="administration.system_setting.updated",
        actor_type=AuditEvent.ActorType.STAFF if updated_by_id else AuditEvent.ActorType.SERVICE,
        actor_id=str(updated_by_id) if updated_by_id else "administration.service",
        organization_id=None,  # Platform-wide setting; not a tenant event.
        affected_entity_type="SystemSetting",
        affected_entity_id=str(setting.id),
        payload={
            "namespace": namespace,
            "keys": affected_keys,
            # Note: NO values. Credentials never enter the audit log.
        },
    )
    return setting


# --- Reference catalog lookups --------------------------------------------------
#
# Each ``is_valid_<catalog>(code)`` returns True if the code is in the
# ACTIVE rows of the corresponding catalog. Inactive rows are kept around
# (historical invoices may reference them) but do not pass new
# validation. The validation rule layer is the one consumer; cross-context
# callers go through these helpers, not the models.


def is_valid_msic(code: str) -> bool:
    if not code:
        return False
    return MsicCode.objects.filter(code=code, is_active=True).exists()


def is_valid_classification(code: str) -> bool:
    if not code:
        return False
    return ClassificationCode.objects.filter(code=code, is_active=True).exists()


def is_valid_uom(code: str) -> bool:
    if not code:
        return False
    return UnitOfMeasureCode.objects.filter(code=code, is_active=True).exists()


def is_valid_tax_type(code: str) -> bool:
    if not code:
        return False
    return TaxTypeCode.objects.filter(code=code, is_active=True).exists()


def is_valid_country(code: str) -> bool:
    if not code:
        return False
    return CountryCode.objects.filter(code=code, is_active=True).exists()


# --- Reference catalog refresh stub ---------------------------------------------
#
# Placeholder for the monthly LHDN catalog refresh per LHDN_INTEGRATION.md
# "reference data caching". Production implementation hits LHDN's published
# catalog endpoints, diffs against the local rows, and:
#   - Inserts new codes.
#   - Updates descriptions on existing codes (LHDN occasionally clarifies).
#   - Marks deprecated codes ``is_active=False`` (historical invoices that
#     reference them still verify).
#   - Updates ``last_refreshed_at`` on every row touched.
#
# Today this just stamps ``last_refreshed_at`` on every active row so the
# Celery beat schedule is a no-op until the LHDN client wires in. The shape
# is here so downstream consumers (super-admin console, ops dashboard)
# can rely on the contract.


# --- Platform-wide audit (Slice 34) -----------------------------------------------
#
# These functions list audit events across ALL tenants for the super-admin
# surface. They elevate via ``super_admin_context`` so RLS lets them read
# rows belonging to other organizations. Every elevation records its reason
# in code; the audit log itself records the resulting query because every
# Read of an audit row that crosses a tenant boundary is itself a
# noteworthy operational fact (you can grep for "admin.platform_audit_listed"
# events to see who looked at what).


def list_platform_events(
    *,
    actor_user_id: UUID | str,
    action_type: str | None = None,
    organization_id: UUID | str | None = None,
    limit: int = 50,
    before_sequence: int | None = None,
) -> list[Any]:
    """Cross-tenant audit list for platform-staff readers.

    Distinct from ``audit.services.list_events_for_organization`` (which
    is tenant-scoped under the regular RLS policy). This function
    elevates briefly to super-admin context so the query reads every
    org's events, then records its own elevation as an audit event so
    the read of cross-tenant rows is itself in the audit chain.

    ``organization_id`` filter (optional) lets the operator narrow to
    one tenant from the same surface — saves a separate "tenants list →
    drill in" gesture when you're chasing a specific incident.

    Returns AuditEvent rows newest-first; the cursor is sequence number
    same as the customer-facing list.
    """
    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event
    from apps.identity.tenancy import super_admin_context

    with super_admin_context(reason="admin.platform_audit:cross_tenant_read"):
        qs = AuditEvent.objects.all()
        if action_type:
            qs = qs.filter(action_type=action_type)
        if organization_id:
            qs = qs.filter(organization_id=organization_id)
        if before_sequence is not None:
            qs = qs.filter(sequence__lt=before_sequence)
        events = list(qs.order_by("-sequence")[:limit])

    # Audit the read itself. The actor is the staff user; we don't scope
    # the event to any tenant (organization_id=NULL because it crosses
    # tenants by definition). Record the filter parameters but never
    # event payloads — those are the THING being audited, recursive
    # inclusion would be noise.
    record_event(
        action_type="admin.platform_audit_listed",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=None,
        affected_entity_type="AuditEvent",
        affected_entity_id="",
        payload={
            "filters": {
                "action_type": action_type or "",
                "organization_id": str(organization_id) if organization_id else "",
                "limit": int(limit),
                "before_sequence": int(before_sequence)
                if before_sequence is not None
                else 0,
            },
            "result_count": len(events),
        },
    )
    return events


def list_platform_action_types(*, actor_user_id: UUID | str) -> list[str]:
    """Distinct action types across the entire chain.

    Powers the filter dropdown on the platform audit page. Cross-tenant
    so the dropdown reflects EVERY action that's ever been recorded,
    not just the ones in the operator's own tenant (which would be
    misleading — a staff user typically has no own-org events).

    Same elevation pattern as ``list_platform_events``; recorded as
    ``admin.platform_action_types_listed``.
    """
    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event
    from apps.identity.tenancy import super_admin_context

    with super_admin_context(reason="admin.platform_audit:list_action_types"):
        types = sorted(
            AuditEvent.objects.order_by()
            .values_list("action_type", flat=True)
            .distinct()
        )

    record_event(
        action_type="admin.platform_action_types_listed",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=None,
        affected_entity_type="AuditEvent",
        affected_entity_id="",
        payload={"distinct_count": len(types)},
    )
    return types


def count_platform_events(*, actor_user_id: UUID | str) -> int:
    """Total event count across the chain. Used as the "events on chain" KPI."""
    from apps.audit.models import AuditEvent
    from apps.identity.tenancy import super_admin_context

    # No audit on the count itself — it's a header KPI that fires on
    # every page load and shouldn't drown the chain in noise.
    with super_admin_context(reason="admin.platform_audit:count"):
        return AuditEvent.objects.count()


# --- Tenant directory (Slice 35) -------------------------------------------------


def list_platform_tenants(
    *, actor_user_id: UUID | str, search: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    """Cross-tenant directory of every Organization on the platform.

    Returns a denormalised dict per tenant with counts that the operator
    needs at-a-glance: member_count, ingestion_jobs_total, recent_jobs
    (last 7 days), and a last_activity_at timestamp. Heavy aggregation
    runs in one query (per metric); the list page uses these to highlight
    tenants that look idle or newly active.

    Audited as ``admin.platform_tenants_listed`` so the cross-tenant
    read appears on the chain.
    """
    from datetime import timedelta

    from django.db.models import Count, Max
    from django.utils import timezone

    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event
    from apps.identity.models import Organization, OrganizationMembership
    from apps.identity.tenancy import super_admin_context
    from apps.ingestion.models import IngestionJob

    seven_days_ago = timezone.now() - timedelta(days=7)

    with super_admin_context(reason="admin.platform_tenants:list"):
        qs = Organization.objects.all()
        if search:
            # Case-insensitive contains across the two display fields the
            # operator might paste in. Plain SQL ILIKE under the hood.
            qs = qs.filter(legal_name__icontains=search) | qs.filter(
                tin__icontains=search
            )
        orgs = list(
            qs.order_by("legal_name").values(
                "id",
                "legal_name",
                "tin",
                "contact_email",
                "subscription_state",
                "created_at",
            )[:limit]
        )

        org_ids = [o["id"] for o in orgs]
        members_by_org = dict(
            OrganizationMembership.objects.filter(organization_id__in=org_ids)
            .values_list("organization_id")
            .annotate(c=Count("id"))
        )
        # Total invoices per org (via IngestionJob — the universally-
        # populated count is "uploads attempted").
        jobs_total_by_org = dict(
            IngestionJob.objects.filter(organization_id__in=org_ids)
            .values_list("organization_id")
            .annotate(c=Count("id"))
        )
        jobs_recent_by_org = dict(
            IngestionJob.objects.filter(
                organization_id__in=org_ids, created_at__gte=seven_days_ago
            )
            .values_list("organization_id")
            .annotate(c=Count("id"))
        )
        # Last activity = max(IngestionJob.created_at, Organization.created_at).
        # An org that's never uploaded still has a "last activity" of its
        # creation timestamp so the column never reads "never".
        last_job_by_org = dict(
            IngestionJob.objects.filter(organization_id__in=org_ids)
            .values_list("organization_id")
            .annotate(at=Max("created_at"))
        )

    out: list[dict[str, Any]] = []
    for org in orgs:
        last_job = last_job_by_org.get(org["id"])
        out.append(
            {
                "id": str(org["id"]),
                "legal_name": org["legal_name"],
                "tin": org["tin"],
                "contact_email": org["contact_email"],
                "subscription_state": org["subscription_state"],
                "created_at": (
                    org["created_at"].isoformat() if org["created_at"] else None
                ),
                "member_count": int(members_by_org.get(org["id"], 0)),
                "ingestion_jobs_total": int(jobs_total_by_org.get(org["id"], 0)),
                "ingestion_jobs_recent_7d": int(
                    jobs_recent_by_org.get(org["id"], 0)
                ),
                "last_activity_at": (
                    last_job.isoformat()
                    if last_job
                    else (org["created_at"].isoformat() if org["created_at"] else None)
                ),
            }
        )

    record_event(
        action_type="admin.platform_tenants_listed",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=None,
        affected_entity_type="Organization",
        affected_entity_id="",
        payload={
            "search": (search or "")[:64],
            "result_count": len(out),
            "limit": int(limit),
        },
    )
    return out


# --- Engine credentials management (Slice 36) ----------------------------------
#
# The super-admin can rotate per-engine credentials (API keys, hosts, model
# identifiers) and toggle status (active / degraded / archived) without
# touching .env or restarting workers. The Engine.credentials JSONField is
# the source of truth at runtime; ``apps.extraction.credentials`` reads
# from it first, then falls back to env. The frontend redacts credential
# values when displaying — operators can replace but not read existing
# values, matching standard credential-rotation UX.


# Credential fields are NEVER returned in cleartext. The frontend gets a
# bool per key indicating "is this field set?", which is enough to render
# "edit" vs "rotate" UI without leaking the secret. To replace a value the
# operator submits the new value; to clear, they submit an empty string.
_REDACTED_PLACEHOLDER = "***"


def list_engines_for_admin(*, actor_user_id: UUID | str) -> list[dict[str, Any]]:
    """Cross-engine catalogue with redacted credential metadata.

    Returns one dict per Engine row with its name, capability, status,
    description, recent-call counts, and a ``credential_keys`` map
    (``{key: is_set}``) — never the values themselves. Operators rotate
    by writing new values; reading them back isn't part of the contract.

    Audited as ``admin.engines_listed`` so the read shows on the chain.
    """
    from datetime import timedelta

    from django.db.models import Count
    from django.utils import timezone

    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event
    from apps.extraction.models import Engine, EngineCall

    cutoff = timezone.now() - timedelta(days=7)

    # No tenant filter — the engine catalogue is global. The audit event
    # below records the read.
    engines = list(Engine.objects.order_by("capability", "name"))
    engine_ids = [e.id for e in engines]
    recent_calls = dict(
        EngineCall.objects.filter(
            engine_id__in=engine_ids, started_at__gte=cutoff
        )
        .values_list("engine_id")
        .annotate(c=Count("id"))
    )
    success_calls = dict(
        EngineCall.objects.filter(
            engine_id__in=engine_ids,
            started_at__gte=cutoff,
            outcome=EngineCall.Outcome.SUCCESS,
        )
        .values_list("engine_id")
        .annotate(c=Count("id"))
    )

    out: list[dict[str, Any]] = []
    for engine in engines:
        creds = engine.credentials or {}
        credential_keys = {k: bool(v) for k, v in creds.items() if isinstance(k, str)}
        out.append(
            {
                "id": str(engine.id),
                "name": engine.name,
                "vendor": engine.vendor,
                "model_identifier": engine.model_identifier,
                "adapter_version": engine.adapter_version,
                "capability": engine.capability,
                "status": engine.status,
                "cost_per_call_micros": int(engine.cost_per_call_micros),
                "description": engine.description,
                "credential_keys": credential_keys,
                "calls_last_7d": int(recent_calls.get(engine.id, 0)),
                "calls_success_last_7d": int(success_calls.get(engine.id, 0)),
                "created_at": engine.created_at.isoformat()
                if engine.created_at
                else None,
                "updated_at": engine.updated_at.isoformat()
                if engine.updated_at
                else None,
            }
        )

    record_event(
        action_type="admin.engines_listed",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=None,
        affected_entity_type="Engine",
        affected_entity_id="",
        payload={"result_count": len(out)},
    )
    return out


# Editable Engine columns. Whitelist enforces "name + adapter_version +
# capability" remain immutable from the UI — those are wiring contracts;
# changing them silently could orphan routing rules.
_EDITABLE_ENGINE_FIELDS = {
    "model_identifier",
    "status",
    "cost_per_call_micros",
    "description",
}


class EngineUpdateError(Exception):
    """Raised when an engine update payload is invalid."""


def update_engine(
    *,
    engine_id: UUID | str,
    actor_user_id: UUID | str,
    field_updates: dict[str, Any] | None = None,
    credential_updates: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Atomically update editable fields and/or credentials on one Engine.

    ``field_updates`` keys are restricted to ``_EDITABLE_ENGINE_FIELDS``
    (model_identifier, status, cost_per_call_micros, description).
    ``credential_updates`` is a dict of {key: value}; an empty-string value
    deletes the key from the JSON, any other string sets it. Reading back
    a credential is never possible through this surface.

    Audited as ``admin.engine_updated`` with the FIELD names (not values)
    in the payload — same PII-safe convention as customer-side
    ``invoice.updated``.
    """
    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event
    from apps.extraction.models import Engine

    field_updates = field_updates or {}
    credential_updates = credential_updates or {}

    invalid = set(field_updates) - _EDITABLE_ENGINE_FIELDS
    if invalid:
        raise EngineUpdateError(
            f"Fields not editable: {sorted(invalid)}. "
            f"Allowed: {sorted(_EDITABLE_ENGINE_FIELDS)}"
        )

    if "status" in field_updates and field_updates["status"] not in {
        Engine.Status.ACTIVE,
        Engine.Status.DEGRADED,
        Engine.Status.ARCHIVED,
    }:
        raise EngineUpdateError(
            f"Invalid status {field_updates['status']!r}. "
            f"Allowed: active, degraded, archived"
        )

    with transaction.atomic():
        engine = Engine.objects.select_for_update().get(id=engine_id)

        changed_fields: list[str] = []
        for key, value in field_updates.items():
            if getattr(engine, key) != value:
                setattr(engine, key, value)
                changed_fields.append(key)

        changed_credential_keys: list[str] = []
        if credential_updates:
            current = dict(engine.credentials or {})
            for key, value in credential_updates.items():
                if not isinstance(key, str) or not key:
                    raise EngineUpdateError("Credential keys must be non-empty strings.")
                if value == "":
                    if key in current:
                        del current[key]
                        changed_credential_keys.append(key)
                else:
                    if current.get(key) != value:
                        current[key] = value
                        changed_credential_keys.append(key)
            engine.credentials = current

        if not changed_fields and not changed_credential_keys:
            # Nothing actually changed — skip the save + audit so the
            # operator's "no-op" gesture (e.g. re-saving the same form)
            # doesn't add audit noise.
            return _engine_admin_dict(engine)

        engine.save()

        record_event(
            action_type="admin.engine_updated",
            actor_type=AuditEvent.ActorType.USER,
            actor_id=str(actor_user_id),
            organization_id=None,
            affected_entity_type="Engine",
            affected_entity_id=str(engine.id),
            payload={
                "engine_name": engine.name,
                "fields_changed": sorted(changed_fields),
                # Names of credential keys, never values.
                "credential_keys_changed": sorted(changed_credential_keys),
            },
        )

    return _engine_admin_dict(engine)


def _engine_admin_dict(engine: Any) -> dict[str, Any]:
    """Single-engine admin shape — same as the list-view rows."""
    creds = engine.credentials or {}
    return {
        "id": str(engine.id),
        "name": engine.name,
        "vendor": engine.vendor,
        "model_identifier": engine.model_identifier,
        "adapter_version": engine.adapter_version,
        "capability": engine.capability,
        "status": engine.status,
        "cost_per_call_micros": int(engine.cost_per_call_micros),
        "description": engine.description,
        "credential_keys": {k: bool(v) for k, v in creds.items()},
        "updated_at": engine.updated_at.isoformat() if engine.updated_at else None,
    }


def refresh_reference_catalogs() -> dict[str, int]:
    """Stamp ``last_refreshed_at`` on every active reference row.

    Returns per-catalog counts so the (future) operations dashboard can
    report what the refresh touched. Real LHDN client lands when the
    integration credentials in the ``lhdn`` SystemSetting are populated.
    """
    from django.utils import timezone as _tz

    now = _tz.now()
    counts: dict[str, int] = {}
    for label, model in (
        ("msic", MsicCode),
        ("classification", ClassificationCode),
        ("uom", UnitOfMeasureCode),
        ("tax_type", TaxTypeCode),
        ("country", CountryCode),
    ):
        counts[label] = model.objects.filter(is_active=True).update(
            last_refreshed_at=now
        )
    return counts
