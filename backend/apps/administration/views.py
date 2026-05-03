"""Platform-administration views (super-admin surface).

Read-mostly today — the first endpoint is just an "are you staff?" probe
the frontend uses to gate the /admin route. Subsequent slices add
cross-tenant audit log, tenant list, engine credentials management.

Every endpoint is protected by ``IsPlatformStaff``; no fallthrough to
tenant-context. The actual cross-tenant queries elevate via
``super_admin_context`` so RLS lets them read across all customers,
with the elevation reason recorded in the audit log per call.
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from . import services
from .permissions import IsPlatformStaff
from .serializers import PlatformAuditEventSerializer


@api_view(["GET"])
@permission_classes([IsPlatformStaff])
def admin_me(request: Request) -> Response:
    """Probe endpoint — returns the staff identity if the caller is staff.

    The frontend's /admin route fetches this on mount. A 403 means
    "not staff — redirect to /dashboard"; a 200 means "render the
    admin shell".
    """
    user = request.user
    return Response(
        {
            "id": str(user.id),
            "email": user.email,
            "is_staff": True,
            "is_superuser": bool(getattr(user, "is_superuser", False)),
        }
    )


@api_view(["GET"])
@permission_classes([IsPlatformStaff])
def platform_overview(request: Request) -> Response:
    """Cross-tenant KPI snapshot for the admin landing page."""
    return Response(services.platform_overview(actor_user_id=request.user.id))


@api_view(["GET"])
@permission_classes([IsPlatformStaff])
def platform_audit_events(request: Request) -> Response:
    """Cross-tenant audit list. Uses sequence-cursor pagination (same as the
    customer-facing audit page).

    Query params:
        ?action_type=auth.login_success       (exact match, optional)
        ?organization_id=<uuid>               (filter to one tenant, optional)
        ?limit=50                             (1-200, default 50)
        ?before_sequence=12345                (pagination cursor, optional)
    """
    action_type = request.query_params.get("action_type") or None
    organization_id = request.query_params.get("organization_id") or None

    try:
        limit = int(request.query_params.get("limit", "50"))
    except ValueError:
        return Response(
            {"detail": "limit must be an integer."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    limit = max(1, min(limit, 200))

    before_sequence: int | None = None
    raw_before = request.query_params.get("before_sequence")
    if raw_before:
        try:
            before_sequence = int(raw_before)
        except ValueError:
            return Response(
                {"detail": "before_sequence must be an integer."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    events = services.list_platform_events(
        actor_user_id=request.user.id,
        action_type=action_type,
        organization_id=organization_id,
        limit=limit,
        before_sequence=before_sequence,
    )
    total = services.count_platform_events(actor_user_id=request.user.id)
    return Response(
        {
            "results": PlatformAuditEventSerializer(events, many=True).data,
            "total": total,
        }
    )


@api_view(["GET"])
@permission_classes([IsPlatformStaff])
def platform_action_types(request: Request) -> Response:
    """Distinct action_type values across the entire chain (cross-tenant)."""
    return Response(
        {
            "results": services.list_platform_action_types(
                actor_user_id=request.user.id,
            ),
        }
    )


@api_view(["GET"])
@permission_classes([IsPlatformStaff])
def admin_list_system_settings(request: Request) -> Response:
    """List every known SystemSetting namespace with redacted credentials."""
    return Response(
        {
            "results": services.list_system_settings_for_admin(
                actor_user_id=request.user.id,
            ),
        }
    )


@api_view(["POST"])
@permission_classes([IsPlatformStaff])
def admin_test_email(request: Request) -> Response:
    """POST /api/v1/admin/system-settings/email/test/

    Body: ``{"to": "ops@example.com"}``. Sends a synchronous test
    email using the configured SMTP creds. Returns the SMTP outcome
    so the operator sees whether the creds are working.
    """
    body = request.data or {}
    to = str(body.get("to") or "").strip()
    if not to or "@" not in to:
        return Response(
            {"detail": "Provide a valid 'to' address."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    from apps.notifications.services import send_test_email

    result = send_test_email(to=to, actor_user_id=request.user.id)
    return Response(result)


@api_view(["PATCH"])
@permission_classes([IsPlatformStaff])
def admin_update_system_setting(request: Request, namespace: str) -> Response:
    """Patch one namespace. Body: { "fields": {...}, "reason": "..." }"""
    body = request.data or {}
    field_updates = body.get("fields") or {}
    if not isinstance(field_updates, dict):
        return Response(
            {"detail": "fields must be an object."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        result = services.admin_update_system_setting(
            actor_user_id=request.user.id,
            namespace=namespace,
            field_updates=field_updates,
            reason=str(body.get("reason") or ""),
        )
    except services.SystemSettingUpdateError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(["PATCH"])
@permission_classes([IsPlatformStaff])
def admin_update_tenant(request: Request, organization_id: str) -> Response:
    """PATCH editable tenant fields. Body shape:
    { "fields": {...}, "reason": "..." }
    """
    body = request.data or {}
    field_updates = body.get("fields") or {}
    if not isinstance(field_updates, dict):
        return Response(
            {"detail": "fields must be an object."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        result = services.admin_update_tenant(
            actor_user_id=request.user.id,
            organization_id=organization_id,
            field_updates=field_updates,
            reason=str(body.get("reason") or ""),
        )
    except services.TenantUpdateError as exc:
        msg = str(exc)
        if "not found" in msg:
            return Response({"detail": msg}, status=status.HTTP_404_NOT_FOUND)
        return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(["PATCH"])
@permission_classes([IsPlatformStaff])
def admin_update_membership(request: Request, membership_id: str) -> Response:
    """Toggle is_active and/or change role on one membership.

    Body shape:
        {
          "is_active": true|false,    (optional)
          "role_name": "owner|admin|approver|submitter|viewer",  (optional)
          "reason": "departed employee — IT ticket #4421"        (REQUIRED)
        }
    """
    body = request.data or {}
    try:
        result = services.admin_update_membership(
            actor_user_id=request.user.id,
            membership_id=membership_id,
            is_active=body.get("is_active"),
            role_name=body.get("role_name"),
            reason=str(body.get("reason") or ""),
        )
    except services.MembershipUpdateError as exc:
        msg = str(exc)
        if "not found" in msg:
            return Response({"detail": msg}, status=status.HTTP_404_NOT_FOUND)
        return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(["GET"])
@permission_classes([IsPlatformStaff])
def platform_tenant_detail(request: Request, organization_id: str) -> Response:
    """Per-tenant snapshot for the admin tenant-detail page."""
    from apps.identity.models import Organization

    try:
        return Response(
            services.tenant_detail(
                actor_user_id=request.user.id,
                organization_id=organization_id,
            )
        )
    except Organization.DoesNotExist:
        return Response(
            {"detail": "Tenant not found."},
            status=status.HTTP_404_NOT_FOUND,
        )


@api_view(["POST"])
@permission_classes([IsPlatformStaff])
def admin_start_impersonation(request: Request, organization_id: str) -> Response:
    """Begin a 30-minute impersonation of one tenant.

    Body: { "reason": "support ticket #4421" }   (REQUIRED)

    On success, sets the Django session's ``organization_id`` to the
    impersonated tenant so customer-side endpoints serve the tenant's
    data, and stores ``impersonation_session_id`` for the banner
    + end-flow lookup. Returns the session details + a redirect_to
    pointing at the customer dashboard.
    """
    body = request.data or {}
    reason = str(body.get("reason") or "")
    try:
        session = services.start_impersonation(
            actor_user_id=request.user.id,
            organization_id=organization_id,
            reason=reason,
        )
    except services.ImpersonationError as exc:
        msg = str(exc)
        if "not found" in msg:
            return Response({"detail": msg}, status=status.HTTP_404_NOT_FOUND)
        return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

    request.session["organization_id"] = str(session.organization_id)
    request.session["impersonation_session_id"] = str(session.id)
    return Response(
        {
            "session_id": str(session.id),
            "organization_id": str(session.organization_id),
            "started_at": session.started_at.isoformat(),
            "expires_at": session.expires_at.isoformat(),
            "redirect_to": "/dashboard",
        }
    )


@api_view(["POST"])
@permission_classes([IsPlatformStaff])
def admin_end_impersonation(request: Request) -> Response:
    """End the current impersonation session for this Django session.

    Idempotent — calling with no active impersonation is a no-op
    that returns 204. Removes ``impersonation_session_id`` and clears
    ``organization_id`` so the staff user's session is back to its
    no-active-org default (admin namespace doesn't need one).
    """
    session_id = request.session.get("impersonation_session_id")
    if session_id:
        try:
            services.end_impersonation(
                actor_user_id=request.user.id,
                session_id=session_id,
                end_reason="user_ended",
            )
        except services.ImpersonationError:
            # Race: someone else already ended the row. Continue
            # cleaning up the Django session anyway.
            pass
    request.session.pop("impersonation_session_id", None)
    request.session.pop("organization_id", None)
    return Response({"redirect_to": "/admin"})


@api_view(["GET"])
@permission_classes([IsPlatformStaff])
def admin_list_engines(request: Request) -> Response:
    """List every engine with redacted credential metadata."""
    return Response(
        {
            "results": services.list_engines_for_admin(
                actor_user_id=request.user.id,
            ),
        }
    )


@api_view(["PATCH"])
@permission_classes([IsPlatformStaff])
def admin_update_engine(request: Request, engine_id: str) -> Response:
    """Patch editable fields + credential keys for one engine.

    Body shape:
        {
            "fields": {"status": "active", "model_identifier": "..."},
            "credentials": {"api_key": "<new>", "host": ""}
        }
    Empty-string credential value deletes the key. Reading back the
    plaintext credential is never possible via this surface.
    """
    from apps.extraction.models import Engine

    body = request.data or {}
    field_updates = body.get("fields") or {}
    credential_updates = body.get("credentials") or {}

    if not isinstance(field_updates, dict) or not isinstance(credential_updates, dict):
        return Response(
            {"detail": "fields and credentials must be objects."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        result = services.update_engine(
            engine_id=engine_id,
            actor_user_id=request.user.id,
            field_updates=field_updates,
            credential_updates=credential_updates,
        )
    except Engine.DoesNotExist:
        return Response(
            {"detail": "Engine not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    except services.EngineUpdateError as exc:
        return Response(
            {"detail": str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return Response(result)


@api_view(["GET"])
@permission_classes([IsPlatformStaff])
def platform_tenants(request: Request) -> Response:
    """Tenant directory with member + activity counts.

    Query params:
        ?search=acme    (case-insensitive substring against legal_name + tin)
        ?limit=100      (1-500, default 100)
    """
    search = (request.query_params.get("search") or "").strip() or None
    try:
        limit = int(request.query_params.get("limit", "100"))
    except ValueError:
        return Response(
            {"detail": "limit must be an integer."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    limit = max(1, min(limit, 500))
    return Response(
        {
            "results": services.list_platform_tenants(
                actor_user_id=request.user.id,
                search=search,
                limit=limit,
            ),
        }
    )


# --- Plans + Feature flags + Routing rules + Support tools (Slice 99) -----------


@api_view(["GET"])
@permission_classes([IsPlatformStaff])
def admin_list_plans(request: Request) -> Response:
    return Response(
        {"results": services.list_plans_for_admin(actor_user_id=request.user.id)}
    )


@api_view(["POST"])
@permission_classes([IsPlatformStaff])
def admin_revise_plan(request: Request, plan_id: str) -> Response:
    body = request.data or {}
    updates = body.get("updates") or {}
    if not isinstance(updates, dict):
        return Response(
            {"detail": "updates must be an object."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        result = services.admin_revise_plan(
            actor_user_id=request.user.id,
            plan_id=plan_id,
            updates=updates,
        )
    except services.PlanUpdateError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as exc:  # Plan.DoesNotExist
        return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
    return Response(result)


@api_view(["GET"])
@permission_classes([IsPlatformStaff])
def admin_list_feature_flags(request: Request) -> Response:
    return Response(
        {"results": services.list_feature_flags_for_admin(actor_user_id=request.user.id)}
    )


@api_view(["PATCH"])
@permission_classes([IsPlatformStaff])
def admin_update_feature_flag(request: Request, slug: str) -> Response:
    body = request.data or {}
    if "default_enabled" not in body:
        return Response(
            {"detail": "default_enabled is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        result = services.admin_update_feature_flag_default(
            actor_user_id=request.user.id,
            slug=slug,
            default_enabled=bool(body.get("default_enabled")),
            description=body.get("description"),
        )
    except services.PlanUpdateError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(["PUT"])
@permission_classes([IsPlatformStaff])
def admin_set_feature_flag_override(
    request: Request, organization_id: str, slug: str
) -> Response:
    body = request.data or {}
    try:
        result = services.admin_set_feature_flag_override(
            actor_user_id=request.user.id,
            organization_id=organization_id,
            slug=slug,
            enabled=bool(body.get("enabled", False)),
            reason=str(body.get("reason") or ""),
        )
    except services.PlanUpdateError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(["DELETE"])
@permission_classes([IsPlatformStaff])
def admin_clear_feature_flag_override(
    request: Request, organization_id: str, slug: str
) -> Response:
    services.admin_clear_feature_flag_override(
        actor_user_id=request.user.id,
        organization_id=organization_id,
        slug=slug,
    )
    return Response({"cleared": True})


@api_view(["GET"])
@permission_classes([IsPlatformStaff])
def admin_list_org_overrides(request: Request, organization_id: str) -> Response:
    return Response(
        {
            "results": services.list_feature_flag_overrides_for_org(
                actor_user_id=request.user.id,
                organization_id=organization_id,
            )
        }
    )


@api_view(["POST"])
@permission_classes([IsPlatformStaff])
def admin_assign_plan(request: Request, organization_id: str) -> Response:
    body = request.data or {}
    try:
        result = services.admin_assign_plan_to_tenant(
            actor_user_id=request.user.id,
            organization_id=organization_id,
            plan_id=str(body.get("plan_id") or ""),
            billing_cycle=str(body.get("billing_cycle") or "monthly"),
            reason=str(body.get("reason") or ""),
        )
    except services.SubscriptionAssignmentError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(["POST"])
@permission_classes([IsPlatformStaff])
def admin_reset_2fa(request: Request, user_id: str) -> Response:
    body = request.data or {}
    try:
        result = services.admin_reset_user_2fa(
            actor_user_id=request.user.id,
            target_user_id=user_id,
            reason=str(body.get("reason") or ""),
        )
    except services.SupportActionError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(["POST"])
@permission_classes([IsPlatformStaff])
def admin_retry_invoice(request: Request, invoice_id: str) -> Response:
    body = request.data or {}
    try:
        result = services.admin_retry_stuck_invoice(
            actor_user_id=request.user.id,
            invoice_id=invoice_id,
            reason=str(body.get("reason") or ""),
        )
    except services.SupportActionError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(["POST"])
@permission_classes([IsPlatformStaff])
def admin_waive_overage(request: Request, organization_id: str) -> Response:
    body = request.data or {}
    try:
        result = services.admin_waive_overage(
            actor_user_id=request.user.id,
            organization_id=organization_id,
            waived_invoice_count=int(body.get("waived_invoice_count") or 0),
            reason=str(body.get("reason") or ""),
        )
    except services.SupportActionError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(["GET"])
@permission_classes([IsPlatformStaff])
def admin_list_routing_rules(request: Request) -> Response:
    return Response(
        {"results": services.list_routing_rules_for_admin(actor_user_id=request.user.id)}
    )


@api_view(["PATCH"])
@permission_classes([IsPlatformStaff])
def admin_update_routing_rule(request: Request, rule_id: str) -> Response:
    body = request.data or {}
    try:
        result = services.admin_update_routing_rule(
            actor_user_id=request.user.id,
            rule_id=rule_id,
            priority=body.get("priority"),
            is_active=body.get("is_active"),
        )
    except services.RoutingRuleUpdateError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(["GET"])
@permission_classes([IsPlatformStaff])
def admin_system_health(request: Request) -> Response:
    return Response(services.system_health_snapshot(actor_user_id=request.user.id))
