"""DRF authentication class for API keys.

Closes the loop on Slice 46: customers can mint keys, but until now no
endpoint actually accepted them as auth. This module wires
``Authorization: Bearer <plaintext>`` headers to a synthetic API-key
identity that DRF treats as an authenticated request, while populating
the Django session-style ``organization_id`` for the tenancy
middleware to pick up.

Lookup is by prefix (indexed on ``APIKey.key_prefix``) followed by a
``hmac.compare_digest`` check on the SHA-256 hash. Inactive keys (or
keys that fail prefix lookup) return ``AuthenticationFailed`` so the
view layer responds with 401.

On success we update ``last_used_at`` (best-effort, no transaction —
a clock-skew or DB error here doesn't fail the request).
"""

from __future__ import annotations

import hashlib
import hmac

from django.utils import timezone
from rest_framework import authentication, exceptions

from .models import APIKey, User


_BEARER_PREFIX = "Bearer "
_KEY_PREFIX_LEN = 12


class APIKeyAuthentication(authentication.BaseAuthentication):
    """Authenticate via ``Authorization: Bearer zk_live_…``.

    Returns ``(user, api_key)`` where ``user`` is the
    ``created_by_user_id`` if the User row still exists, otherwise a
    synthetic AnonymousUser-like proxy bound to the org. ``api_key``
    is the APIKey row so views can introspect (``request.auth.id`` /
    ``request.auth.organization_id``).

    Pairs with ``apps.identity.tenancy.TenantContextMiddleware``: the
    middleware reads ``request.session['organization_id']`` and sets
    the tenant variable. For API-key requests there's no session, so
    this auth class falls through to the existing middleware via the
    ``request.session`` shim — sets ``organization_id`` on the auth-
    side session-like dict so the tenant context picks it up.
    """

    keyword = "Bearer"

    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.startswith(_BEARER_PREFIX):
            return None  # Not our auth scheme — let other classes try.

        plaintext = header[len(_BEARER_PREFIX):].strip()
        if not plaintext:
            return None  # Empty bearer — let session auth handle.

        # Only act on tokens that look like our API-key shape so we
        # don't conflict with future bearer formats (e.g. JWT). The
        # ``zk_live_`` prefix is stable.
        if not plaintext.startswith("zk_live_"):
            return None

        prefix = plaintext[:_KEY_PREFIX_LEN]
        provided_hash = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()

        # Prefix lookup is indexed; small candidate set (typically 1
        # row). Constant-time hash compare avoids timing leaks.
        candidates = APIKey.objects.filter(
            key_prefix=prefix, is_active=True
        ).select_related()

        # Need to bypass tenant RLS here — we don't know the org yet.
        # Wrap in super-admin elevation; the elevation reason is
        # logged for ops via the standard pattern.
        from apps.identity.tenancy import super_admin_context

        match: APIKey | None = None
        with super_admin_context(reason="api_key_auth:lookup"):
            for row in candidates:
                if hmac.compare_digest(row.key_hash, provided_hash):
                    match = row
                    break

        if match is None:
            raise exceptions.AuthenticationFailed("Invalid API key.")

        # Resolve the user behind the key. If they've been deleted
        # we raise rather than fall through anonymous — a key whose
        # owner is gone shouldn't keep working.
        user = None
        if match.created_by_user_id:
            with super_admin_context(reason="api_key_auth:user_lookup"):
                user = User.objects.filter(id=match.created_by_user_id).first()
        if user is None:
            raise exceptions.AuthenticationFailed(
                "API key owner is no longer active. Please mint a new key."
            )

        # Populate the session-org pointer so TenantContextMiddleware
        # picks it up. Django's session is mutable here — we don't
        # persist it (the middleware reads, the tenant var is set,
        # the request completes, the session is discarded with the
        # request).
        if hasattr(request, "session"):
            request.session["organization_id"] = str(match.organization_id)

        # Best-effort last_used_at update. Failures here don't 401.
        try:
            with super_admin_context(reason="api_key_auth:touch"):
                APIKey.objects.filter(id=match.id).update(
                    last_used_at=timezone.now()
                )
        except Exception:  # noqa: BLE001
            pass

        return (user, match)

    def authenticate_header(self, request) -> str:
        return self.keyword
