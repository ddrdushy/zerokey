"""Integrations endpoints."""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.identity import services as identity_services

from . import services


def _check_org(request: Request):
    organization_id = request.session.get("organization_id")
    if not organization_id:
        return None, Response(
            {"detail": "No active organization."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not identity_services.can_user_act_for_organization(request.user, organization_id):
        return None, Response(
            {"detail": "You are not a member of that organization."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return organization_id, None


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def webhooks(request: Request) -> Response:
    """List + create. POST returns plaintext secret ONCE."""
    organization_id, err = _check_org(request)
    if err is not None:
        return err

    if request.method == "POST":
        body = request.data or {}
        try:
            row, plaintext = services.create_webhook(
                organization_id=organization_id,
                label=str(body.get("label") or ""),
                url=str(body.get("url") or ""),
                event_types=body.get("event_types"),
                actor_user_id=request.user.id,
            )
        except services.WebhookError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "id": str(row.id),
                "label": row.label,
                "url": row.url,
                "event_types": list(row.event_types or []),
                "secret_prefix": row.secret_prefix,
                "is_active": True,
                "plaintext_secret": plaintext,
            },
            status=status.HTTP_201_CREATED,
        )

    return Response(
        {
            "results": services.list_webhooks(organization_id=organization_id),
            "available_events": [
                {"key": k, "label": label} for k, label in services.WEBHOOK_EVENT_KEYS
            ],
        }
    )


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def revoke_webhook(request: Request, webhook_id: str) -> Response:
    organization_id, err = _check_org(request)
    if err is not None:
        return err
    try:
        result = services.revoke_webhook(
            organization_id=organization_id,
            webhook_id=webhook_id,
            actor_user_id=request.user.id,
        )
    except services.WebhookError as exc:
        msg = str(exc)
        if "not found" in msg:
            return Response({"detail": msg}, status=status.HTTP_404_NOT_FOUND)
        return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def test_webhook(request: Request, webhook_id: str) -> Response:
    """Send a synthetic test delivery (no real HTTP yet)."""
    organization_id, err = _check_org(request)
    if err is not None:
        return err
    try:
        result = services.send_test_delivery(
            organization_id=organization_id,
            webhook_id=webhook_id,
            actor_user_id=request.user.id,
        )
    except services.WebhookError as exc:
        msg = str(exc)
        if "not found" in msg:
            return Response({"detail": msg}, status=status.HTTP_404_NOT_FOUND)
        return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def webhook_deliveries(request: Request) -> Response:
    organization_id, err = _check_org(request)
    if err is not None:
        return err
    webhook_id = request.query_params.get("webhook_id") or None
    return Response(
        {
            "results": services.list_recent_deliveries(
                organization_id=organization_id,
                webhook_id=webhook_id,
                limit=int(request.query_params.get("limit") or 20),
            )
        }
    )
