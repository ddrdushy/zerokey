"""Billing endpoints — read-mostly for the customer Settings → Billing tab.

Write paths (subscription create / cancel / upgrade) ship with the
Stripe wiring slice; today the customer sees their plan + usage but
can't change billing state from here.
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.identity import services as identity_services

from . import services


@api_view(["GET"])
@permission_classes([AllowAny])
def public_plans(request: Request) -> Response:
    """Public pricing-page plan catalog. No auth required."""
    return Response({"results": services.list_public_plans()})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def billing_overview(request: Request) -> Response:
    """Customer's current subscription + usage for the active org."""
    organization_id = request.session.get("organization_id")
    if not organization_id:
        return Response(
            {"detail": "No active organization."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not identity_services.can_user_act_for_organization(
        request.user, organization_id
    ):
        return Response(
            {"detail": "You are not a member of that organization."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return Response(
        {
            "subscription": services.get_active_subscription(
                organization_id=organization_id
            ),
            "usage": services.current_period_usage(
                organization_id=organization_id
            ),
            "available_plans": services.list_public_plans(),
        }
    )
