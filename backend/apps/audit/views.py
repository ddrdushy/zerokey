"""Audit context views.

  GET /api/v1/audit/stats/         — counts for the active org's KPI tile.
  GET /api/v1/audit/events/        — paginated list, optional ?action_type filter.
  GET /api/v1/audit/action-types/  — distinct action types for the dropdown.

Reads only. The audit log is append-only at the application layer; nothing
in this module mutates events. Tenant isolation comes from RLS plus the
explicit ``organization_id`` filter in the service.
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from . import services
from .serializers import AuditEventSerializer


def _active_org(request: Request) -> str | None:
    session = getattr(request, "session", None)
    return session.get("organization_id") if session is not None else None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def stats(request: Request) -> Response:
    organization_id = _active_org(request)
    if not organization_id:
        return Response(
            {"detail": "No active organization. Switch organization first."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return Response(services.stats_for_organization(organization_id=organization_id))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_events(request: Request) -> Response:
    organization_id = _active_org(request)
    if not organization_id:
        return Response({"results": [], "total": 0})

    action_type = request.query_params.get("action_type") or None
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

    rows = services.list_events_for_organization(
        organization_id=organization_id,
        action_type=action_type,
        limit=limit,
        before_sequence=before_sequence,
    )
    total = services.count_events_for_organization(organization_id=organization_id)
    return Response(
        {
            "results": AuditEventSerializer(rows, many=True).data,
            "total": total,
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_action_types(request: Request) -> Response:
    organization_id = _active_org(request)
    if not organization_id:
        return Response({"results": []})
    return Response(
        {
            "results": services.list_action_types_for_organization(
                organization_id=organization_id
            )
        }
    )
