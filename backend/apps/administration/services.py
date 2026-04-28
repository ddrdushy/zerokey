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
