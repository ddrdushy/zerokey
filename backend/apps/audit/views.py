"""Audit context views.

  GET  /api/v1/audit/stats/         — counts for the active org's KPI tile.
  GET  /api/v1/audit/events/        — paginated list, optional ?action_type filter.
  GET  /api/v1/audit/action-types/  — distinct action types for the dropdown.
  POST /api/v1/audit/verify/        — verify the chain on the customer's behalf.

Reads only (apart from ``verify`` which writes one audit event recording the
verification call itself). Tenant isolation comes from RLS plus the
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


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def verify_chain_view(request: Request) -> Response:
    """Customer-triggered chain verification.

    POST not GET because the call writes one audit event (recording that
    the verification was requested) — same convention every other
    business-meaningful action follows. Cheap to call but not trivially
    idempotent: each call writes a fresh ``audit.chain_verified`` event.
    """
    organization_id = _active_org(request)
    if not organization_id:
        return Response(
            {"detail": "No active organization."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    result = services.verify_chain_for_visibility(
        organization_id=organization_id,
        actor_user_id=request.user.id,
    )
    return Response(result)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def latest_verification_view(request: Request) -> Response:
    """Most recent chain verification run, manual or scheduled.

    Read-only — returns ``{"latest": null}`` before the first beat tick
    (or for a fresh deployment with no verifications yet) so the UI can
    render an explicit "no verification yet" state without 404 handling.
    The shape is sanitised by the service: no ``error_detail``, no
    sequence number on tamper detection.
    """
    organization_id = _active_org(request)
    if not organization_id:
        return Response(
            {"detail": "No active organization."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return Response({"latest": services.latest_chain_verification()})


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
