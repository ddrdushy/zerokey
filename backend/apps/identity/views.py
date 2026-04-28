"""Identity context views.

DRF views for registration, login, logout, /me, and switch-organization.
Phase 1 uses session authentication (cookie-based) for the customer web app;
API-key authentication for programmatic access lands in Phase 4.
"""

from __future__ import annotations

from django.contrib.auth import authenticate, login, logout
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from . import services
from .serializers import (
    LoginSerializer,
    OrganizationDetailSerializer,
    RegisterSerializer,
    SwitchOrganizationSerializer,
    UserSerializer,
)


@api_view(["GET"])
@permission_classes([AllowAny])
def ping(_request: Request) -> Response:
    return Response({"context": "identity", "status": "ok"})


@ensure_csrf_cookie
@api_view(["GET"])
@permission_classes([AllowAny])
def csrf(_request: Request) -> Response:
    """Set the CSRF cookie so the SPA can include the token on POSTs."""
    return Response({"detail": "CSRF cookie set"})


@api_view(["POST"])
@permission_classes([AllowAny])
def register(request: Request) -> Response:
    """Register a new owner. Creates User + Organization + Owner Membership atomically."""
    serializer = RegisterSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        result = services.register_owner(**serializer.validated_data)
    except services.RegistrationError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    # Set the active organization first so the auth signal handler picks it up,
    # then call login() — which fires user_logged_in and records the event.
    request.session["organization_id"] = str(result.organization.id)
    login(request, result.user)

    return Response(
        UserSerializer(result.user, context={"request": request}).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request: Request) -> Response:
    serializer = LoginSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = authenticate(
        request,
        username=serializer.validated_data["email"],
        password=serializer.validated_data["password"],
    )
    if user is None or not user.is_active:
        # The signal-handler still records auth.login_failed via Django's
        # user_login_failed signal, fired by ``authenticate`` on miss.
        return Response({"detail": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)

    # Set the active organization first so the auth signal handler attributes
    # the login event to the right tenant, then call login().
    memberships = services.memberships_for(user)
    if memberships:
        request.session["organization_id"] = str(memberships[0].organization_id)
    login(request, user)

    return Response(UserSerializer(user, context={"request": request}).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_view(request: Request) -> Response:
    logout(request)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request: Request) -> Response:
    # If the user is authenticated but their session has no active org (e.g.
    # they signed in before any membership existed, or admin truncates wiped
    # state), auto-pick their first active membership. Better UX than a stuck
    # "No active organization" dashboard.
    if not request.session.get("organization_id"):
        memberships = services.memberships_for(request.user)
        if memberships:
            request.session["organization_id"] = str(memberships[0].organization_id)
    return Response(UserSerializer(request.user, context={"request": request}).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def switch_organization(request: Request) -> Response:
    serializer = SwitchOrganizationSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    organization_id = serializer.validated_data["organization_id"]

    if not services.can_user_act_for_organization(request.user, organization_id):
        return Response(
            {"detail": "You do not have an active membership in that organization."},
            status=status.HTTP_403_FORBIDDEN,
        )

    request.session["organization_id"] = str(organization_id)
    return Response(UserSerializer(request.user, context={"request": request}).data)


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def organization_detail(request: Request) -> Response:
    """Settings → Organization surface.

    GET   returns the full Organization shape for the active org.
    PATCH applies edits via the allowlisted ``update_organization`` service.

    Active-org scoping is the user's session ``organization_id`` (set by
    the registration / login flow). A user with multiple memberships
    edits the org currently selected by the switch-organization endpoint.
    """
    organization_id = request.session.get("organization_id")
    if not organization_id:
        return Response(
            {"detail": "No active organization. Switch organization first."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not services.can_user_act_for_organization(request.user, organization_id):
        return Response(
            {"detail": "You are not a member of that organization."},
            status=status.HTTP_403_FORBIDDEN,
        )

    if request.method == "PATCH":
        if not isinstance(request.data, dict):
            return Response(
                {"detail": "Body must be a JSON object."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            org = services.update_organization(
                organization_id=organization_id,
                updates=request.data,
                actor_user_id=request.user.id,
            )
        except services.OrganizationUpdateError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(OrganizationDetailSerializer(org).data)

    org = services.get_organization(organization_id=organization_id)
    if org is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(OrganizationDetailSerializer(org).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def organization_members(request: Request) -> Response:
    """Settings → Members tab list.

    Lists active + inactive memberships for the active org. Any
    member can read; the customer-side write surface
    (``patch_organization_member``) is owner/admin-only.
    """
    organization_id = request.session.get("organization_id")
    if not organization_id:
        return Response(
            {"detail": "No active organization."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not services.can_user_act_for_organization(request.user, organization_id):
        return Response(
            {"detail": "You are not a member of that organization."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return Response(
        {"results": services.list_organization_members(organization_id=organization_id)}
    )


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def organization_api_keys(request: Request) -> Response:
    """Settings → API keys list + create.

    GET  → list of {id, label, key_prefix, is_active, ...} rows. NEVER
           returns plaintext — the customer sees only the prefix.
    POST → create a key. Body: {"label": "ci-pipeline"}. Response
           includes ``plaintext`` exactly ONCE; subsequent reads will
           never return it.
    """
    organization_id = request.session.get("organization_id")
    if not organization_id:
        return Response(
            {"detail": "No active organization."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not services.can_user_act_for_organization(request.user, organization_id):
        return Response(
            {"detail": "You are not a member of that organization."},
            status=status.HTTP_403_FORBIDDEN,
        )

    from . import api_keys as api_keys_service

    if request.method == "POST":
        body = request.data or {}
        try:
            row, plaintext = api_keys_service.create_api_key(
                organization_id=organization_id,
                label=str(body.get("label") or ""),
                actor_user=request.user,
            )
        except api_keys_service.APIKeyError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        # Plaintext is in the response body ONCE. Tests assert this is
        # the only place it appears.
        return Response(
            {
                "id": str(row.id),
                "label": row.label,
                "key_prefix": row.key_prefix,
                "is_active": True,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "plaintext": plaintext,
            },
            status=status.HTTP_201_CREATED,
        )

    return Response(
        {"results": api_keys_service.list_api_keys(organization_id=organization_id)}
    )


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def revoke_organization_api_key(request: Request, api_key_id: str) -> Response:
    """Soft-revoke an API key. Idempotent on already-revoked rows."""
    organization_id = request.session.get("organization_id")
    if not organization_id:
        return Response(
            {"detail": "No active organization."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not services.can_user_act_for_organization(request.user, organization_id):
        return Response(
            {"detail": "You are not a member of that organization."},
            status=status.HTTP_403_FORBIDDEN,
        )
    from . import api_keys as api_keys_service

    try:
        result = api_keys_service.revoke_api_key(
            organization_id=organization_id,
            api_key_id=api_key_id,
            actor_user=request.user,
        )
    except api_keys_service.APIKeyError as exc:
        msg = str(exc)
        if "not found" in msg:
            return Response({"detail": msg}, status=status.HTTP_404_NOT_FOUND)
        return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def patch_organization_member(request: Request, membership_id: str) -> Response:
    """Owner / admin updates another member's role or active state.

    Body: ``{"is_active": bool, "role_name": "owner|admin|..."}``
    (at least one). Customer-side path; for staff cross-tenant
    edits use ``/api/v1/admin/memberships/<id>/`` instead.
    """
    organization_id = request.session.get("organization_id")
    if not organization_id:
        return Response(
            {"detail": "No active organization."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not services.can_user_act_for_organization(request.user, organization_id):
        return Response(
            {"detail": "You are not a member of that organization."},
            status=status.HTTP_403_FORBIDDEN,
        )
    body = request.data or {}
    try:
        result = services.update_organization_member(
            organization_id=organization_id,
            membership_id=membership_id,
            actor_user=request.user,
            is_active=body.get("is_active"),
            role_name=body.get("role_name"),
        )
    except services.MembershipManagementError as exc:
        msg = str(exc)
        if "not found" in msg:
            return Response({"detail": msg}, status=status.HTTP_404_NOT_FOUND)
        if "Only" in msg or "cannot change" in msg or "not a member" in msg:
            return Response({"detail": msg}, status=status.HTTP_403_FORBIDDEN)
        return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)
