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
        series.append(
            {"date": day.isoformat(), "count": by_day.get(day.isoformat(), 0)}
        )
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
        invoices_pending = Invoice.objects.filter(
            status=Invoice.Status.READY_FOR_REVIEW
        ).count()

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
                unavailable=Count(
                    "id", filter=Q(outcome=EngineCall.Outcome.UNAVAILABLE)
                ),
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


# --- Tenant detail (Slice 38) ----------------------------------------------------


def tenant_detail(
    *, actor_user_id: UUID | str, organization_id: UUID | str
) -> dict[str, Any]:
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
            OrganizationMembership.objects.filter(
                organization_id=org.id, is_active=True
            )
            .select_related("user", "role")
            .order_by("joined_date")[:50]
        )

        recent_jobs = list(
            IngestionJob.objects.filter(organization_id=org.id)
            .order_by("-created_at")[:10]
        )
        recent_invoices = list(
            Invoice.objects.filter(organization_id=org.id)
            .order_by("-created_at")[:10]
        )

        member_count = OrganizationMembership.objects.filter(
            organization_id=org.id, is_active=True
        ).count()
        jobs_total = IngestionJob.objects.filter(organization_id=org.id).count()
        jobs_recent_7d = IngestionJob.objects.filter(
            organization_id=org.id, created_at__gte=seven_days_ago
        ).count()
        invoices_total = Invoice.objects.filter(
            organization_id=org.id
        ).count()
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
                "joined_date": m.joined_date.isoformat()
                if m.joined_date
                else None,
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


def list_system_settings_for_admin(
    *, actor_user_id: UUID | str
) -> list[dict[str, Any]]:
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

    by_namespace = {
        s.namespace: s for s in SystemSetting.objects.all()
    }
    out: list[dict[str, Any]] = []
    for schema in SYSTEM_SETTING_SCHEMAS:
        ns = schema["namespace"]
        row = by_namespace.get(ns)
        stored = (row.values if row else {}) or {}
        cred_keys = {
            f["key"] for f in schema["fields"] if f["kind"] == "credential"
        }
        non_cred_values = {
            k: str(v)
            for k, v in stored.items()
            if k not in cred_keys and isinstance(k, str)
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
                "updated_at": (
                    row.updated_at.isoformat()
                    if row and row.updated_at
                    else None
                ),
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
        raise SystemSettingUpdateError(
            "A reason is required for system-setting changes."
        )

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
            f"Keys not in {namespace} schema: {sorted(invalid)}. "
            f"Allowed: {sorted(allowed_keys)}"
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
        current = dict(setting.values or {})
        changed_keys: list[str] = []
        for key, value in field_updates.items():
            value_str = "" if value is None else str(value)
            if value_str == "":
                if key in current:
                    del current[key]
                    changed_keys.append(key)
            else:
                if current.get(key) != value_str:
                    current[key] = value_str
                    changed_keys.append(key)

        if not changed_keys:
            return _system_setting_admin_dict(setting, schema)

        setting.values = current
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


def _system_setting_admin_dict(
    setting: SystemSetting, schema: dict[str, Any]
) -> dict[str, Any]:
    stored = setting.values or {}
    cred_keys = {f["key"] for f in schema["fields"] if f["kind"] == "credential"}
    non_cred_values = {
        k: str(v) for k, v in stored.items() if k not in cred_keys
    }
    credential_keys = {k: bool(stored.get(k)) for k in cred_keys}
    return {
        "namespace": setting.namespace,
        "label": schema["label"],
        "description": schema["description"],
        "fields": schema["fields"],
        "values": non_cred_values,
        "credential_keys": credential_keys,
        "updated_at": setting.updated_at.isoformat()
        if setting.updated_at
        else None,
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
                org = Organization.objects.select_for_update().get(
                    id=organization_id
                )
            except Organization.DoesNotExist as exc:
                raise TenantUpdateError(
                    f"Tenant {organization_id} not found."
                ) from exc

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
        raise MembershipUpdateError(
            "At least one of is_active or role_name must be supplied."
        )
    if not reason or not reason.strip():
        raise MembershipUpdateError("A reason is required for membership updates.")

    with super_admin_context(reason="admin.membership_update"):
        with transaction.atomic():
            try:
                membership = (
                    OrganizationMembership.objects.select_for_update().get(
                        id=membership_id
                    )
                )
            except OrganizationMembership.DoesNotExist as exc:
                raise MembershipUpdateError(
                    f"Membership {membership_id} not found."
                ) from exc

            changes: dict[str, Any] = {}
            if is_active is not None and bool(is_active) != bool(membership.is_active):
                membership.is_active = bool(is_active)
                changes["is_active"] = bool(is_active)
            if role_name is not None:
                try:
                    role = Role.objects.get(name=role_name)
                except Role.DoesNotExist as exc:
                    raise MembershipUpdateError(
                        f"Unknown role {role_name!r}."
                    ) from exc
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
