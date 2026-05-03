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
    email = serializer.validated_data["email"]
    user = authenticate(
        request,
        username=email,
        password=serializer.validated_data["password"],
    )
    if user is None or not user.is_active:
        # Slice 104 — Django's authenticate() catches the
        # ``PermissionDenied`` that ``AxesStandaloneBackend`` raises on
        # lockout and returns None — same shape as a bad password.
        # Disambiguate by asking axes directly so the locked-out user
        # gets a clear 403 + Retry-After instead of being told their
        # password is wrong (which they then try to "fix" with another
        # attempt — burning more lockout budget).
        from axes.handlers.proxy import AxesProxyHandler  # noqa: PLC0415

        if AxesProxyHandler.is_locked(request, credentials={"username": email}):
            from zerokey.middleware import get_request_id  # noqa: PLC0415

            response = Response(
                {
                    "error": {
                        "code": "account_locked",
                        "message": "Too many failed attempts. Try again later.",
                        "request_id": get_request_id(),
                    }
                },
                status=status.HTTP_403_FORBIDDEN,
            )
            # 15-minute cool-off matches AXES_COOLOFF_TIME in settings.
            response["Retry-After"] = "900"
            return response
        # The signal-handler still records auth.login_failed via Django's
        # user_login_failed signal, fired by ``authenticate`` on miss.
        return Response({"detail": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)

    # Slice 89 — if 2FA is enabled, defer login() until the
    # second factor is verified. Stash the user's id on the
    # session so /login/2fa/ can complete the auth without
    # re-asking for the password.
    if user.two_factor_enabled:
        request.session["pending_2fa_user_id"] = str(user.id)
        request.session["pending_2fa_email"] = user.email
        return Response(
            {"needs_2fa": True, "email": user.email},
            status=status.HTTP_200_OK,
        )

    # Set the active organization first so the auth signal handler attributes
    # the login event to the right tenant, then call login().
    memberships = services.memberships_for(user)
    if memberships:
        request.session["organization_id"] = str(memberships[0].organization_id)
    login(request, user)

    return Response(UserSerializer(user, context={"request": request}).data)


@api_view(["POST"])
@permission_classes([AllowAny])
def sso_initiate_view(request: Request) -> Response:
    """Slice 97 — start the OIDC dance for ``email``.

    Body: ``{"email": "user@example.com"}``. Returns the authorize
    URL the FE should redirect to. State / nonce / provider id are
    stashed in the session for the callback to verify.
    """
    from . import sso

    email = (request.data.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return Response(
            {"detail": "email is required."}, status=status.HTTP_400_BAD_REQUEST
        )
    try:
        info = sso.initiate(email=email, request=request)
    except sso.SsoError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"redirect_url": info.url, "state": info.state})


@api_view(["POST"])
@permission_classes([AllowAny])
def sso_callback_view(request: Request) -> Response:
    """Slice 97 — exchange ``code``, JIT-provision, complete login.

    Body: ``{"code": "<>", "state": "<>"}``. The FE collects these
    from the IdP's redirect query string and POSTs them here so we
    can complete the login under our own session machinery.
    """
    from django.contrib.auth import login as django_login

    from . import sso

    code = (request.data.get("code") or "").strip()
    state = (request.data.get("state") or "").strip()
    if not code or not state:
        return Response(
            {"detail": "code and state are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        user = sso.complete(request=request, code=code, state=state)
    except sso.SsoError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    # Pin the active org to the IdP's org (the user JIT-provisioned
    # there) so the next /me/ call returns the right tenant context.
    memberships = services.memberships_for(user)
    if memberships:
        request.session["organization_id"] = str(memberships[0].organization_id)
    django_login(request, user)
    return Response(UserSerializer(user, context={"request": request}).data)


@api_view(["GET", "POST", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def sso_provider_view(request: Request) -> Response:
    """Slice 97 — manage the active org's OIDC provider.

    Owner / Admin only — others 403. One provider per org today
    (unique constraint), so:

      GET     returns the current provider or null
      POST    creates a provider (409 if one already exists)
      PATCH   updates the existing provider
      DELETE  removes the provider (re-enables password auth only)

    ``client_secret`` is write-only — the GET response returns
    presence-only ("set" / "unset") rather than the plaintext.
    """
    from .models import OidcProvider

    organization_id = request.session.get("organization_id")
    if not organization_id:
        return Response({"detail": "No active organization."}, status=status.HTTP_400_BAD_REQUEST)

    membership = (
        request.user.memberships.filter(organization_id=organization_id).first()
    )
    if membership is None or membership.role.name not in {"owner", "admin"}:
        return Response(
            {"detail": "Only owners or admins can manage SSO."},
            status=status.HTTP_403_FORBIDDEN,
        )

    provider = OidcProvider.objects.filter(organization_id=organization_id).first()

    def serialize(p: OidcProvider | None) -> dict:
        if p is None:
            return {"provider": None}
        return {
            "provider": {
                "id": str(p.id),
                "label": p.label,
                "is_active": p.is_active,
                "issuer": p.issuer,
                "client_id": p.client_id,
                "client_secret_set": bool(p.client_secret),
                "scopes": p.scopes,
                "allowed_email_domains": list(p.allowed_email_domains or []),
                "jit_provision": p.jit_provision,
                "default_role": p.default_role.name if p.default_role else None,
                "last_login_at": p.last_login_at.isoformat() if p.last_login_at else None,
            }
        }

    if request.method == "GET":
        return Response(serialize(provider))

    body = request.data if isinstance(request.data, dict) else {}

    if request.method == "DELETE":
        if provider is None:
            return Response({"provider": None})
        provider.delete()
        return Response({"provider": None})

    if request.method == "POST":
        if provider is not None:
            return Response(
                {"detail": "A provider already exists for this organization. Use PATCH."},
                status=status.HTTP_409_CONFLICT,
            )
        from .models import Role

        role = None
        role_name = body.get("default_role") or "submitter"
        role = Role.objects.filter(name=role_name).first()
        provider = OidcProvider.objects.create(
            organization_id=organization_id,
            label=str(body.get("label") or "OIDC SSO")[:64],
            is_active=bool(body.get("is_active", True)),
            issuer=str(body.get("issuer") or "")[:512],
            client_id=str(body.get("client_id") or "")[:255],
            client_secret=str(body.get("client_secret") or ""),
            scopes=str(body.get("scopes") or "openid email profile")[:512],
            allowed_email_domains=list(body.get("allowed_email_domains") or []),
            jit_provision=bool(body.get("jit_provision", True)),
            default_role=role,
        )
        return Response(serialize(provider), status=status.HTTP_201_CREATED)

    # PATCH
    if provider is None:
        return Response({"detail": "No provider configured. POST first."}, status=status.HTTP_404_NOT_FOUND)
    for field in ("label", "issuer", "client_id", "scopes"):
        if field in body and body[field] is not None:
            setattr(provider, field, str(body[field])[:512])
    if "client_secret" in body and body["client_secret"] is not None:
        # Empty string clears the secret (PKCE-only flows); non-empty
        # rotates it.
        provider.client_secret = str(body["client_secret"])
    if "is_active" in body:
        provider.is_active = bool(body["is_active"])
    if "jit_provision" in body:
        provider.jit_provision = bool(body["jit_provision"])
    if "allowed_email_domains" in body and isinstance(body["allowed_email_domains"], list):
        provider.allowed_email_domains = list(body["allowed_email_domains"])
    if "default_role" in body and body["default_role"]:
        from .models import Role

        role = Role.objects.filter(name=body["default_role"]).first()
        if role:
            provider.default_role = role
    provider.save()
    return Response(serialize(provider))


@api_view(["POST"])
@permission_classes([AllowAny])
def login_2fa_view(request: Request) -> Response:
    """Complete login after a TOTP / recovery-code challenge (Slice 89)."""
    from .models import User
    from .totp import decrypt_secret, verify_and_consume_recovery_code, verify_code

    user_id = request.session.get("pending_2fa_user_id")
    if not user_id:
        return Response(
            {"detail": "No 2FA challenge in progress. Sign in first."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    user = User.objects.filter(id=user_id, is_active=True).first()
    if user is None:
        return Response({"detail": "Session expired."}, status=status.HTTP_400_BAD_REQUEST)

    code = str((request.data or {}).get("code") or "").strip()
    if not code:
        return Response({"detail": "code is required."}, status=status.HTTP_400_BAD_REQUEST)

    secret = decrypt_secret(user.totp_secret_encrypted)
    ok = verify_code(secret_b32=secret, code=code)
    if not ok:
        # Try the recovery code path. Single-use; consume on match.
        if verify_and_consume_recovery_code(user=user, code=code):
            user.save(update_fields=["totp_recovery_hashes"])
            ok = True

    if not ok:
        return Response({"detail": "Invalid code."}, status=status.HTTP_401_UNAUTHORIZED)

    # Clear challenge state, complete the login.
    request.session.pop("pending_2fa_user_id", None)
    request.session.pop("pending_2fa_email", None)
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


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def onboarding_view(request: Request) -> Response:
    """Get + dismiss the post-signup onboarding checklist (Slice 92).

    GET returns the checklist state: which items are already done
    (derived from real data — uploaded a certificate, configured
    inbox token, has invited a teammate, has any IngestionJob),
    plus whether the user has dismissed the checklist.

    POST dismisses it. The checklist hides for this user from now on
    even if not every step is done — power users want to get rid of
    it.
    """
    from datetime import datetime, timezone as _tz

    from apps.ingestion.models import IngestionJob

    organization_id = request.session.get("organization_id")
    if not organization_id:
        return Response({"detail": "No active organization."}, status=status.HTTP_400_BAD_REQUEST)

    org = services.get_organization(organization_id=organization_id)
    if org is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == "POST":
        if request.user.onboarding_dismissed_at is None:
            request.user.onboarding_dismissed_at = datetime.now(_tz.utc)
            request.user.save(update_fields=["onboarding_dismissed_at"])
        return Response({"dismissed_at": request.user.onboarding_dismissed_at.isoformat()})

    # Derive each step's done-state from existing data so the checklist
    # never goes stale. No new "is_done" columns to maintain.
    has_certificate = bool(org.certificate_uploaded)
    has_inbox_token = bool(org.inbox_token)
    member_count = len(services.list_organization_members(organization_id=organization_id))
    has_invited = member_count > 1
    has_uploaded = IngestionJob.objects.filter(organization_id=organization_id).exists()
    has_2fa = bool(request.user.two_factor_enabled)

    return Response(
        {
            "dismissed_at": (
                request.user.onboarding_dismissed_at.isoformat()
                if request.user.onboarding_dismissed_at
                else None
            ),
            "steps": [
                {
                    "key": "upload_certificate",
                    "title": "Upload your LHDN signing certificate",
                    "why": "ZeroKey signs every invoice with your LHDN-issued certificate before submission. Without it, we can't talk to MyInvois on your behalf.",
                    "where": "/dashboard/settings",
                    "done": has_certificate,
                },
                {
                    "key": "configure_inbox",
                    "title": "Set up your inbox-forward address",
                    "why": "Forward supplier invoices to a unique ZeroKey email address and they land in your dashboard automatically — no upload step needed.",
                    "where": "/dashboard/settings",
                    "done": has_inbox_token,
                },
                {
                    "key": "first_upload",
                    "title": "Upload your first invoice",
                    "why": "See the full pipeline in action: extraction, validation, signing, submission. The dashboard's drop zone accepts PDF, image, Excel, CSV, or ZIP.",
                    "where": "/dashboard",
                    "done": has_uploaded,
                },
                {
                    "key": "invite_teammate",
                    "title": "Invite a teammate",
                    "why": "Most businesses don't have one person handling everything. Invite an Approver or Submitter so submissions don't bottleneck on you.",
                    "where": "/dashboard/settings",
                    "done": has_invited,
                },
                {
                    "key": "enable_2fa",
                    "title": "Turn on two-factor authentication",
                    "why": "Your account holds an LHDN signing certificate — anyone with your password could submit invoices in your company's name. Add a second factor.",
                    "where": "/dashboard/settings",
                    "done": has_2fa,
                },
            ],
        }
    )


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


# --- Slice 89 — TOTP 2FA enrollment / disable ---------------------------


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def two_factor_enroll(request: Request) -> Response:
    """Mint a fresh TOTP secret + provisioning URI for the user.

    Does NOT enable 2FA yet — the user must POST a valid code
    to ``/2fa/confirm/`` before ``two_factor_enabled`` flips True.
    Re-calling this overwrites any half-finished enrollment, which
    is what the user wants if they lost their previous QR.
    """
    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event

    from . import totp

    plain, encrypted = totp.generate_secret_encrypted()
    request.user.totp_secret_encrypted = encrypted
    # Pre-confirmation: do NOT touch two_factor_enabled or
    # totp_recovery_hashes. Enabling without confirmation would
    # lock the user out on next login.
    request.user.save(update_fields=["totp_secret_encrypted"])

    record_event(
        action_type="identity.2fa.enroll_started",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(request.user.id),
        organization_id=request.session.get("organization_id"),
        affected_entity_type="User",
        affected_entity_id=str(request.user.id),
        payload={},
    )

    uri = totp.provisioning_uri(account_email=request.user.email, secret_b32=plain)
    return Response({"secret": plain, "provisioning_uri": uri})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def two_factor_confirm(request: Request) -> Response:
    """Verify a TOTP code, flip 2FA on, mint recovery codes."""
    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event

    from . import totp

    code = str((request.data or {}).get("code") or "").strip()
    if not code:
        return Response({"detail": "code is required."}, status=status.HTTP_400_BAD_REQUEST)
    if not request.user.totp_secret_encrypted:
        return Response(
            {"detail": "2FA enrollment hasn't been started."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    secret = totp.decrypt_secret(request.user.totp_secret_encrypted)
    if not totp.verify_code(secret_b32=secret, code=code):
        return Response({"detail": "Invalid code."}, status=status.HTTP_400_BAD_REQUEST)

    plain_codes = totp.generate_recovery_codes()
    request.user.totp_recovery_hashes = [totp.hash_recovery_code(c) for c in plain_codes]
    request.user.two_factor_enabled = True
    request.user.save(update_fields=["two_factor_enabled", "totp_recovery_hashes"])

    # Slice 104 — SECURITY.md "rotated on privilege escalation".
    # Enabling 2FA changes the trust level of this session, so cycle
    # the session key. cycle_key() preserves the session data
    # (organization_id, etc.) but issues a fresh session id, which
    # invalidates any leaked / fixated id from before the upgrade.
    request.session.cycle_key()

    record_event(
        action_type="identity.2fa.enabled",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(request.user.id),
        organization_id=request.session.get("organization_id"),
        affected_entity_type="User",
        affected_entity_id=str(request.user.id),
        payload={"recovery_codes_minted": len(plain_codes)},
    )

    # Recovery codes are surfaced exactly once. The user must
    # save them now; we never re-show them.
    return Response({"ok": True, "recovery_codes": plain_codes})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def two_factor_disable(request: Request) -> Response:
    """Disable 2FA — requires a current TOTP or recovery code."""
    from apps.audit.models import AuditEvent
    from apps.audit.services import record_event

    from . import totp

    if not request.user.two_factor_enabled:
        return Response({"detail": "2FA is not enabled."}, status=status.HTTP_400_BAD_REQUEST)
    code = str((request.data or {}).get("code") or "").strip()
    if not code:
        return Response({"detail": "code is required."}, status=status.HTTP_400_BAD_REQUEST)

    secret = totp.decrypt_secret(request.user.totp_secret_encrypted)
    ok = totp.verify_code(secret_b32=secret, code=code)
    if not ok:
        ok = totp.verify_and_consume_recovery_code(user=request.user, code=code)
    if not ok:
        return Response({"detail": "Invalid code."}, status=status.HTTP_401_UNAUTHORIZED)

    request.user.two_factor_enabled = False
    request.user.totp_secret_encrypted = ""
    request.user.totp_recovery_hashes = []
    request.user.save(
        update_fields=[
            "two_factor_enabled",
            "totp_secret_encrypted",
            "totp_recovery_hashes",
        ]
    )

    # Slice 104 — same rotation rationale as 2fa-confirm: changing the
    # account's auth requirements is a privilege-level change.
    request.session.cycle_key()

    record_event(
        action_type="identity.2fa.disabled",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(request.user.id),
        organization_id=request.session.get("organization_id"),
        affected_entity_type="User",
        affected_entity_id=str(request.user.id),
        payload={},
    )
    return Response({"ok": True})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def feature_flags_view(request: Request) -> Response:
    """Return ``{slug: enabled}`` for every declared flag, resolved for the active org.

    Frontend uses the map to gate UI surfaces (hide the SSO settings
    tab if ``sso`` is off, hide the multi-entity dashboard if
    ``multi_entity_dashboard`` is off, etc.).
    """
    organization_id = request.session.get("organization_id")
    if not organization_id:
        return Response({"flags": {}})
    from apps.billing.services import resolved_feature_flags

    return Response({"flags": resolved_feature_flags(organization_id=organization_id)})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def global_search_view(request: Request) -> Response:
    """Cross-domain search for the topbar Cmd-K-style input.

    Slice 101 — returns up to 5 hits per category:
      - invoices  (by invoice_number / supplier / buyer)
      - customers (by legal_name / TIN)
      - audit     (by action_type or affected entity id)

    Tenant-scoped via the active org context. Empty query → empty.
    """
    organization_id = request.session.get("organization_id")
    if not organization_id:
        return Response({"invoices": [], "customers": [], "audit": []})

    q = (request.query_params.get("q") or "").strip()
    if len(q) < 2:
        return Response({"invoices": [], "customers": [], "audit": []})

    from django.db.models import Q

    from apps.audit.models import AuditEvent
    from apps.enrichment.models import CustomerMaster
    from apps.submission.models import Invoice

    # Pull a slightly wider candidate set then dedupe by
    # (invoice_number, supplier, buyer) so a customer who uploaded the
    # same PDF many times sees ONE hit per logical invoice. The most
    # recent row wins (we sort by -created_at). Slice 102 — fixes the
    # UX-walk finding where searching "IV" returned 5 identical
    # "IV-1605-003" rows.
    raw_invoices = list(
        Invoice.objects.filter(
            organization_id=organization_id,
        )
        .filter(
            Q(invoice_number__icontains=q)
            | Q(supplier_legal_name__icontains=q)
            | Q(buyer_legal_name__icontains=q)
        )
        .order_by("-created_at")[:25]
    )
    seen: set[tuple[str, str, str]] = set()
    invoices: list[Invoice] = []
    for inv in raw_invoices:
        key = (
            (inv.invoice_number or "").strip().lower(),
            (inv.supplier_legal_name or "").strip().lower(),
            (inv.buyer_legal_name or "").strip().lower(),
        )
        # Empty-key invoices (no number, no parties) are kept distinct
        # so blank-extraction rows don't all collapse into one mystery row.
        if key != ("", "", "") and key in seen:
            continue
        seen.add(key)
        invoices.append(inv)
        if len(invoices) >= 5:
            break
    customers = list(
        CustomerMaster.objects.filter(organization_id=organization_id)
        .filter(Q(legal_name__icontains=q) | Q(tin__icontains=q))
        .order_by("legal_name")[:5]
    )
    audit = list(
        AuditEvent.objects.filter(organization_id=organization_id)
        .filter(
            Q(action_type__icontains=q)
            | Q(affected_entity_id__icontains=q)
            | Q(actor_id__icontains=q)
        )
        .order_by("-timestamp")[:5]
    )

    return Response(
        {
            "query": q,
            "invoices": [
                {
                    "id": str(inv.id),
                    "invoice_number": inv.invoice_number or "",
                    "supplier_legal_name": inv.supplier_legal_name,
                    "buyer_legal_name": inv.buyer_legal_name,
                    "status": inv.status,
                    "grand_total": str(inv.grand_total) if inv.grand_total is not None else "",
                    "currency_code": inv.currency_code,
                    "ingestion_job_id": str(inv.ingestion_job_id) if inv.ingestion_job_id else "",
                }
                for inv in invoices
            ],
            "customers": [
                {
                    "id": str(c.id),
                    "legal_name": c.legal_name,
                    "tin": c.tin,
                }
                for c in customers
            ],
            "audit": [
                {
                    "id": str(e.id),
                    "sequence": int(e.sequence) if hasattr(e, "sequence") else 0,
                    "action_type": e.action_type,
                    "occurred_at": e.timestamp.isoformat() if e.timestamp else None,
                    "affected_entity_type": e.affected_entity_type,
                    "affected_entity_id": e.affected_entity_id,
                }
                for e in audit
            ],
        }
    )
