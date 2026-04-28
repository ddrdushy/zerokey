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
    return Response(
        services.platform_overview(actor_user_id=request.user.id)
    )


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

    if not isinstance(field_updates, dict) or not isinstance(
        credential_updates, dict
    ):
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
