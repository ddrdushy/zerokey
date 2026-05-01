"""OIDC SSO flow (Slice 97).

Public surface:

  ``initiate(*, email, request) -> RedirectInfo`` —
    pick the right OidcProvider for ``email`` (by org allowed-domains
    or org TIN lookup), build the authorize URL, stash state + nonce
    + provider id in the session, return ``(url, state)``.

  ``complete(*, request, code, state) -> User`` —
    exchange the authorization ``code`` for tokens against the IdP,
    validate the ID token, JIT-provision User + Membership if
    configured, return the User. Caller is responsible for
    ``django.contrib.auth.login(request, user)`` and setting the
    session's ``organization_id``.

Why authlib instead of rolling our own:

  - JOSE-spec JWT verification (RS256/EC + JWKS rotation) is fiddly
    enough that mistakes have leaked tokens in the wild. authlib's
    JWT verifier is in active CVE coverage; ours wouldn't be.
  - OIDC discovery + token-exchange + nonce semantics are well-
    trodden ground; rebuilding is busywork.

What we do NOT use authlib for:

  - Session storage: we use Django's session (``request.session``)
    rather than authlib's session-backed Flask wrapper.
  - User model: JIT-provisioning is our model layer, not authlib's.

Dev / test note: the flow has been smoke-tested end-to-end against
Google's OIDC discovery (https://accounts.google.com/.well-known/
openid-configuration) — register a Web app in Google Cloud Console,
set the redirect URI to ``http://localhost:3000/sign-in/callback``,
paste the client_id + client_secret into Settings → SSO, sign in
with the test domain.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
from django.conf import settings
from django.utils import timezone

from .models import OidcProvider, OrganizationMembership, Role, User

logger = logging.getLogger(__name__)


# Scope strings beyond what the operator configured. ``openid`` MUST
# be present per spec; we always send it even if the admin omitted
# it from the scopes string.
_REQUIRED_SCOPES = frozenset({"openid"})


# Discovery cache — process-local, with no TTL because the OIDC
# discovery doc changes rarely (once per IdP key rotation, typically
# annual). On the rare occasions it does change, restart the
# backend. Belt-and-suspenders: authlib JWT verifier rejects expired
# keys regardless of cache freshness.
_DISCOVERY_CACHE: dict[str, dict[str, Any]] = {}


@dataclass(frozen=True)
class RedirectInfo:
    """``url`` to redirect the browser to + ``state`` to verify on callback."""

    url: str
    state: str
    provider_id: str


class SsoError(Exception):
    """Surfaced to the FE as a clean 400 with the error string."""


def _discover(issuer: str) -> dict[str, Any]:
    """Fetch + cache the OIDC discovery document for ``issuer``."""
    if issuer in _DISCOVERY_CACHE:
        return _DISCOVERY_CACHE[issuer]
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url)
            resp.raise_for_status()
            doc = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SsoError(f"OIDC discovery failed for {issuer}: {exc}") from exc
    _DISCOVERY_CACHE[issuer] = doc
    return doc


def _matches_email_domain(email: str, allowed: list[str]) -> bool:
    """Empty allowlist → any email; otherwise match by suffix."""
    if not allowed:
        return True
    domain = (email.split("@")[-1] or "").lower()
    return any(domain == d.lower().lstrip("@") for d in allowed)


def _find_provider(email: str) -> OidcProvider:
    """Pick the OidcProvider that should handle ``email``.

    v1 strategy: walk all active providers, pick the first whose
    ``allowed_email_domains`` matches the email's domain. If no
    domain allowlist is set on a provider, it accepts any email —
    so a provider with no allowlist becomes the catch-all.

    Multiple providers with overlapping allowlists is operator
    error; first match wins (ordered by created_at). When a real
    customer hits this we add an org-picker UI.
    """
    from apps.identity.tenancy import super_admin_context

    with super_admin_context(reason="sso.provider_lookup"):
        providers = list(
            OidcProvider.objects.filter(is_active=True).order_by("created_at")
        )
        for p in providers:
            if _matches_email_domain(email, list(p.allowed_email_domains or [])):
                return p
    raise SsoError(
        "No SSO provider matches this email. Ask your administrator to add one or sign in with a password."
    )


def initiate(*, email: str, request) -> RedirectInfo:
    """Begin the OIDC dance. Returns the IdP authorize URL."""
    provider = _find_provider(email)
    discovery = _discover(provider.issuer)
    authorize_endpoint = discovery.get("authorization_endpoint")
    if not authorize_endpoint:
        raise SsoError("IdP discovery doc missing authorization_endpoint.")

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)

    # The ``redirect_uri`` we register with the IdP must match exactly
    # what the IdP returns to. Pulled from settings so dev / staging /
    # prod each register their own. SSO_REDIRECT_URI defaults to the
    # frontend's expected callback page.
    redirect_uri = getattr(settings, "SSO_REDIRECT_URI", "http://localhost:3000/sign-in/callback")

    scopes = " ".join(set((provider.scopes or "").split()) | _REQUIRED_SCOPES)
    params = {
        "client_id": provider.client_id,
        "response_type": "code",
        "scope": scopes,
        "redirect_uri": redirect_uri,
        "state": state,
        "nonce": nonce,
    }
    url = f"{authorize_endpoint}?{urlencode(params)}"

    # Stash the bits we'll need at callback time in the session.
    # Cleared at completion or on error — never long-lived.
    request.session["sso_state"] = state
    request.session["sso_nonce"] = nonce
    request.session["sso_provider_id"] = str(provider.id)
    request.session["sso_email_hint"] = email

    return RedirectInfo(url=url, state=state, provider_id=str(provider.id))


def complete(*, request, code: str, state: str) -> User:
    """Exchange ``code`` for tokens, validate, JIT-provision, return User."""
    expected_state = request.session.get("sso_state")
    if not expected_state or state != expected_state:
        raise SsoError("State mismatch — possible CSRF.")
    provider_id = request.session.get("sso_provider_id")
    nonce = request.session.get("sso_nonce")
    if not provider_id or not nonce:
        raise SsoError("SSO session expired. Please retry.")

    from apps.identity.tenancy import super_admin_context

    with super_admin_context(reason="sso.callback"):
        try:
            provider = OidcProvider.objects.get(id=provider_id, is_active=True)
        except OidcProvider.DoesNotExist as exc:
            raise SsoError("Provider has been disabled. Contact your admin.") from exc
        organization_id = provider.organization_id
        default_role = provider.default_role

    discovery = _discover(provider.issuer)
    token_endpoint = discovery.get("token_endpoint")
    jwks_uri = discovery.get("jwks_uri")
    if not (token_endpoint and jwks_uri):
        raise SsoError("IdP discovery doc missing token_endpoint or jwks_uri.")

    redirect_uri = getattr(settings, "SSO_REDIRECT_URI", "http://localhost:3000/sign-in/callback")
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": provider.client_id,
    }
    if provider.client_secret:
        payload["client_secret"] = provider.client_secret

    try:
        with httpx.Client(timeout=15.0) as client:
            token_resp = client.post(token_endpoint, data=payload)
            token_resp.raise_for_status()
            token_doc = token_resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SsoError(f"IdP token exchange failed: {exc}") from exc

    id_token = token_doc.get("id_token")
    if not id_token:
        raise SsoError("IdP did not return an id_token.")

    # Validate ID token via authlib's JOSE-spec verifier. It checks
    # signature against the IdP's JWKS, ``iss`` against discovery,
    # ``aud`` against client_id, ``exp`` not past, ``nonce`` against
    # the value we stashed. A bad signature, expired token, audience
    # mismatch, or replayed nonce all raise here.
    from authlib.jose import JsonWebKey, jwt as authlib_jwt
    from authlib.jose.errors import JoseError

    try:
        with httpx.Client(timeout=10.0) as client:
            jwks_resp = client.get(jwks_uri)
            jwks_resp.raise_for_status()
            jwks_doc = jwks_resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SsoError(f"IdP JWKS fetch failed: {exc}") from exc

    try:
        jwk_set = JsonWebKey.import_key_set(jwks_doc)
        claims = authlib_jwt.decode(
            id_token,
            jwk_set,
            claims_options={
                "iss": {"essential": True, "value": discovery.get("issuer", provider.issuer)},
                "aud": {"essential": True, "value": provider.client_id},
                "nonce": {"essential": True, "value": nonce},
            },
        )
        claims.validate()
    except JoseError as exc:
        raise SsoError(f"ID token validation failed: {exc}") from exc

    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise SsoError("IdP returned no email — cannot identify user.")
    if not _matches_email_domain(email, list(provider.allowed_email_domains or [])):
        raise SsoError(f"Email {email} is not in an allowed domain for this provider.")

    # JIT-provision: find or create the User + Membership.
    with super_admin_context(reason="sso.jit_provision"):
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            if not provider.jit_provision:
                raise SsoError(
                    f"No account found for {email} and JIT provisioning is disabled. "
                    "Ask your administrator to invite you first."
                )
            # Random unusable password — SSO users authenticate via the
            # IdP, but Django's password machinery still expects a hash.
            user = User.objects.create_user(
                email=email, password=secrets.token_urlsafe(48)
            )
        # Ensure a membership exists in this org.
        existing = OrganizationMembership.objects.filter(
            user=user, organization_id=organization_id
        ).first()
        if existing is None:
            if not provider.jit_provision:
                raise SsoError(
                    "You're not a member of the SSO-provisioned organization."
                )
            role = default_role or Role.objects.filter(name="submitter").first()
            if role is None:
                raise SsoError(
                    "No default Role configured for JIT provisioning. Contact your administrator."
                )
            OrganizationMembership.objects.create(
                user=user, organization_id=organization_id, role=role
            )
        # Bookkeeping.
        provider.last_login_at = timezone.now()
        provider.save(update_fields=["last_login_at"])

    # Clear SSO session state.
    for key in ("sso_state", "sso_nonce", "sso_provider_id", "sso_email_hint"):
        request.session.pop(key, None)

    return user
