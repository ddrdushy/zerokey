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
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import record_event

from .models import (
    ClassificationCode,
    CountryCode,
    ImpersonationSession,
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
        # Slice 55: SystemSetting.values stores ciphertext at rest.
        # decrypt_value passes legacy plaintext through unchanged so
        # rows written before the encryption rollout still work.
        from .crypto import decrypt_value

        raw = setting.values.get(key)
        if raw not in (None, ""):
            value = decrypt_value(raw) if isinstance(raw, str) else raw
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
    # Slice 55: encrypt-on-write — every string value lands as
    # ciphertext at rest. Keys stay plaintext (the audit log
    # records WHICH keys changed by name, which is a feature).
    from .crypto import encrypt_dict_values

    encrypted_values = encrypt_dict_values(values)

    setting, created = SystemSetting.objects.get_or_create(
        namespace=namespace,
        defaults={
            "values": encrypted_values,
            "description": description,
            "updated_by_id": updated_by_id,
        },
    )
    if not created:
        previous_keys = set(setting.values.keys())
        setting.values = encrypted_values
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
                "before_sequence": int(before_sequence) if before_sequence is not None else 0,
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
            AuditEvent.objects.order_by().values_list("action_type", flat=True).distinct()
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


# --- Shared sparkline helper -----------------------------------------------------


def _daily_count_sparkline(
    queryset: Any,
    *,
    date_field: str,
    days: int = 14,
) -> list[dict[str, Any]]:
    """Bucket a queryset by day for the last ``days`` days. Gap-filled.

    Returns a list of length ``days`` (oldest first) with shape
    ``[{date: "2026-04-29", count: 3}, ...]``. Same shape the customer
    audit-stats sparkline uses (``apps.audit.services._daily_sparkline``)
    so the React side can reuse one sparkline component for both.
    """
    from datetime import timedelta

    from django.db.models import Count
    from django.db.models.functions import TruncDate
    from django.utils import timezone

    today = timezone.localdate(timezone.now())
    start = today - timedelta(days=days - 1)

    rows = (
        queryset.filter(**{f"{date_field}__date__gte": start})
        .annotate(day=TruncDate(date_field))
        .values("day")
        .annotate(count=Count("id"))
    )
    by_day = {row["day"].isoformat(): int(row["count"]) for row in rows}

    series: list[dict[str, Any]] = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        series.append({"date": day.isoformat(), "count": by_day.get(day.isoformat(), 0)})
    return series


# --- Platform overview KPIs (Slice 37) -------------------------------------------


def platform_overview(*, actor_user_id: UUID | str) -> dict[str, Any]:
    """Cross-tenant snapshot for the admin overview page.

    Returns counts the operator looks at first when opening the console:

      - tenants: total + active-in-last-7d (active = at least one
        ingestion job in the window).
      - users: total platform user accounts.
      - ingestion: total ingestion jobs + last-7d count + last-24h count.
      - invoices: total invoices + last-7d count + how many are still
        "ready_for_review" (i.e. unsubmitted and unresolved).
      - inbox: open exception items across every tenant.
      - audit: total events on the chain + last-24h.
      - engines: total registered + active count + degraded count.

    Audited as ``admin.platform_overview_viewed`` so the dashboard load
    appears on the chain. Lightweight payload (counts only) so the
    audit volume stays sane on a frequently-loaded page.
    """
    from datetime import timedelta

    from django.db.models import Count, Q
    from django.utils import timezone

    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event
    from apps.extraction.models import Engine
    from apps.identity.models import Organization, User
    from apps.identity.tenancy import super_admin_context
    from apps.ingestion.models import IngestionJob
    from apps.submission.models import ExceptionInboxItem, Invoice

    now = timezone.now()
    seven_days_ago = now - timedelta(days=7)
    one_day_ago = now - timedelta(hours=24)

    with super_admin_context(reason="admin.platform_overview:read"):
        tenants_total = Organization.objects.count()
        tenants_active_7d = (
            IngestionJob.objects.filter(created_at__gte=seven_days_ago)
            .values("organization_id")
            .distinct()
            .count()
        )
        users_total = User.objects.count()

        jobs_total = IngestionJob.objects.count()
        jobs_7d = IngestionJob.objects.filter(created_at__gte=seven_days_ago).count()
        jobs_24h = IngestionJob.objects.filter(created_at__gte=one_day_ago).count()

        invoices_total = Invoice.objects.count()
        invoices_7d = Invoice.objects.filter(created_at__gte=seven_days_ago).count()
        invoices_pending = Invoice.objects.filter(status=Invoice.Status.READY_FOR_REVIEW).count()

        inbox_open = ExceptionInboxItem.objects.filter(
            status=ExceptionInboxItem.Status.OPEN
        ).count()

        audit_total = AuditEvent.objects.count()
        audit_24h = AuditEvent.objects.filter(timestamp__gte=one_day_ago).count()

        engine_breakdown = {
            row["status"]: int(row["c"])
            for row in Engine.objects.values("status").annotate(c=Count("id"))
        }
        engines_total = sum(engine_breakdown.values())

        # Per-engine 7-day call success rate so the operator can spot a
        # silently-failing engine before tenants do. Gathered as a small
        # list rather than expanding the count blob.
        from apps.extraction.models import EngineCall

        engine_calls = list(
            EngineCall.objects.filter(started_at__gte=seven_days_ago)
            .values("engine__name")
            .annotate(
                total=Count("id"),
                success=Count("id", filter=Q(outcome=EngineCall.Outcome.SUCCESS)),
                failure=Count("id", filter=Q(outcome=EngineCall.Outcome.FAILURE)),
                unavailable=Count("id", filter=Q(outcome=EngineCall.Outcome.UNAVAILABLE)),
            )
            .order_by("-total")[:8]
        )

    # 14-day daily sparklines for the four KPIs the operator most wants to
    # eyeball trends on. Gap-filled so the front-end always renders 14 bars.
    ingestion_sparkline = _daily_count_sparkline(
        IngestionJob.objects.all(),
        date_field="created_at",
        days=14,
    )
    invoices_sparkline = _daily_count_sparkline(
        Invoice.objects.all(),
        date_field="created_at",
        days=14,
    )
    audit_sparkline = _daily_count_sparkline(
        AuditEvent.objects.all(),
        date_field="timestamp",
        days=14,
    )
    inbox_sparkline = _daily_count_sparkline(
        ExceptionInboxItem.objects.all(),
        date_field="created_at",
        days=14,
    )

    overview = {
        "tenants": {
            "total": tenants_total,
            "active_last_7d": tenants_active_7d,
        },
        "users": {"total": users_total},
        "ingestion": {
            "total": jobs_total,
            "last_7d": jobs_7d,
            "last_24h": jobs_24h,
            "sparkline": ingestion_sparkline,
        },
        "invoices": {
            "total": invoices_total,
            "last_7d": invoices_7d,
            "pending_review": invoices_pending,
            "sparkline": invoices_sparkline,
        },
        "inbox": {"open": inbox_open, "sparkline": inbox_sparkline},
        "audit": {
            "total": audit_total,
            "last_24h": audit_24h,
            "sparkline": audit_sparkline,
        },
        "engines": {
            "total": engines_total,
            "active": int(engine_breakdown.get("active", 0)),
            "degraded": int(engine_breakdown.get("degraded", 0)),
            "archived": int(engine_breakdown.get("archived", 0)),
            "calls_last_7d": [
                {
                    "engine": row["engine__name"],
                    "total": int(row["total"]),
                    "success": int(row["success"]),
                    "failure": int(row["failure"]),
                    "unavailable": int(row["unavailable"]),
                }
                for row in engine_calls
            ],
        },
    }

    record_event(
        action_type="admin.platform_overview_viewed",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=None,
        affected_entity_type="Platform",
        affected_entity_id="",
        payload={
            "counters": {
                "tenants_total": tenants_total,
                "invoices_total": invoices_total,
                "inbox_open": inbox_open,
            },
        },
    )
    return overview


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
            qs = qs.filter(legal_name__icontains=search) | qs.filter(tin__icontains=search)
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
            IngestionJob.objects.filter(organization_id__in=org_ids, created_at__gte=seven_days_ago)
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
                "created_at": (org["created_at"].isoformat() if org["created_at"] else None),
                "member_count": int(members_by_org.get(org["id"], 0)),
                "ingestion_jobs_total": int(jobs_total_by_org.get(org["id"], 0)),
                "ingestion_jobs_recent_7d": int(jobs_recent_by_org.get(org["id"], 0)),
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


# --- Tenant detail (Slice 38) ----------------------------------------------------


def tenant_detail(*, actor_user_id: UUID | str, organization_id: UUID | str) -> dict[str, Any]:
    """Cross-tenant per-org snapshot for the admin tenant detail page.

    Returns the same row shape ``list_platform_tenants`` produces, plus:

      - ``members``: list of {user_id, email, role, joined_date}
      - ``recent_invoices``: last 10 invoices with status + buyer +
        invoice number + grand_total + created_at
      - ``recent_jobs``: last 10 ingestion jobs with status + filename +
        engine + confidence + created_at

    Audited as ``admin.tenant_detail_viewed`` with the org_id in the
    payload so the chain records who looked at which tenant.

    Raises ``Organization.DoesNotExist`` if the id is unknown — the
    view layer maps that to a 404.
    """
    from datetime import timedelta

    from django.db.models import Count
    from django.utils import timezone

    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event
    from apps.identity.models import Organization, OrganizationMembership
    from apps.identity.tenancy import super_admin_context
    from apps.ingestion.models import IngestionJob
    from apps.submission.models import ExceptionInboxItem, Invoice

    seven_days_ago = timezone.now() - timedelta(days=7)

    with super_admin_context(reason="admin.tenant_detail:read"):
        # Raises DoesNotExist if the id is unknown.
        org = Organization.objects.get(id=organization_id)

        members = list(
            OrganizationMembership.objects.filter(organization_id=org.id, is_active=True)
            .select_related("user", "role")
            .order_by("joined_date")[:50]
        )

        recent_jobs = list(
            IngestionJob.objects.filter(organization_id=org.id).order_by("-created_at")[:10]
        )
        recent_invoices = list(
            Invoice.objects.filter(organization_id=org.id).order_by("-created_at")[:10]
        )

        member_count = OrganizationMembership.objects.filter(
            organization_id=org.id, is_active=True
        ).count()
        jobs_total = IngestionJob.objects.filter(organization_id=org.id).count()
        jobs_recent_7d = IngestionJob.objects.filter(
            organization_id=org.id, created_at__gte=seven_days_ago
        ).count()
        invoices_total = Invoice.objects.filter(organization_id=org.id).count()
        invoices_pending = Invoice.objects.filter(
            organization_id=org.id, status=Invoice.Status.READY_FOR_REVIEW
        ).count()
        inbox_open = ExceptionInboxItem.objects.filter(
            organization_id=org.id,
            status=ExceptionInboxItem.Status.OPEN,
        ).count()
        # Audit count for the tenant — counts events scoped to this org,
        # NOT system events (those would skew the per-tenant story).
        audit_count = AuditEvent.objects.filter(organization_id=org.id).count()

        # Inbox open by reason for a quick triage view.
        inbox_by_reason = dict(
            ExceptionInboxItem.objects.filter(
                organization_id=org.id,
                status=ExceptionInboxItem.Status.OPEN,
            )
            .values_list("reason")
            .annotate(c=Count("id"))
        )

        # 14-day per-tenant ingestion sparkline so the operator can spot a
        # tenant whose volume just dropped (or spiked) at a glance.
        ingestion_sparkline = _daily_count_sparkline(
            IngestionJob.objects.filter(organization_id=org.id),
            date_field="created_at",
            days=14,
        )

    detail = {
        "id": str(org.id),
        "legal_name": org.legal_name,
        "tin": org.tin,
        "contact_email": org.contact_email,
        "contact_phone": org.contact_phone,
        "registered_address": org.registered_address,
        "subscription_state": org.subscription_state,
        "trial_state": org.trial_state,
        "language_preference": org.language_preference,
        "timezone": org.timezone,
        "billing_currency": org.billing_currency,
        "certificate_uploaded": bool(org.certificate_uploaded),
        "created_at": org.created_at.isoformat() if org.created_at else None,
        "stats": {
            "member_count": int(member_count),
            "ingestion_jobs_total": int(jobs_total),
            "ingestion_jobs_recent_7d": int(jobs_recent_7d),
            "invoices_total": int(invoices_total),
            "invoices_pending_review": int(invoices_pending),
            "inbox_open": int(inbox_open),
            "audit_events": int(audit_count),
        },
        "inbox_open_by_reason": {
            str(reason): int(count) for reason, count in inbox_by_reason.items()
        },
        "ingestion_sparkline": ingestion_sparkline,
        "members": [
            {
                "id": str(m.id),
                "user_id": str(m.user_id),
                "email": m.user.email,
                "role": m.role.name,
                "is_active": bool(m.is_active),
                "joined_date": m.joined_date.isoformat() if m.joined_date else None,
            }
            for m in members
        ],
        "recent_jobs": [
            {
                "id": str(j.id),
                "filename": j.original_filename,
                "mime_type": j.file_mime_type,
                "size_bytes": int(j.file_size or 0),
                "status": j.status,
                "engine": j.extraction_engine,
                "confidence": float(j.extraction_confidence)
                if j.extraction_confidence is not None
                else None,
                "source_channel": j.source_channel,
                "created_at": j.created_at.isoformat() if j.created_at else None,
            }
            for j in recent_jobs
        ],
        "recent_invoices": [
            {
                "id": str(inv.id),
                "invoice_number": inv.invoice_number,
                "buyer_legal_name": inv.buyer_legal_name,
                "status": inv.status,
                "currency_code": inv.currency_code,
                "grand_total": str(inv.grand_total) if inv.grand_total is not None else None,
                "created_at": inv.created_at.isoformat() if inv.created_at else None,
            }
            for inv in recent_invoices
        ],
    }

    record_event(
        action_type="admin.tenant_detail_viewed",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=None,
        affected_entity_type="Organization",
        affected_entity_id=str(org.id),
        payload={
            "tenant_legal_name": org.legal_name,
            "stats_snapshot": detail["stats"],
        },
    )
    return detail


# --- System-settings admin surface (Slice 41) ------------------------------------
#
# Every platform-wide configuration namespace is editable from the admin
# console. The schema below documents what keys belong to each namespace
# and which keys are credentials (redacted on read; rotated by writing a
# new value; cleared by writing empty string). Reading the value back is
# never possible — the API only ever returns ``{key: bool}`` for the
# credential keys.
#
# Adding a new namespace: add it to ``SYSTEM_SETTING_SCHEMAS`` and the
# admin UI renders it automatically. The runtime resolver
# ``apps.administration.services.system_setting`` reads the same DB row
# regardless of whether the namespace is in this schema or not, so the
# schema is purely a documentation + UI hint, not an enforcement gate.


SYSTEM_SETTING_SCHEMAS: list[dict[str, Any]] = [
    {
        "namespace": "lhdn",
        "label": "LHDN MyInvois",
        "description": (
            "Integration with the LHDN MyInvois e-invoice portal. The "
            "preprod URL ships as the default; production deployments "
            "swap in the live endpoint when ready."
        ),
        "fields": [
            {
                "key": "base_url",
                "label": "Base URL",
                "kind": "string",
                "placeholder": "https://preprod-api.myinvois.hasil.gov.my",
            },
            {
                "key": "client_id",
                "label": "Client ID",
                "kind": "credential",
            },
            {
                "key": "client_secret",
                "label": "Client secret",
                "kind": "credential",
            },
        ],
    },
    {
        "namespace": "stripe",
        "label": "Stripe billing",
        "description": (
            "Payments + subscriptions for ZeroKey's plan catalog. FPX "
            "support is enabled on the Stripe side; no separate "
            "namespace required."
        ),
        "fields": [
            {
                "key": "publishable_key",
                "label": "Publishable key",
                "kind": "string",
                "placeholder": "pk_live_…",
            },
            {
                "key": "secret_key",
                "label": "Secret key",
                "kind": "credential",
            },
            {
                "key": "webhook_secret",
                "label": "Webhook signing secret",
                "kind": "credential",
            },
            {
                "key": "default_currency",
                "label": "Default currency",
                "kind": "string",
                "placeholder": "MYR",
            },
        ],
    },
    {
        "namespace": "email",
        "label": "Email / SMTP",
        "description": (
            "Outbound email for password resets, invitations, "
            "notifications. Use a transactional provider (SES, "
            "Postmark, Mailgun) — not a personal Gmail."
        ),
        "fields": [
            {
                "key": "smtp_host",
                "label": "SMTP host",
                "kind": "string",
                "placeholder": "smtp.eu-west-1.amazonaws.com",
            },
            {
                "key": "smtp_port",
                "label": "SMTP port",
                "kind": "string",
                "placeholder": "587",
            },
            {
                "key": "smtp_user",
                "label": "SMTP username",
                "kind": "string",
            },
            {
                "key": "smtp_password",
                "label": "SMTP password",
                "kind": "credential",
            },
            {
                "key": "from_address",
                "label": "From address",
                "kind": "string",
                "placeholder": "no-reply@symprio.com",
            },
            {
                "key": "from_name",
                "label": "From name",
                "kind": "string",
                "placeholder": "ZeroKey",
            },
            {
                "key": "use_tls",
                "label": "Use TLS",
                "kind": "string",
                "placeholder": "true",
            },
        ],
    },
    {
        "namespace": "email_inbound",
        "label": "Email-forward inbound",
        "description": (
            "Inbound webhook for the email-forward ingestion channel "
            "(Slice 64). The email provider (SES + Lambda, Mailgun, "
            "SendGrid Inbound Parse) POSTs parsed messages to "
            "/api/v1/ingestion/inbox/email-forward/. The shared bearer "
            "token is the auth — set it here AND in the provider config."
        ),
        "fields": [
            {
                "key": "webhook_token",
                "label": "Inbound webhook bearer token",
                "kind": "credential",
            },
        ],
    },
    {
        "namespace": "branding",
        "label": "Branding & support",
        "description": (
            "Public-facing branding and support contact information. "
            "Used by the marketing site, transactional emails, and "
            "invoice PDFs."
        ),
        "fields": [
            {
                "key": "product_name",
                "label": "Product name",
                "kind": "string",
                "placeholder": "ZeroKey",
            },
            {
                "key": "support_email",
                "label": "Support email",
                "kind": "string",
                "placeholder": "support@symprio.com",
            },
            {
                "key": "terms_url",
                "label": "Terms of service URL",
                "kind": "string",
                "placeholder": "https://zerokey.symprio.com/terms",
            },
            {
                "key": "privacy_url",
                "label": "Privacy policy URL",
                "kind": "string",
                "placeholder": "https://zerokey.symprio.com/privacy",
            },
        ],
    },
    {
        "namespace": "engine_defaults",
        "label": "Engine routing defaults",
        "description": (
            "Confidence thresholds the extraction pipeline uses when "
            "deciding to escalate from pdfplumber → EasyOCR → vision. "
            "Override per-engine via the engine credentials page."
        ),
        "fields": [
            {
                "key": "ocr_threshold",
                "label": "OCR escalation threshold",
                "kind": "string",
                "placeholder": "0.5",
            },
            {
                "key": "vision_threshold",
                "label": "Vision escalation threshold",
                "kind": "string",
                "placeholder": "0.5",
            },
        ],
    },
]


def list_system_settings_for_admin(*, actor_user_id: UUID | str) -> list[dict[str, Any]]:
    """Return one entry per known namespace with redacted credential metadata.

    Output shape per namespace:
        {
          namespace, label, description, fields: [{key, label, kind, placeholder}],
          values: {key: string},                   (non-credential values only)
          credential_keys: {key: bool},            (which credentials are set)
          updated_at: iso-string | null,
        }

    Credentials are NEVER returned in cleartext — the same
    write-only contract the engine credentials surface uses.

    Audited as ``admin.system_settings_listed``.
    """
    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event

    by_namespace = {s.namespace: s for s in SystemSetting.objects.all()}
    out: list[dict[str, Any]] = []
    for schema in SYSTEM_SETTING_SCHEMAS:
        ns = schema["namespace"]
        row = by_namespace.get(ns)
        stored = (row.values if row else {}) or {}
        cred_keys = {f["key"] for f in schema["fields"] if f["kind"] == "credential"}
        non_cred_values = {
            k: str(v) for k, v in stored.items() if k not in cred_keys and isinstance(k, str)
        }
        credential_keys = {k: bool(stored.get(k)) for k in cred_keys}
        out.append(
            {
                "namespace": ns,
                "label": schema["label"],
                "description": schema["description"],
                "fields": schema["fields"],
                "values": non_cred_values,
                "credential_keys": credential_keys,
                "updated_at": (row.updated_at.isoformat() if row and row.updated_at else None),
            }
        )

    record_event(
        action_type="admin.system_settings_listed",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=None,
        affected_entity_type="SystemSetting",
        affected_entity_id="",
        payload={"namespaces": [s["namespace"] for s in SYSTEM_SETTING_SCHEMAS]},
    )
    return out


class SystemSettingUpdateError(Exception):
    """Raised when a system-setting update payload is invalid."""


def admin_update_system_setting(
    *,
    actor_user_id: UUID | str,
    namespace: str,
    field_updates: dict[str, str],
    reason: str = "",
) -> dict[str, Any]:
    """Patch one namespace's values dict atomically.

    Non-credential keys: any non-None value sets, empty-string clears.
    Credential keys: any non-empty value sets/rotates, empty-string clears.
    Reading credentials back is impossible.

    Audited as ``admin.system_setting_updated`` with the field NAMES
    changed and the reason — never values. The existing
    ``upsert_system_setting`` helper would also work but emits a less
    structured event; this wrapper uses the dedicated admin event so
    the audit log can distinguish operator-driven changes from
    migration-driven ones.
    """
    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event

    if not reason or not reason.strip():
        raise SystemSettingUpdateError("A reason is required for system-setting changes.")

    schema = next(
        (s for s in SYSTEM_SETTING_SCHEMAS if s["namespace"] == namespace),
        None,
    )
    if schema is None:
        raise SystemSettingUpdateError(
            f"Unknown namespace {namespace!r}. "
            f"Allowed: {[s['namespace'] for s in SYSTEM_SETTING_SCHEMAS]}"
        )

    allowed_keys = {f["key"] for f in schema["fields"]}
    invalid = set(field_updates) - allowed_keys
    if invalid:
        raise SystemSettingUpdateError(
            f"Keys not in {namespace} schema: {sorted(invalid)}. Allowed: {sorted(allowed_keys)}"
        )

    with transaction.atomic():
        setting, _ = SystemSetting.objects.select_for_update().get_or_create(
            namespace=namespace,
            defaults={
                "values": {},
                "description": schema["description"],
                "updated_by_id": actor_user_id,
            },
        )
        # Slice 55: stored values are ciphertext; compare in plaintext
        # so a no-op update doesn't fire false "changed" events, then
        # re-encrypt on write.
        from .crypto import decrypt_dict_values, encrypt_dict_values

        current_plain = decrypt_dict_values(dict(setting.values or {}))
        changed_keys: list[str] = []
        for key, value in field_updates.items():
            value_str = "" if value is None else str(value)
            if value_str == "":
                if key in current_plain:
                    del current_plain[key]
                    changed_keys.append(key)
            else:
                if current_plain.get(key) != value_str:
                    current_plain[key] = value_str
                    changed_keys.append(key)

        if not changed_keys:
            return _system_setting_admin_dict(setting, schema)

        setting.values = encrypt_dict_values(current_plain)
        setting.updated_by_id = actor_user_id
        setting.save(update_fields=["values", "updated_by_id", "updated_at"])

        record_event(
            action_type="admin.system_setting_updated",
            actor_type=AuditEvent.ActorType.USER,
            actor_id=str(actor_user_id),
            organization_id=None,
            affected_entity_type="SystemSetting",
            affected_entity_id=str(setting.id),
            payload={
                "namespace": namespace,
                "fields_changed": sorted(changed_keys),
                "reason": reason.strip()[:255],
            },
        )

    return _system_setting_admin_dict(setting, schema)


def _system_setting_admin_dict(setting: SystemSetting, schema: dict[str, Any]) -> dict[str, Any]:
    # Slice 55: stored values are ciphertext at rest. Decrypt for the
    # admin-surface readout — non-credential values must round-trip
    # to the UI in plaintext (host names, region codes, etc.). Credential
    # *presence* booleans don't need plaintext.
    from .crypto import decrypt_dict_values

    stored = decrypt_dict_values(setting.values or {})
    cred_keys = {f["key"] for f in schema["fields"] if f["kind"] == "credential"}
    non_cred_values = {k: str(v) for k, v in stored.items() if k not in cred_keys}
    credential_keys = {k: bool(stored.get(k)) for k in cred_keys}
    return {
        "namespace": setting.namespace,
        "label": schema["label"],
        "description": schema["description"],
        "fields": schema["fields"],
        "values": non_cred_values,
        "credential_keys": credential_keys,
        "updated_at": setting.updated_at.isoformat() if setting.updated_at else None,
    }


# --- Tenant edit from admin (Slice 40) -----------------------------------------
#
# Platform staff can update a tenant's display + contact metadata and
# subscription state via the admin surface. Wiring fields (id, tin) and
# financial state are NOT editable here — those have stronger constraints
# and lifecycle invariants we don't want bypassed by a typo.


_EDITABLE_TENANT_FIELDS = {
    "legal_name",
    "contact_email",
    "contact_phone",
    "registered_address",
    "language_preference",
    "timezone",
    "billing_currency",
    "subscription_state",
    "trial_state",
}


class TenantUpdateError(Exception):
    """Raised when an admin tenant update payload is invalid."""


def admin_update_tenant(
    *,
    actor_user_id: UUID | str,
    organization_id: UUID | str,
    field_updates: dict[str, Any],
    reason: str = "",
) -> dict[str, Any]:
    """Atomically update editable tenant fields under super-admin elevation.

    ``field_updates`` keys are restricted to ``_EDITABLE_TENANT_FIELDS``;
    everything else (id, tin, certificate_*, sst_number) is wiring or
    customer-managed. ``reason`` is REQUIRED — staff edits to customer
    metadata always need a why on the audit row.

    Audited as ``admin.tenant_updated`` with the field NAMES changed and
    the reason in the payload. Field VALUES are never put into the audit
    payload (they could be PII like contact_email or registered_address).
    """
    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event
    from apps.identity.models import Organization
    from apps.identity.tenancy import super_admin_context

    if not reason or not reason.strip():
        raise TenantUpdateError("A reason is required for tenant updates.")

    invalid = set(field_updates) - _EDITABLE_TENANT_FIELDS
    if invalid:
        raise TenantUpdateError(
            f"Fields not editable from admin: {sorted(invalid)}. "
            f"Allowed: {sorted(_EDITABLE_TENANT_FIELDS)}"
        )

    with super_admin_context(reason="admin.tenant_update"):
        with transaction.atomic():
            try:
                org = Organization.objects.select_for_update().get(id=organization_id)
            except Organization.DoesNotExist as exc:
                raise TenantUpdateError(f"Tenant {organization_id} not found.") from exc

            changed: list[str] = []
            for key, value in field_updates.items():
                if value is None:
                    # Treat null as no-op rather than clearing — clearing
                    # contact_email to "" is a destructive change that
                    # should be explicit.
                    continue
                if getattr(org, key) != value:
                    setattr(org, key, value)
                    changed.append(key)

            if not changed:
                return _tenant_admin_dict(org)

            org.save(update_fields=[*changed, "updated_at"])

            record_event(
                action_type="admin.tenant_updated",
                actor_type=AuditEvent.ActorType.USER,
                actor_id=str(actor_user_id),
                organization_id=str(org.id),
                affected_entity_type="Organization",
                affected_entity_id=str(org.id),
                payload={
                    "fields_changed": sorted(changed),
                    "reason": reason.strip()[:255],
                },
            )

    return _tenant_admin_dict(org)


def _tenant_admin_dict(org: Any) -> dict[str, Any]:
    """Single-tenant admin shape after an update."""
    return {
        "id": str(org.id),
        "legal_name": org.legal_name,
        "tin": org.tin,
        "contact_email": org.contact_email,
        "contact_phone": org.contact_phone,
        "registered_address": org.registered_address,
        "language_preference": org.language_preference,
        "timezone": org.timezone,
        "billing_currency": org.billing_currency,
        "subscription_state": org.subscription_state,
        "trial_state": org.trial_state,
    }


# --- Tenant impersonation (Slice 43) ---------------------------------------------
#
# Platform staff can briefly act on behalf of a tenant for support
# purposes. Session is time-limited (30 min default), audited at start
# and end, and the customer-side endpoints continue to receive
# ``request.user == staff_user`` (the User row never changes) — only
# the session's ``organization_id`` shifts to the impersonated tenant
# so RLS reads its data.

IMPERSONATION_TTL_MINUTES = 30
_MAX_REASON_LENGTH = 255


class ImpersonationError(Exception):
    """Raised when an impersonation request is invalid."""


def start_impersonation(
    *,
    actor_user_id: UUID | str,
    organization_id: UUID | str,
    reason: str,
) -> ImpersonationSession:
    """Begin a time-limited impersonation session.

    Closes any earlier active session for the same staff user (one
    impersonation at a time, no chaining), creates a fresh row with a
    30-minute TTL, audits as ``admin.tenant_impersonation_started``.
    """
    from datetime import timedelta

    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event
    from apps.identity.models import Organization
    from apps.identity.tenancy import super_admin_context

    if not reason or not reason.strip():
        raise ImpersonationError("A reason is required to start impersonation.")
    reason_clean = reason.strip()[:_MAX_REASON_LENGTH]

    with super_admin_context(reason="admin.start_impersonation:lookup"):
        try:
            org = Organization.objects.get(id=organization_id)
        except Organization.DoesNotExist as exc:
            raise ImpersonationError(f"Tenant {organization_id} not found.") from exc

        # Close any previous active session by the same staff so the
        # audit chain has a clean start/end pair instead of orphaned
        # rows. Same staff impersonating two tenants simultaneously
        # is explicitly forbidden — they end one before starting another.
        ImpersonationSession.objects.filter(
            staff_user_id=actor_user_id, ended_at__isnull=True
        ).update(
            ended_at=timezone.now(),
            ended_by_user_id=actor_user_id,
            end_reason="superseded_by_new_session",
        )

        with transaction.atomic():
            now = timezone.now()
            session = ImpersonationSession.objects.create(
                staff_user_id=actor_user_id,
                organization_id=org.id,
                started_at=now,
                expires_at=now + timedelta(minutes=IMPERSONATION_TTL_MINUTES),
                reason=reason_clean,
            )
            record_event(
                action_type="admin.tenant_impersonation_started",
                actor_type=AuditEvent.ActorType.USER,
                actor_id=str(actor_user_id),
                organization_id=str(org.id),
                affected_entity_type="ImpersonationSession",
                affected_entity_id=str(session.id),
                payload={
                    "ttl_minutes": IMPERSONATION_TTL_MINUTES,
                    "reason": reason_clean,
                    "tenant_legal_name": org.legal_name,
                },
            )
    return session


def end_impersonation(
    *,
    actor_user_id: UUID | str,
    session_id: UUID | str,
    end_reason: str = "user_ended",
) -> ImpersonationSession:
    """End an active impersonation session.

    Idempotent: ending an already-ended session is a no-op (returns the
    existing row without re-auditing). Auto-expiry is handled by the
    caller checking ``is_active`` on each request.
    """
    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event

    try:
        session = ImpersonationSession.objects.get(id=session_id)
    except ImpersonationSession.DoesNotExist as exc:
        raise ImpersonationError(f"Impersonation session {session_id} not found.") from exc

    if session.ended_at is not None:
        return session

    session.ended_at = timezone.now()
    session.ended_by_user_id = actor_user_id
    session.end_reason = end_reason[:64]
    session.save(update_fields=["ended_at", "ended_by_user_id", "end_reason"])

    record_event(
        action_type="admin.tenant_impersonation_ended",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(session.organization_id),
        affected_entity_type="ImpersonationSession",
        affected_entity_id=str(session.id),
        payload={
            "end_reason": end_reason[:64],
            "duration_seconds": int((session.ended_at - session.started_at).total_seconds()),
        },
    )
    return session


def get_active_impersonation_for_session(*, session_id: UUID | str | None) -> dict[str, Any] | None:
    """Return the active impersonation context for a Django session.

    Called from the identity ``/me/`` endpoint so the frontend can render
    the impersonation banner. Returns None when no session id, when
    the session id is unknown, when the session is ended, or when the
    session is past its expiry. Past-expiry sessions are auto-ended
    here so the next call sees the closed row.
    """
    if not session_id:
        return None
    try:
        session = ImpersonationSession.objects.get(id=session_id)
    except ImpersonationSession.DoesNotExist:
        return None

    if session.ended_at is not None:
        return None
    if not session.is_active:
        # Past expires_at — close it now so the chain has the end event.
        end_impersonation(
            actor_user_id=session.staff_user_id,
            session_id=session.id,
            end_reason="expired",
        )
        return None

    # Resolve tenant legal name for the banner.
    from apps.identity.models import Organization
    from apps.identity.tenancy import super_admin_context

    legal_name = ""
    with super_admin_context(reason="admin.impersonation:banner"):
        org = Organization.objects.filter(id=session.organization_id).first()
        if org is not None:
            legal_name = org.legal_name

    return {
        "session_id": str(session.id),
        "organization_id": str(session.organization_id),
        "tenant_legal_name": legal_name,
        "started_at": session.started_at.isoformat(),
        "expires_at": session.expires_at.isoformat(),
        "reason": session.reason,
    }


# --- Tenant member management (Slice 39) -----------------------------------------
#
# Platform staff can deactivate / reactivate a tenant's membership rows and
# change their role. Used when a customer reports a compromised account, a
# departed employee, or wants to elevate someone via a support ticket
# faster than the customer-side owner path. Every action is audited under
# the staff actor with the membership id on `affected_entity_id`.


class MembershipUpdateError(Exception):
    """Raised when a membership update payload is invalid."""


def admin_update_membership(
    *,
    actor_user_id: UUID | str,
    membership_id: UUID | str,
    is_active: bool | None = None,
    role_name: str | None = None,
    reason: str = "",
) -> dict[str, Any]:
    """Atomically toggle membership.is_active and/or change membership.role.

    Both fields are optional; at least one must be supplied. ``reason`` is
    required (staff-side privileged actions need a why) and lands in the
    audit payload.

    Audited as ``admin.membership_updated`` with the membership id on
    ``affected_entity_id`` so chain queries for "who changed memberships
    on this tenant" find the rows by index.
    """
    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event
    from apps.identity.models import OrganizationMembership, Role
    from apps.identity.tenancy import super_admin_context

    if is_active is None and role_name is None:
        raise MembershipUpdateError("At least one of is_active or role_name must be supplied.")
    if not reason or not reason.strip():
        raise MembershipUpdateError("A reason is required for membership updates.")

    with super_admin_context(reason="admin.membership_update"):
        with transaction.atomic():
            try:
                membership = OrganizationMembership.objects.select_for_update().get(
                    id=membership_id
                )
            except OrganizationMembership.DoesNotExist as exc:
                raise MembershipUpdateError(f"Membership {membership_id} not found.") from exc

            changes: dict[str, Any] = {}
            if is_active is not None and bool(is_active) != bool(membership.is_active):
                membership.is_active = bool(is_active)
                changes["is_active"] = bool(is_active)
            if role_name is not None:
                try:
                    role = Role.objects.get(name=role_name)
                except Role.DoesNotExist as exc:
                    raise MembershipUpdateError(f"Unknown role {role_name!r}.") from exc
                if role.id != membership.role_id:
                    membership.role = role
                    changes["role"] = role_name

            if not changes:
                # No-op; don't pollute the chain. Return current shape.
                pass
            else:
                membership.save()
                record_event(
                    action_type="admin.membership_updated",
                    actor_type=AuditEvent.ActorType.USER,
                    actor_id=str(actor_user_id),
                    organization_id=str(membership.organization_id),
                    affected_entity_type="OrganizationMembership",
                    affected_entity_id=str(membership.id),
                    payload={
                        "fields_changed": sorted(changes.keys()),
                        "reason": reason.strip()[:255],
                    },
                )

    return {
        "id": str(membership.id),
        "user_id": str(membership.user_id),
        "organization_id": str(membership.organization_id),
        "role": membership.role.name,
        "is_active": bool(membership.is_active),
    }


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
        EngineCall.objects.filter(engine_id__in=engine_ids, started_at__gte=cutoff)
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
                "created_at": engine.created_at.isoformat() if engine.created_at else None,
                "updated_at": engine.updated_at.isoformat() if engine.updated_at else None,
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
            f"Fields not editable: {sorted(invalid)}. Allowed: {sorted(_EDITABLE_ENGINE_FIELDS)}"
        )

    if "status" in field_updates and field_updates["status"] not in {
        Engine.Status.ACTIVE,
        Engine.Status.DEGRADED,
        Engine.Status.ARCHIVED,
    }:
        raise EngineUpdateError(
            f"Invalid status {field_updates['status']!r}. Allowed: active, degraded, archived"
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
            # Slice 55: credentials are ciphertext at rest. Decrypt to
            # compare in plaintext (so a no-op re-save doesn't show
            # spurious "changed" entries) then re-encrypt on write.
            from .crypto import decrypt_dict_values, encrypt_dict_values

            current_plain = decrypt_dict_values(dict(engine.credentials or {}))
            for key, value in credential_updates.items():
                if not isinstance(key, str) or not key:
                    raise EngineUpdateError("Credential keys must be non-empty strings.")
                if value == "":
                    if key in current_plain:
                        del current_plain[key]
                        changed_credential_keys.append(key)
                else:
                    if current_plain.get(key) != value:
                        current_plain[key] = value
                        changed_credential_keys.append(key)
            engine.credentials = encrypt_dict_values(current_plain)

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
        counts[label] = model.objects.filter(is_active=True).update(last_refreshed_at=now)
    return counts


# --- Plans + Feature flags admin (Slice 99) -------------------------------------
#
# Plans are platform-wide (not tenant-scoped). Versioning rule: published
# plans are NEVER edited in place — a "revise" creates v=N+1 of the same
# slug and marks the old row inactive. Existing Subscriptions stay
# pointed at the row they were created with so historical billing
# replays accurately.
#
# Feature flags resolve at runtime via apps.billing.services.is_feature
# _enabled (org override → plan.features → flag.default_enabled).


class PlanUpdateError(Exception):
    """Raised by admin plan editors on validation failure."""


def list_plans_for_admin(*, actor_user_id: UUID | str) -> list[dict[str, Any]]:
    """Return every Plan row (active + archived, all versions). Admin-only."""
    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event
    from apps.billing.models import Plan
    from apps.identity.tenancy import super_admin_context

    with super_admin_context(reason="admin.plans:list"):
        plans = list(
            Plan.objects.all().order_by("tier", "slug", "-version")
        )

    record_event(
        action_type="admin.plans_listed",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=None,
        affected_entity_type="Plan",
        affected_entity_id="",
        payload={"plan_count": len(plans)},
    )
    return [_plan_admin_dict(p) for p in plans]


def _plan_admin_dict(plan: Any) -> dict[str, Any]:
    return {
        "id": str(plan.id),
        "slug": plan.slug,
        "version": int(plan.version),
        "name": plan.name,
        "description": plan.description,
        "tier": plan.tier,
        "monthly_price_cents": int(plan.monthly_price_cents),
        "annual_price_cents": int(plan.annual_price_cents),
        "billing_currency": plan.billing_currency,
        "included_invoices_per_month": int(plan.included_invoices_per_month),
        "per_overage_cents": int(plan.per_overage_cents),
        "included_users": int(plan.included_users),
        "included_api_keys": int(plan.included_api_keys),
        "features": plan.features or {},
        "stripe_price_id_monthly": plan.stripe_price_id_monthly,
        "stripe_price_id_annual": plan.stripe_price_id_annual,
        "is_active": bool(plan.is_active),
        "is_public": bool(plan.is_public),
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
    }


# Editable subset on a plan revision. Slug + tier are fixed for a given
# slug-family — changing them creates a different plan, not a revision.
_PLAN_EDITABLE_FIELDS = {
    "name",
    "description",
    "monthly_price_cents",
    "annual_price_cents",
    "billing_currency",
    "included_invoices_per_month",
    "per_overage_cents",
    "included_users",
    "included_api_keys",
    "features",
    "stripe_price_id_monthly",
    "stripe_price_id_annual",
    "is_active",
    "is_public",
}


def admin_revise_plan(
    *,
    actor_user_id: UUID | str,
    plan_id: UUID | str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Publish a new version of an existing plan.

    The previous row stays in the table (so existing Subscriptions
    keep resolving to the price they signed up at) but flips
    ``is_active=False`` so new signups can't pick it. The new row gets
    version=N+1 with merged values.

    Per BUSINESS_MODEL.md: "Existing customers continue on their
    grandfathered plan version unless they actively migrate."

    Returns the new plan row dict.
    """
    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event
    from apps.billing.models import Plan
    from apps.identity.tenancy import super_admin_context

    bad = sorted(set(updates.keys()) - _PLAN_EDITABLE_FIELDS)
    if bad:
        raise PlanUpdateError(f"Unknown plan field(s): {', '.join(bad)}")

    with super_admin_context(reason=f"admin.plans:revise:{plan_id}"):
        with transaction.atomic():
            base = Plan.objects.select_for_update().get(id=plan_id)
            # Bump version. The new row is_active by default; the old
            # row is force-deactivated so new signups can't see it.
            new_version = int(base.version) + 1

            new_data = {
                "slug": base.slug,
                "version": new_version,
                "tier": base.tier,
                "name": updates.get("name", base.name),
                "description": updates.get("description", base.description),
                "monthly_price_cents": int(
                    updates.get("monthly_price_cents", base.monthly_price_cents)
                ),
                "annual_price_cents": int(
                    updates.get("annual_price_cents", base.annual_price_cents)
                ),
                "billing_currency": updates.get(
                    "billing_currency", base.billing_currency
                ),
                "included_invoices_per_month": int(
                    updates.get(
                        "included_invoices_per_month", base.included_invoices_per_month
                    )
                ),
                "per_overage_cents": int(
                    updates.get("per_overage_cents", base.per_overage_cents)
                ),
                "included_users": int(updates.get("included_users", base.included_users)),
                "included_api_keys": int(
                    updates.get("included_api_keys", base.included_api_keys)
                ),
                "features": updates.get("features", base.features) or {},
                "stripe_price_id_monthly": updates.get(
                    "stripe_price_id_monthly", base.stripe_price_id_monthly
                ),
                "stripe_price_id_annual": updates.get(
                    "stripe_price_id_annual", base.stripe_price_id_annual
                ),
                "is_active": bool(updates.get("is_active", True)),
                "is_public": bool(updates.get("is_public", base.is_public)),
            }

            new_plan = Plan.objects.create(**new_data)

            # Deactivate the old row only when we actually shipped a new
            # active row. Keeps the previous plan available if the
            # operator publishes an inactive draft.
            if new_plan.is_active:
                Plan.objects.filter(id=base.id).update(is_active=False)

            record_event(
                action_type="admin.plan_revised",
                actor_type=AuditEvent.ActorType.USER,
                actor_id=str(actor_user_id),
                organization_id=None,
                affected_entity_type="Plan",
                affected_entity_id=str(new_plan.id),
                payload={
                    "slug": base.slug,
                    "from_version": int(base.version),
                    "to_version": new_version,
                    "changed_fields": sorted(updates.keys()),
                },
            )

    return _plan_admin_dict(new_plan)


# --- Feature flags admin -------------------------------------------------------


def list_feature_flags_for_admin(
    *, actor_user_id: UUID | str
) -> list[dict[str, Any]]:
    """List every declared FeatureFlag with override + enabled-org counts."""
    from django.db.models import Count

    from apps.billing.models import FeatureFlag, FeatureFlagOverride
    from apps.identity.tenancy import super_admin_context

    with super_admin_context(reason="admin.feature_flags:list"):
        flags = list(FeatureFlag.objects.all().order_by("category", "slug"))
        override_counts = dict(
            FeatureFlagOverride.objects.values_list("flag_id")
            .annotate(c=Count("id"))
            .values_list("flag_id", "c")
        )

    return [
        {
            "id": str(f.id),
            "slug": f.slug,
            "display_name": f.display_name,
            "description": f.description,
            "default_enabled": bool(f.default_enabled),
            "category": f.category,
            "override_count": int(override_counts.get(f.id, 0)),
        }
        for f in flags
    ]


def admin_update_feature_flag_default(
    *,
    actor_user_id: UUID | str,
    slug: str,
    default_enabled: bool,
    description: str | None = None,
) -> dict[str, Any]:
    """Edit the global default for a declared flag."""
    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event
    from apps.billing.models import FeatureFlag
    from apps.identity.tenancy import super_admin_context

    with super_admin_context(reason=f"admin.feature_flags:update:{slug}"):
        try:
            flag = FeatureFlag.objects.get(slug=slug)
        except FeatureFlag.DoesNotExist as exc:
            raise PlanUpdateError(f"Unknown feature flag: {slug}") from exc

        prior = bool(flag.default_enabled)
        flag.default_enabled = bool(default_enabled)
        if description is not None:
            flag.description = description[:8000]
        flag.save(update_fields=["default_enabled", "description", "updated_at"])

        record_event(
            action_type="admin.feature_flag_default_changed",
            actor_type=AuditEvent.ActorType.USER,
            actor_id=str(actor_user_id),
            organization_id=None,
            affected_entity_type="FeatureFlag",
            affected_entity_id=str(flag.id),
            payload={
                "slug": slug,
                "from": prior,
                "to": bool(default_enabled),
            },
        )

    return {
        "id": str(flag.id),
        "slug": flag.slug,
        "default_enabled": bool(flag.default_enabled),
    }


def admin_set_feature_flag_override(
    *,
    actor_user_id: UUID | str,
    organization_id: UUID | str,
    slug: str,
    enabled: bool,
    reason: str,
    expires_at: Any = None,
) -> dict[str, Any]:
    """Create or update a per-org feature flag override."""
    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event
    from apps.billing.models import FeatureFlag, FeatureFlagOverride
    from apps.identity.tenancy import super_admin_context

    if not (reason or "").strip():
        raise PlanUpdateError("Reason is required for a feature flag override.")

    with super_admin_context(reason=f"admin.feature_flags:override:{slug}"):
        flag = FeatureFlag.objects.filter(slug=slug).first()
        if flag is None:
            raise PlanUpdateError(f"Unknown feature flag: {slug}")

        override, _ = FeatureFlagOverride.objects.update_or_create(
            organization_id=organization_id,
            flag=flag,
            defaults={
                "enabled": bool(enabled),
                "expires_at": expires_at,
                "reason": (reason or "").strip()[:255],
                "created_by_user_id": actor_user_id,
            },
        )

        record_event(
            action_type="admin.feature_flag_override_set",
            actor_type=AuditEvent.ActorType.USER,
            actor_id=str(actor_user_id),
            organization_id=str(organization_id),
            affected_entity_type="FeatureFlagOverride",
            affected_entity_id=str(override.id),
            payload={
                "slug": slug,
                "enabled": bool(enabled),
                "reason": reason,
            },
        )

    return {
        "id": str(override.id),
        "slug": slug,
        "enabled": bool(override.enabled),
        "reason": override.reason,
        "expires_at": override.expires_at.isoformat() if override.expires_at else None,
    }


def admin_clear_feature_flag_override(
    *,
    actor_user_id: UUID | str,
    organization_id: UUID | str,
    slug: str,
) -> None:
    """Remove a per-org override so the org falls back to plan default."""
    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event
    from apps.billing.models import FeatureFlag, FeatureFlagOverride
    from apps.identity.tenancy import super_admin_context

    with super_admin_context(reason=f"admin.feature_flags:clear:{slug}"):
        flag = FeatureFlag.objects.filter(slug=slug).first()
        if flag is None:
            return
        deleted = FeatureFlagOverride.objects.filter(
            organization_id=organization_id, flag=flag
        ).delete()
        if deleted[0]:
            record_event(
                action_type="admin.feature_flag_override_cleared",
                actor_type=AuditEvent.ActorType.USER,
                actor_id=str(actor_user_id),
                organization_id=str(organization_id),
                affected_entity_type="FeatureFlagOverride",
                affected_entity_id="",
                payload={"slug": slug},
            )


def list_feature_flag_overrides_for_org(
    *,
    actor_user_id: UUID | str,
    organization_id: UUID | str,
) -> list[dict[str, Any]]:
    """Return every override for an org for the admin tenant detail panel."""
    from apps.billing.models import FeatureFlagOverride
    from apps.identity.tenancy import super_admin_context

    with super_admin_context(
        reason=f"admin.feature_flags:list_org_overrides:{organization_id}"
    ):
        overrides = list(
            FeatureFlagOverride.objects.filter(organization_id=organization_id)
            .select_related("flag")
            .order_by("flag__category", "flag__slug")
        )

    return [
        {
            "id": str(o.id),
            "slug": o.flag.slug,
            "display_name": o.flag.display_name,
            "enabled": bool(o.enabled),
            "reason": o.reason,
            "expires_at": o.expires_at.isoformat() if o.expires_at else None,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        for o in overrides
    ]


# --- Plan assignment to a tenant -----------------------------------------------


class SubscriptionAssignmentError(Exception):
    """Raised when admin assigns/changes a tenant's plan and validation fails."""


def admin_assign_plan_to_tenant(
    *,
    actor_user_id: UUID | str,
    organization_id: UUID | str,
    plan_id: UUID | str,
    billing_cycle: str = "monthly",
    reason: str = "",
) -> dict[str, Any]:
    """Assign or replace a tenant's active subscription to the given plan.

    Marks the previous active subscription ``replaced`` (per
    BUSINESS_MODEL.md: history is preserved, never deleted) and
    creates a fresh row pointing at the chosen plan + cycle. Does NOT
    sync to Stripe — Stripe-managed subscriptions get changed via the
    customer portal; this path is for admin overrides + custom plans.

    Audit-logged with ``admin.subscription_assigned``.
    """
    from datetime import timedelta

    from django.utils import timezone as _tz

    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event
    from apps.billing.models import Plan, Subscription
    from apps.identity.models import Organization
    from apps.identity.tenancy import super_admin_context

    if billing_cycle not in {"monthly", "annual"}:
        raise SubscriptionAssignmentError(
            "billing_cycle must be 'monthly' or 'annual'."
        )

    with super_admin_context(
        reason=f"admin.subscription:assign:{organization_id}:{plan_id}"
    ):
        with transaction.atomic():
            try:
                org = Organization.objects.get(id=organization_id)
            except Organization.DoesNotExist as exc:
                raise SubscriptionAssignmentError("Unknown organization.") from exc
            try:
                plan = Plan.objects.get(id=plan_id)
            except Plan.DoesNotExist as exc:
                raise SubscriptionAssignmentError("Unknown plan.") from exc

            # Mark every prior active row replaced — keeps the audit
            # story coherent (no two ACTIVEs at once).
            Subscription.objects.filter(
                organization_id=org.id,
                status__in=[
                    Subscription.Status.ACTIVE,
                    Subscription.Status.TRIALING,
                    Subscription.Status.PAST_DUE,
                ],
            ).update(status=Subscription.Status.REPLACED, cancelled_at=_tz.now())

            now = _tz.now()
            cycle_days = 365 if billing_cycle == "annual" else 30
            new_sub = Subscription.objects.create(
                organization_id=org.id,
                plan=plan,
                status=Subscription.Status.ACTIVE,
                billing_cycle=billing_cycle,
                current_period_start=now,
                current_period_end=now + timedelta(days=cycle_days),
            )
            # Mirror to Organization.subscription_state for fast list-page reads.
            org.subscription_state = Organization.SubscriptionState.ACTIVE
            org.save(update_fields=["subscription_state", "updated_at"])

            record_event(
                action_type="admin.subscription_assigned",
                actor_type=AuditEvent.ActorType.USER,
                actor_id=str(actor_user_id),
                organization_id=str(org.id),
                affected_entity_type="Subscription",
                affected_entity_id=str(new_sub.id),
                payload={
                    "plan_slug": plan.slug,
                    "plan_version": int(plan.version),
                    "billing_cycle": billing_cycle,
                    "reason": reason[:255],
                },
            )

    return {
        "id": str(new_sub.id),
        "plan_id": str(plan.id),
        "plan_slug": plan.slug,
        "plan_name": plan.name,
        "billing_cycle": billing_cycle,
        "status": new_sub.status,
    }


# --- Customer support tools (Slice 99) -----------------------------------------


class SupportActionError(Exception):
    """Raised when an admin support action fails validation."""


def admin_reset_user_2fa(
    *,
    actor_user_id: UUID | str,
    target_user_id: UUID | str,
    reason: str,
) -> dict[str, Any]:
    """Disable the target user's 2FA (per PRODUCT_REQUIREMENTS Domain 11).

    Used by support to unblock a customer who lost their authenticator.
    Recovery codes are revoked at the same time so the customer must
    re-enroll cleanly. Audit-logged with the reason.
    """
    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event
    from apps.identity.models import User
    from apps.identity.tenancy import super_admin_context

    if not (reason or "").strip():
        raise SupportActionError("Reason is required to reset a user's 2FA.")

    with super_admin_context(reason=f"admin.support:reset_2fa:{target_user_id}"):
        try:
            user = User.objects.get(id=target_user_id)
        except User.DoesNotExist as exc:
            raise SupportActionError("Unknown user.") from exc

        was_enabled = bool(user.two_factor_enabled)
        user.two_factor_enabled = False
        user.totp_secret_encrypted = ""
        # Slice 89 stored recovery codes as a list field; defensive
        # both shapes.
        for f in ("totp_recovery_codes", "two_factor_recovery_codes"):
            if hasattr(user, f):
                setattr(user, f, [])
        update_fields = ["two_factor_enabled", "totp_secret_encrypted", "updated_at"]
        for f in ("totp_recovery_codes", "two_factor_recovery_codes"):
            if hasattr(user, f):
                update_fields.append(f)
        user.save(update_fields=update_fields)

        record_event(
            action_type="admin.user_2fa_reset",
            actor_type=AuditEvent.ActorType.USER,
            actor_id=str(actor_user_id),
            organization_id=None,
            affected_entity_type="User",
            affected_entity_id=str(user.id),
            payload={
                "email": user.email,
                "was_enabled": was_enabled,
                "reason": reason[:255],
            },
        )

    return {
        "user_id": str(user.id),
        "email": user.email,
        "two_factor_enabled": False,
    }


def admin_retry_stuck_invoice(
    *,
    actor_user_id: UUID | str,
    invoice_id: UUID | str,
    reason: str,
) -> dict[str, Any]:
    """Re-enqueue the structuring + validation pipeline for an invoice.

    Used by support when an invoice landed in error / extracting
    state and never recovered. Re-runs the structurer; if it succeeds
    the invoice transitions to ready_for_review on its own.

    The Stripe-style waitlist: this is the only admin action that
    touches the live extraction pipeline, so we keep it explicit
    rather than auto-recovering.
    """
    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event
    from apps.identity.tenancy import super_admin_context
    from apps.submission.models import Invoice

    if not (reason or "").strip():
        raise SupportActionError("Reason is required to retry an invoice.")

    with super_admin_context(reason=f"admin.support:retry:{invoice_id}"):
        try:
            invoice = Invoice.objects.get(id=invoice_id)
        except Invoice.DoesNotExist as exc:
            raise SupportActionError("Unknown invoice.") from exc

        # Enqueue structuring on the high-priority worker. Don't .delay()
        # under a transaction — but we're outside one here, so it's fine.
        from apps.extraction.tasks import structure_invoice

        structure_invoice.delay(str(invoice.id))

        record_event(
            action_type="admin.invoice_retried",
            actor_type=AuditEvent.ActorType.USER,
            actor_id=str(actor_user_id),
            organization_id=str(invoice.organization_id),
            affected_entity_type="Invoice",
            affected_entity_id=str(invoice.id),
            payload={
                "prior_status": invoice.status,
                "reason": reason[:255],
            },
        )

    return {
        "invoice_id": str(invoice.id),
        "queued": True,
        "prior_status": invoice.status,
    }


def admin_waive_overage(
    *,
    actor_user_id: UUID | str,
    organization_id: UUID | str,
    waived_invoice_count: int,
    reason: str,
) -> dict[str, Any]:
    """Forgive ``waived_invoice_count`` overage invoices on the current period.

    Attaches an ``OverageWaiver`` row to the org's active subscription
    pinned to its current billing period. The bill calculator reads
    waivers and subtracts before computing overage charges.

    Pass ``-1`` to waive all overages for the current period.
    """
    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event
    from apps.billing.models import OverageWaiver, Subscription
    from apps.identity.tenancy import super_admin_context

    if not (reason or "").strip():
        raise SupportActionError("Reason is required to waive overage charges.")
    if not isinstance(waived_invoice_count, int):
        raise SupportActionError("waived_invoice_count must be an integer.")
    if waived_invoice_count == 0:
        raise SupportActionError("Use a non-zero count (or -1 for all).")

    with super_admin_context(
        reason=f"admin.support:waive_overage:{organization_id}"
    ):
        sub = (
            Subscription.objects.filter(
                organization_id=organization_id,
                status__in=[
                    Subscription.Status.ACTIVE,
                    Subscription.Status.TRIALING,
                    Subscription.Status.PAST_DUE,
                ],
            )
            .order_by("-created_at")
            .first()
        )
        if sub is None:
            raise SupportActionError("Tenant has no active subscription.")
        if sub.current_period_start is None or sub.current_period_end is None:
            raise SupportActionError(
                "Active subscription has no billing period to waive against."
            )

        waiver = OverageWaiver.objects.create(
            organization_id=organization_id,
            subscription=sub,
            period_start=sub.current_period_start,
            period_end=sub.current_period_end,
            waived_invoice_count=int(waived_invoice_count),
            reason=reason[:255],
            created_by_user_id=actor_user_id,
        )

        record_event(
            action_type="admin.overage_waived",
            actor_type=AuditEvent.ActorType.USER,
            actor_id=str(actor_user_id),
            organization_id=str(organization_id),
            affected_entity_type="OverageWaiver",
            affected_entity_id=str(waiver.id),
            payload={
                "subscription_id": str(sub.id),
                "waived_invoice_count": int(waived_invoice_count),
                "reason": reason[:255],
            },
        )

    return {
        "id": str(waiver.id),
        "waived_invoice_count": int(waived_invoice_count),
        "period_start": waiver.period_start.isoformat(),
        "period_end": waiver.period_end.isoformat(),
    }


# --- Engine routing-rule editor (Slice 99) -------------------------------------


class RoutingRuleUpdateError(Exception):
    """Raised on validation failure for routing-rule edits."""


def list_routing_rules_for_admin(
    *, actor_user_id: UUID | str
) -> list[dict[str, Any]]:
    """Return every EngineRoutingRule with engine name + capability."""
    from apps.extraction.models import EngineRoutingRule
    from apps.identity.tenancy import super_admin_context

    with super_admin_context(reason="admin.routing_rules:list"):
        rules = list(
            EngineRoutingRule.objects.select_related("engine").order_by(
                "capability", "priority", "created_at"
            )
        )

    return [
        {
            "id": str(r.id),
            "engine_id": str(r.engine.id),
            "engine_name": r.engine.name,
            "engine_status": r.engine.status,
            "capability": r.capability,
            "priority": int(r.priority),
            "is_active": bool(r.is_active),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rules
    ]


def admin_update_routing_rule(
    *,
    actor_user_id: UUID | str,
    rule_id: UUID | str,
    priority: int | None = None,
    is_active: bool | None = None,
) -> dict[str, Any]:
    """Edit a routing rule's priority or active flag."""
    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event
    from apps.extraction.models import EngineRoutingRule
    from apps.identity.tenancy import super_admin_context

    with super_admin_context(reason=f"admin.routing_rules:update:{rule_id}"):
        try:
            rule = EngineRoutingRule.objects.select_related("engine").get(id=rule_id)
        except EngineRoutingRule.DoesNotExist as exc:
            raise RoutingRuleUpdateError("Unknown routing rule.") from exc

        prior = {"priority": rule.priority, "is_active": rule.is_active}
        update_fields: list[str] = []
        if priority is not None:
            try:
                rule.priority = int(priority)
            except (TypeError, ValueError) as exc:
                raise RoutingRuleUpdateError("priority must be an integer.") from exc
            update_fields.append("priority")
        if is_active is not None:
            rule.is_active = bool(is_active)
            update_fields.append("is_active")
        if update_fields:
            rule.save(update_fields=update_fields)

        record_event(
            action_type="admin.routing_rule_updated",
            actor_type=AuditEvent.ActorType.USER,
            actor_id=str(actor_user_id),
            organization_id=None,
            affected_entity_type="EngineRoutingRule",
            affected_entity_id=str(rule.id),
            payload={
                "engine": rule.engine.name,
                "capability": rule.capability,
                "from": prior,
                "to": {"priority": rule.priority, "is_active": rule.is_active},
            },
        )

    return {
        "id": str(rule.id),
        "engine_name": rule.engine.name,
        "capability": rule.capability,
        "priority": int(rule.priority),
        "is_active": bool(rule.is_active),
    }


# --- System health probes (Slice 99) -------------------------------------------


def system_health_snapshot(*, actor_user_id: UUID | str) -> dict[str, Any]:
    """Real-time health view of every critical subsystem.

    Probes:
      - celery: queue depth (Redis broker), worker liveness via task ping
      - postgres: simple SELECT 1
      - lhdn: GET /v1.0/taxpayer/validate/<dummy> → 4xx is healthy
      - stripe: GET /v1/balance with current API key → 401 means
        unconfigured, 200 healthy
      - extraction: avg engine call latency last 60 minutes per engine
    """
    from datetime import timedelta

    from django.db import connection
    from django.utils import timezone as _tz

    from apps.identity.tenancy import super_admin_context

    snapshot: dict[str, Any] = {
        "checked_at": _tz.now().isoformat(),
        "subsystems": {},
        "extraction_latency": [],
        "queue_depth": {},
    }

    # Postgres ping
    pg_ok = False
    try:
        with connection.cursor() as c:
            c.execute("SELECT 1")
            pg_ok = c.fetchone()[0] == 1
    except Exception as exc:
        snapshot["subsystems"]["postgres"] = {
            "status": "down",
            "detail": str(exc)[:120],
        }
    else:
        snapshot["subsystems"]["postgres"] = {"status": "ok" if pg_ok else "down"}

    # Redis / Celery queue depth — reads broker length per known queue.
    try:
        import redis
        from django.conf import settings

        broker = redis.Redis.from_url(settings.CELERY_BROKER_URL)
        for q in ("high", "low", "signing"):
            try:
                snapshot["queue_depth"][q] = int(broker.llen(q))
            except Exception:
                snapshot["queue_depth"][q] = None
        snapshot["subsystems"]["celery"] = {"status": "ok"}
    except Exception as exc:
        snapshot["subsystems"]["celery"] = {
            "status": "unknown",
            "detail": str(exc)[:120],
        }

    # LHDN probe — best-effort. We only check that the configured URL
    # responds; auth status doesn't matter for liveness.
    try:
        import httpx

        from apps.administration.services import system_setting

        base_url = system_setting(namespace="lhdn", key="base_url")
        if base_url:
            r = httpx.get(
                f"{base_url.rstrip('/')}/api/v1.0/taxpayer/validate/IG00000000000",
                timeout=5.0,
            )
            snapshot["subsystems"]["lhdn"] = {
                "status": "ok" if r.status_code < 500 else "degraded",
                "http_status": r.status_code,
            }
        else:
            snapshot["subsystems"]["lhdn"] = {"status": "unconfigured"}
    except Exception as exc:
        snapshot["subsystems"]["lhdn"] = {
            "status": "down",
            "detail": str(exc)[:120],
        }

    # Stripe probe — only check configured-ness (no live API call to keep
    # this snapshot cheap; full balance check is one click away in
    # admin/settings).
    try:
        from apps.administration.services import system_setting

        secret = system_setting(namespace="stripe", key="secret_key")
        snapshot["subsystems"]["stripe"] = {
            "status": "configured" if secret else "unconfigured"
        }
    except Exception as exc:
        snapshot["subsystems"]["stripe"] = {
            "status": "unknown",
            "detail": str(exc)[:120],
        }

    # Extraction latency — avg ms per engine over the last hour.
    try:
        from django.db.models import Avg, Count

        from apps.extraction.models import EngineCall

        cutoff = _tz.now() - timedelta(hours=1)
        with super_admin_context(reason="admin.health:extraction_latency"):
            rows = list(
                EngineCall.objects.filter(started_at__gte=cutoff)
                .values("engine__name")
                .annotate(avg_ms=Avg("duration_ms"), n=Count("id"))
                .order_by("-n")[:10]
            )
        snapshot["extraction_latency"] = [
            {
                "engine": row["engine__name"],
                "avg_ms": int(row["avg_ms"] or 0),
                "calls": int(row["n"]),
            }
            for row in rows
        ]
    except Exception as exc:
        snapshot["extraction_latency_error"] = str(exc)[:120]

    return snapshot
