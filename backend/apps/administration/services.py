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

from .models import SystemSetting


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
