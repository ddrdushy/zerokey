"""Audit context views.

Phase 2 surface:
  GET /api/v1/audit/stats/ — counts for the active org's KPI tile.

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
