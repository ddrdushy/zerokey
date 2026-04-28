"""Extraction context views — the customer-facing engine-activity surface.

  GET /api/v1/engines/        — per-engine summary (for the active org's calls)
  GET /api/v1/engines/calls/  — recent EngineCall rows (paginated)

Read-only. EngineCall rows are append-only at the application layer; the
customer surface never mutates them. Tenant-scoped via the explicit
``organization_id`` filter at the service layer.
"""

from __future__ import annotations

from datetime import datetime

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from . import services
from .serializers import EngineCallSerializer, EngineSummarySerializer


def _active_org(request: Request) -> str | None:
    session = getattr(request, "session", None)
    return session.get("organization_id") if session is not None else None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def engine_summary(request: Request) -> Response:
    organization_id = _active_org(request)
    if not organization_id:
        return Response({"results": []})
    rows = services.engine_summary_for_organization(organization_id=organization_id)
    return Response({"results": EngineSummarySerializer(rows, many=True).data})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def engine_calls(request: Request) -> Response:
    organization_id = _active_org(request)
    if not organization_id:
        return Response({"results": []})

    try:
        limit = int(request.query_params.get("limit", "50"))
    except ValueError:
        return Response(
            {"detail": "limit must be an integer."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    limit = max(1, min(limit, 200))

    raw_before = request.query_params.get("before_started_at")
    before: datetime | None = None
    if raw_before:
        # Accept ISO 8601 strings; reject anything else.
        try:
            before = datetime.fromisoformat(raw_before)
        except ValueError:
            return Response(
                {"detail": "before_started_at must be ISO 8601."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    rows = services.list_engine_calls_for_organization(
        organization_id=organization_id, limit=limit, before_started_at=before
    )
    return Response({"results": EngineCallSerializer(rows, many=True).data})
