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
