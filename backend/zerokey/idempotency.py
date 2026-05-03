"""Idempotency-Key middleware.

Slice 105 — implements ``API_DESIGN.md §Idempotency``:

  * All mutating endpoints accept an optional ``Idempotency-Key``
    HTTP header.
  * Requests with the same idempotency key within a 24-hour window
    are deduplicated: the second request returns the result of the
    first without performing the mutation again.
  * If a key is reused with a *different* request body, the second
    request fails with ``409`` and code ``idempotency_conflict``.
  * Keys are scoped to the authenticated principal (API key id, or
    user id when session-authenticated) so two integrations can use
    the same string without collision.

Why a middleware and not a decorator: the contract is global ("all
mutating endpoints"). A decorator would require remembering to add
it to every new view; a middleware can't be forgotten. Side-benefit
— it sees every endpoint, including ones added in slices we
haven't written yet.

Storage: Django cache (Redis in dev/prod, locmem in tests). One
entry per (scope, key) holding the request-body hash plus the
serialised response. 24-hour TTL.

Skipped:
  - Safe methods (GET/HEAD/OPTIONS/TRACE) — nothing to dedupe.
  - Multipart uploads (``Content-Type`` starts with
    ``multipart/form-data``) — body is too large to hash cheaply
    and the use case (file ingestion) has its own dedup at the
    storage layer (S3 ETags + IngestionJob.uniqueness key).
  - Streaming responses — we'd have to consume the iterator to
    cache; not worth the memory cost for the rare streaming
    endpoint. The replay would be a no-op anyway because the
    next call gets a fresh stream.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
from typing import Any, Callable

from django.core.cache import cache
from django.http import HttpRequest, HttpResponse, JsonResponse, StreamingHttpResponse

from zerokey.middleware import get_request_id

logger = logging.getLogger(__name__)

# 24-hour deduplication window per spec.
IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60

# Cache key prefix. Versioned so a future format change can co-exist
# with old in-flight entries (just bump the version).
_CACHE_PREFIX = "idemp:v1"

# Header name DRF / Django normalises to ``HTTP_IDEMPOTENCY_KEY``.
_HEADER_META_KEY = "HTTP_IDEMPOTENCY_KEY"

# Tight format check — Stripe-style. Reject anything weird so we
# don't end up with cache keys carrying control bytes.
_KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{1,128}$")

# Methods we dedupe. PATCH is mutating; PUT replaces; DELETE removes.
_DEDUPE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _scope_for(request: HttpRequest) -> str | None:
    """Return the dedupe scope for this request.

    API-key requests scope by key id (so two integrations can use
    the same idempotency string). Session-authenticated requests
    scope by user id + active org. Anonymous requests have no
    scope and are never deduped.
    """
    auth_scope = getattr(request, "auth", None)
    if auth_scope is not None:
        # APIKeyAuthentication (apps.identity.api_key_auth) sets
        # ``request.auth`` to the APIKey instance. Scope by its id
        # so two keys can share key strings.
        key_id = getattr(auth_scope, "id", None) or getattr(auth_scope, "pk", None)
        if key_id:
            return f"key:{key_id}"
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        org_id = ""
        try:
            org_id = request.session.get("organization_id") or ""  # type: ignore[union-attr]
        except Exception:
            org_id = ""
        return f"user:{user.pk}:{org_id}"
    return None


def _body_hash(request: HttpRequest) -> str:
    """SHA-256 of the request body. Stable: empty body hashes consistently.

    Reading ``request.body`` consumes the body stream — but Django
    caches it on the HttpRequest after the first read, so subsequent
    DRF parser reads see the cached bytes.
    """
    body = request.body or b""
    return hashlib.sha256(body).hexdigest()


def _cache_key(scope: str, key: str) -> str:
    return f"{_CACHE_PREFIX}:{scope}:{key}"


def _serialise_response(response: HttpResponse) -> dict[str, Any] | None:
    """Pack a response for cache storage. Returns None if not cacheable.

    We cache:
      - status code
      - body bytes (base64-encoded so JSON cache backends are happy)
      - Content-Type
      - the original X-Request-Id so a client correlating logs sees
        it on the replay too (alongside the *replay* request id which
        we add on retrieval — see _build_replay_response).

    Note: at this point in the response chain, ``RequestIdMiddleware``
    hasn't added ``X-Request-Id`` to the response yet (it sits *outside*
    us). Read the contextvar instead — same value, set on request entry.
    """
    if isinstance(response, StreamingHttpResponse):
        return None
    try:
        body = response.content
    except Exception:
        return None
    return {
        "status": int(response.status_code),
        "body_b64": base64.b64encode(body).decode("ascii"),
        "content_type": response.get("Content-Type") or "application/json",
        "original_request_id": get_request_id() or "",
    }


def _build_replay_response(stored: dict[str, Any]) -> HttpResponse:
    """Reconstruct a Django HttpResponse from the cached payload."""
    body = base64.b64decode(stored["body_b64"])
    response = HttpResponse(
        body,
        status=stored["status"],
        content_type=stored["content_type"],
    )
    # Mark the response as a replay so clients (and logs) can tell
    # it's not a fresh execution.
    response["Idempotent-Replay"] = "true"
    if stored.get("original_request_id"):
        response["X-Original-Request-Id"] = stored["original_request_id"]
    return response


def _conflict_response(request_id: str | None) -> JsonResponse:
    """409 Conflict envelope for a key reused with a different body."""
    return JsonResponse(
        {
            "error": {
                "code": "idempotency_conflict",
                "message": (
                    "An Idempotency-Key was reused with a different request body. "
                    "Either use a fresh key or send the original payload."
                ),
                "request_id": request_id,
            }
        },
        status=409,
    )


class IdempotencyMiddleware:
    """Dedupe mutating requests carrying an ``Idempotency-Key`` header.

    Order in MIDDLEWARE: AFTER ``AuthenticationMiddleware`` (we need
    ``request.user``) and AFTER ``AxesMiddleware`` (lockout should
    win over cache lookup). BEFORE the rate-limit header
    middleware so a replay still reports rate-limit budget.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.method not in _DEDUPE_METHODS:
            return self.get_response(request)

        raw_key = request.META.get(_HEADER_META_KEY, "").strip()
        if not raw_key:
            return self.get_response(request)
        if not _KEY_RE.match(raw_key):
            return JsonResponse(
                {
                    "error": {
                        "code": "idempotency_key_invalid",
                        "message": (
                            "Idempotency-Key must be 1-128 chars of "
                            "letters, digits, dash, or underscore."
                        ),
                        "request_id": get_request_id(),
                    }
                },
                status=400,
            )

        content_type = request.META.get("CONTENT_TYPE", "") or ""
        if content_type.startswith("multipart/form-data"):
            # See module docstring: file uploads have their own dedup.
            return self.get_response(request)

        scope = _scope_for(request)
        if scope is None:
            # Anonymous mutating requests are extremely rare (CSRF
            # token endpoint mostly). No principal to scope against —
            # fall through.
            return self.get_response(request)

        body_hash = _body_hash(request)
        cache_key = _cache_key(scope, raw_key)

        existing = cache.get(cache_key)
        if existing is not None:
            if existing.get("body_hash") != body_hash:
                logger.info(
                    "idempotency.conflict",
                    extra={"key": raw_key, "scope": scope},
                )
                return _conflict_response(get_request_id())
            stored = existing.get("response")
            if stored is not None:
                logger.info(
                    "idempotency.replay",
                    extra={"key": raw_key, "scope": scope, "status": stored.get("status")},
                )
                return _build_replay_response(stored)
            # In-flight marker — first request hasn't returned yet.
            # Keep this simple: surface a 409 so the second client
            # backs off rather than racing.
            return JsonResponse(
                {
                    "error": {
                        "code": "idempotency_in_flight",
                        "message": (
                            "Another request with this Idempotency-Key "
                            "is still in flight. Retry shortly."
                        ),
                        "request_id": get_request_id(),
                    }
                },
                status=409,
            )

        # Mark in-flight before processing so a concurrent retry from
        # the same client doesn't double-execute. TTL is short (5 min)
        # so a crashed worker doesn't permanently block the key — the
        # client will get a fresh execution after that.
        cache.set(
            cache_key,
            {"body_hash": body_hash, "response": None},
            timeout=300,
        )

        response = self.get_response(request)

        stored = _serialise_response(response)
        if stored is not None:
            cache.set(
                cache_key,
                {"body_hash": body_hash, "response": stored},
                timeout=IDEMPOTENCY_TTL_SECONDS,
            )
        else:
            # Couldn't cache (streaming response). Drop the in-flight
            # marker so the next attempt isn't blocked by it.
            cache.delete(cache_key)

        return response
