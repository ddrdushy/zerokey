"""Exception Inbox views.

  GET  /api/v1/inbox/            — list open items, scoped to active org
  POST /api/v1/inbox/<id>/resolve/ — manually mark an item resolved
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from . import inbox as inbox_services
from .models import ExceptionInboxItem
from .serializers import ExceptionInboxItemSerializer


def _active_org(request: Request) -> str | None:
    session = getattr(request, "session", None)
    return session.get("organization_id") if session is not None else None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_inbox(request: Request) -> Response:
    organization_id = _active_org(request)
    if not organization_id:
        return Response({"results": [], "total": 0})

    reason = request.query_params.get("reason") or None
    try:
        limit = int(request.query_params.get("limit", "100"))
    except ValueError:
        return Response(
            {"detail": "limit must be an integer."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    limit = max(1, min(limit, 500))

    rows = inbox_services.list_open_for_organization(
        organization_id=organization_id, reason=reason, limit=limit
    )
    total = inbox_services.count_open_for_organization(
        organization_id=organization_id
    )
    return Response(
        {
            "results": ExceptionInboxItemSerializer(rows, many=True).data,
            "total": total,
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def resolve_inbox_item(request: Request, item_id: str) -> Response:
    organization_id = _active_org(request)
    if not organization_id:
        return Response(
            {"detail": "No active organization."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    note = ""
    if isinstance(request.data, dict):
        note = str(request.data.get("note") or "")

    try:
        item = inbox_services.resolve_by_user(
            organization_id=organization_id,
            item_id=item_id,
            actor_user_id=request.user.id,
            note=note,
        )
    except ExceptionInboxItem.DoesNotExist:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    return Response(ExceptionInboxItemSerializer(item).data)
