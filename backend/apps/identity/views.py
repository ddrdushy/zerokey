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


# Slice 86 — locale supported by ZeroKey's i18n scaffold. Keep this
# list aligned with frontend/src/lib/i18n.ts SUPPORTED_LOCALES.
SUPPORTED_LOCALES = frozenset({"en-MY", "bm-MY", "zh-MY", "ta-MY"})


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def update_preferences(request: Request) -> Response:
    """Update the active user's UI preferences (Slice 86).

    Currently accepts ``preferred_language`` only. Other UI
    preferences will share this endpoint as we add them.
    """
    body = request.data or {}
    if not isinstance(body, dict):
        return Response(
            {"detail": "Body must be a JSON object."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    changed = []
    if "preferred_language" in body:
        lang = str(body["preferred_language"] or "").strip()
        if lang not in SUPPORTED_LOCALES:
            return Response(
                {
                    "detail": (
                        f"preferred_language must be one of {sorted(SUPPORTED_LOCALES)}; got {lang!r}."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if request.user.preferred_language != lang:
            request.user.preferred_language = lang
            request.user.save(update_fields=["preferred_language"])
            changed.append("preferred_language")

    return Response(
        {
            "ok": True,
            "changed_fields": changed,
            "preferred_language": request.user.preferred_language,
        }
    )


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

    return Response({"results": api_keys_service.list_api_keys(organization_id=organization_id)})


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def notification_preferences(request: Request) -> Response:
    """Settings → Notifications. Per-user, per-tenant event preferences.

    GET   returns ``{events: [{key, label, description, in_app, email}, ...]}``.
    PATCH accepts ``{"<event_key>": {"in_app": bool, "email": bool}, ...}``.
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

    from . import notifications as notif_service

    if request.method == "PATCH":
        body = request.data or {}
        try:
            result = notif_service.set_preferences(
                organization_id=organization_id,
                user=request.user,
                updates=body,
            )
        except notif_service.NotificationPreferenceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)

    return Response(
        notif_service.get_preferences(organization_id=organization_id, user=request.user)
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


# --- Slice 56: Membership invitations -----------------------------------


def _is_owner_or_admin(user, organization_id) -> bool:
    """Active owner/admin in the org."""
    from .models import OrganizationMembership

    return OrganizationMembership.objects.filter(
        user=user,
        organization_id=organization_id,
        is_active=True,
        role__name__in=["owner", "admin"],
    ).exists()


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def organization_invitations(request: Request) -> Response:
    """Settings → Members → invitations.

    GET → list (any active member can read).
    POST → create (owner / admin only). Body:
        {"email": "...", "role_name": "viewer|submitter|approver|admin"}
    Returns the new row + the plaintext invitation URL fragment in
    ``invitation_url`` so the FE can show it once + offer a copy
    button. The plaintext token never persists; only the SHA-256
    hash is stored.
    """
    from . import invitations as inv_service

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

    if request.method == "GET":
        return Response(
            {"results": inv_service.list_pending_invitations(organization_id=organization_id)}
        )

    # POST
    if not _is_owner_or_admin(request.user, organization_id):
        return Response(
            {"detail": "Only owners and admins can invite members."},
            status=status.HTTP_403_FORBIDDEN,
        )
    body = request.data or {}
    try:
        invitation, plaintext_token = inv_service.create_invitation(
            organization_id=organization_id,
            email=str(body.get("email") or "").strip(),
            role_name=str(body.get("role_name") or "").strip(),
            actor_user_id=request.user.id,
        )
    except inv_service.InvitationError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    # Best-effort email send. Failure must NOT roll back the invite —
    # the inviter can copy the link out of the response if SMTP is
    # down. The audit trail records the invitation creation regardless.
    accept_url = (
        f"{request.build_absolute_uri('/').rstrip('/')}/accept-invitation?token={plaintext_token}"
    )
    try:
        from apps.notifications.email import is_email_configured, send_email

        if is_email_configured():
            send_email(
                to=invitation.email,
                subject=("You've been invited to ZeroKey"),
                body=(
                    f"You've been invited to join ZeroKey on the "
                    f"{invitation.role.name} role.\n\n"
                    f"Accept the invitation:\n{accept_url}\n\n"
                    f"This link expires in 14 days.\n\n— ZeroKey"
                ),
            )
    except Exception:
        pass

    return Response(
        {
            **inv_service._invitation_dict(invitation),
            "invitation_url": accept_url,
            "plaintext_token": plaintext_token,
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def revoke_organization_invitation(request: Request, invitation_id: str) -> Response:
    """Cancel a pending invitation. Owner / admin only."""
    from . import invitations as inv_service

    organization_id = request.session.get("organization_id")
    if not organization_id:
        return Response(
            {"detail": "No active organization."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not _is_owner_or_admin(request.user, organization_id):
        return Response(
            {"detail": "Only owners and admins can revoke invitations."},
            status=status.HTTP_403_FORBIDDEN,
        )
    try:
        invitation = inv_service.revoke_invitation(
            organization_id=organization_id,
            invitation_id=invitation_id,
            actor_user_id=request.user.id,
            reason=str((request.data or {}).get("reason") or ""),
        )
    except inv_service.InvitationError as exc:
        msg = str(exc)
        if "not found" in msg:
            return Response({"detail": msg}, status=status.HTTP_404_NOT_FOUND)
        return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)
    return Response(inv_service._invitation_dict(invitation))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def accept_invitation_view(request: Request) -> Response:
    """Accept an invitation as the currently-signed-in user.

    Body: ``{"token": "<plaintext>"}``. The accepting user's email
    must match the invited email. On success, the new membership is
    created + the user's session ``organization_id`` is set so they
    immediately see the new org.
    """
    from . import invitations as inv_service

    body = request.data or {}
    token = str(body.get("token") or "").strip()
    try:
        membership = inv_service.accept_invitation(token=token, accepting_user_id=request.user.id)
    except inv_service.InvitationError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    request.session["organization_id"] = str(membership.organization_id)
    return Response(
        {
            "membership_id": str(membership.id),
            "organization_id": str(membership.organization_id),
            "role": membership.role.name,
            "redirect_to": "/dashboard",
        }
    )


@api_view(["POST"])
@permission_classes([])
def preview_invitation_view(request: Request) -> Response:
    """Anonymous preview: "what does this invitation token look like?"

    Used by the /accept-invitation landing page so a not-yet-signed-in
    user sees the org name + role being offered before they sign up
    or log in. Returns a 404 for invalid / expired tokens (no info
    leak about what's pending).

    Body: ``{"token": "<plaintext>"}``.
    """
    from . import invitations as inv_service
    from .models import MembershipInvitation, Organization
    from .tenancy import super_admin_context

    token = str((request.data or {}).get("token") or "").strip()
    if not token:
        return Response({"detail": "Missing token."}, status=status.HTTP_400_BAD_REQUEST)

    token_hash = inv_service._hash_token(token)
    with super_admin_context(reason="invitations.preview"):
        invitation = (
            MembershipInvitation.objects.select_related("role")
            .filter(token_hash=token_hash)
            .first()
        )
        if invitation is None:
            return Response(
                {"detail": "Invitation not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        org = Organization.objects.filter(id=invitation.organization_id).first()

    if invitation.status != MembershipInvitation.Status.PENDING:
        return Response(
            {"detail": f"Invitation is {invitation.status}."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return Response(
        {
            "email": invitation.email,
            "role": invitation.role.name,
            "organization_legal_name": org.legal_name if org else "",
            "expires_at": invitation.expires_at.isoformat(),
        }
    )


# --- Slice 57: Per-org integrations -------------------------------------


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def organization_integrations(request: Request) -> Response:
    """Settings → Integrations card list for the active org.

    Read is open to any active member (so viewers see the
    configured-state); writes are owner / admin only via the
    other endpoints.
    """
    from .integrations import list_integrations_for_org

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
    return Response({"results": list_integrations_for_org(organization_id=organization_id)})


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def organization_integration_credentials(request: Request, integration_key: str) -> Response:
    """Patch one environment's credential set.

    Body: ``{"environment": "sandbox|production", "fields": {...}}``
    """
    from . import integrations as integ_service

    organization_id = request.session.get("organization_id")
    if not organization_id:
        return Response(
            {"detail": "No active organization."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not _is_owner_or_admin(request.user, organization_id):
        return Response(
            {"detail": "Only owners and admins can change integration credentials."},
            status=status.HTTP_403_FORBIDDEN,
        )

    body = request.data or {}
    environment = str(body.get("environment") or "").strip()
    fields = body.get("fields") or {}
    if not isinstance(fields, dict):
        return Response(
            {"detail": "fields must be an object."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        result = integ_service.upsert_credentials(
            organization_id=organization_id,
            integration_key=integration_key,
            environment=environment,
            field_updates={k: str(v) if v is not None else "" for k, v in fields.items()},
            actor_user_id=request.user.id,
        )
    except integ_service.IntegrationConfigError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def organization_integration_active_environment(request: Request, integration_key: str) -> Response:
    """Flip the integration between sandbox + production.

    Body: ``{"environment": "sandbox|production", "reason": "..."}``
    """
    from . import integrations as integ_service

    organization_id = request.session.get("organization_id")
    if not organization_id:
        return Response(
            {"detail": "No active organization."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not _is_owner_or_admin(request.user, organization_id):
        return Response(
            {"detail": "Only owners and admins can switch environments."},
            status=status.HTTP_403_FORBIDDEN,
        )
    body = request.data or {}
    try:
        result = integ_service.set_active_environment(
            organization_id=organization_id,
            integration_key=integration_key,
            environment=str(body.get("environment") or "").strip(),
            actor_user_id=request.user.id,
            reason=str(body.get("reason") or ""),
        )
    except integ_service.IntegrationConfigError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def organization_integration_test(request: Request, integration_key: str) -> Response:
    """Run the test-connection probe for one environment.

    Body: ``{"environment": "sandbox|production"}``. Returns
    ``{"ok": bool, "detail": str, "duration_ms": int}``.
    """
    from . import integrations as integ_service

    organization_id = request.session.get("organization_id")
    if not organization_id:
        return Response(
            {"detail": "No active organization."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not _is_owner_or_admin(request.user, organization_id):
        return Response(
            {"detail": "Only owners and admins can test integrations."},
            status=status.HTTP_403_FORBIDDEN,
        )
    body = request.data or {}
    try:
        outcome = integ_service.test_connection(
            organization_id=organization_id,
            integration_key=integration_key,
            environment=str(body.get("environment") or "").strip(),
            actor_user_id=request.user.id,
        )
    except integ_service.IntegrationConfigError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(
        {
            "ok": outcome.ok,
            "detail": outcome.detail,
            "duration_ms": outcome.duration_ms,
        }
    )


# --- Slice 59B: LHDN signing certificate ----------------------------------


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def organization_certificate(request: Request) -> Response:
    """Read + upload the org's LHDN signing certificate.

    GET → returns the current cert state (kind, expiry, subject,
    serial). Never returns the PEM material itself; the cert is
    write-only via this surface (matches the API key + webhook
    secret contract).

    POST → upload a cert. Two body shapes accepted:

      PEM (cert + key separately):
        {
          "cert_pem": "-----BEGIN CERTIFICATE-----\n...",
          "private_key_pem": "-----BEGIN PRIVATE KEY-----\n..."
        }

      PFX / P12 (CA-delivered single bundle):
        {
          "pfx_b64": "<base64-encoded .pfx bytes>",
          "pfx_password": "<bundle passphrase>"
        }

    Owner / admin only. Validates matched RSA pair before
    persisting; returns 400 with an explanatory message on
    parsing, password, or pairing failure.

    Note: a self-signed dev cert is auto-minted on the first
    LHDN sign attempt (Slice 58 ``ensure_certificate``) so the
    customer never has to upload anything to test the flow.
    Uploading replaces that with a real LHDN-issued cert.
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

    from .models import Organization
    from .tenancy import super_admin_context

    if request.method == "GET":
        with super_admin_context(reason="identity.cert.read"):
            org = Organization.objects.filter(id=organization_id).first()
        if org is None:
            return Response(
                {"detail": "Organization not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            {
                "uploaded": bool(org.certificate_uploaded),
                "kind": org.certificate_kind or "",
                "subject_common_name": org.certificate_subject_common_name or "",
                "serial_hex": org.certificate_serial_hex or "",
                "expires_at": (
                    org.certificate_expiry_date.isoformat() if org.certificate_expiry_date else None
                ),
            }
        )

    # POST — upload a cert.
    if not _is_owner_or_admin(request.user, organization_id):
        return Response(
            {"detail": "Only owners and admins can upload certificates."},
            status=status.HTTP_403_FORBIDDEN,
        )
    body = request.data or {}
    pfx_b64 = str(body.get("pfx_b64") or "").strip()
    cert_pem = str(body.get("cert_pem") or "").strip()
    private_key_pem = str(body.get("private_key_pem") or "").strip()

    from apps.submission.certificates import (
        CertificateError,
        pfx_to_pem,
        upload_certificate,
    )

    if pfx_b64:
        # PFX / P12 path — unwrap to PEM, then funnel into the
        # standard upload path so the matched-pair check + audit
        # + persistence are identical.
        import base64
        import binascii

        try:
            pfx_bytes = base64.b64decode(pfx_b64, validate=True)
        except (binascii.Error, ValueError):
            return Response(
                {"detail": "pfx_b64 is not valid base64."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        password = str(body.get("pfx_password") or "")
        try:
            cert_pem, private_key_pem = pfx_to_pem(pfx_bytes=pfx_bytes, password=password)
        except CertificateError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    elif not cert_pem or not private_key_pem:
        return Response(
            {
                "detail": (
                    "Provide either pfx_b64 (+ pfx_password) or both cert_pem and private_key_pem."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        result = upload_certificate(
            organization_id=organization_id,
            cert_pem=cert_pem,
            private_key_pem=private_key_pem,
            actor_user_id=request.user.id,
        )
    except CertificateError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(
        {
            "uploaded": True,
            **result,
        }
    )
