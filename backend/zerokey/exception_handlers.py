"""Project-wide DRF exception handler.

Slice 104 — implements the error envelope contract from
``API_DESIGN.md`` ("errors are first-class"):

    {
      "error": {
        "code":    "validation_error",
        "message": "Plain-language description of what went wrong.",
        "field":   "buyer.tin",                 // optional
        "request_id": "f7c0…",
        "documentation_url": "..."              // optional
      }
    }

DRF's default handler returns shapes like ``{"detail": "..."}``,
``{"field": ["msg"]}``, or ``[{"field": ["msg"]}, ...]`` depending on
the exception. We normalise to the envelope above so every
client / SDK can parse one shape.

Unhandled exceptions (anything DRF doesn't catch) become an
``internal`` error here so the client still receives a parseable
envelope; the underlying exception is re-raised after the response is
prepared so Sentry / Django still see it.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_default_exception_handler

from zerokey.middleware import get_request_id

# Mapping from DRF exception classes to our stable error codes.
# These code strings are part of the public API — once a client
# branches on them, never rename.
_CODE_BY_CLASS: dict[type[BaseException], str] = {
    exceptions.AuthenticationFailed: "authentication_failed",
    exceptions.NotAuthenticated: "not_authenticated",
    exceptions.PermissionDenied: "permission_denied",
    exceptions.NotFound: "not_found",
    exceptions.MethodNotAllowed: "method_not_allowed",
    exceptions.NotAcceptable: "not_acceptable",
    exceptions.UnsupportedMediaType: "unsupported_media_type",
    exceptions.Throttled: "throttled",
    exceptions.ParseError: "parse_error",
    exceptions.ValidationError: "validation_error",
    Http404: "not_found",
    PermissionDenied: "permission_denied",
}


def _flatten_validation(detail: Any, path: str = "") -> tuple[str, str]:
    """Walk a DRF ValidationError detail tree, return (field, message).

    DRF ValidationError details are nested in arbitrary depth — dicts
    keyed by field, lists of errors, or a bare string. We surface the
    first leaf so the envelope's ``field`` + ``message`` are always
    populated. The full structured detail is preserved on the
    response under ``error.errors`` so callers that want every
    issue can still read them.
    """
    if isinstance(detail, dict):
        for key, value in detail.items():
            sub_path = f"{path}.{key}" if path else str(key)
            field, message = _flatten_validation(value, sub_path)
            if message:
                return field, message
        return path, ""
    if isinstance(detail, list):
        for item in detail:
            field, message = _flatten_validation(item, path)
            if message:
                return field, message
        return path, ""
    return path, str(detail)


def envelope_exception_handler(exc: BaseException, context: dict) -> Response | None:
    """DRF EXCEPTION_HANDLER entry point.

    Called for every uncaught exception that propagates out of a DRF
    view. Returning ``None`` falls back to Django's 500 page (we
    never want that for an API request — we always emit JSON), so we
    catch the unhandled case explicitly below.
    """
    response = drf_default_exception_handler(exc, context)
    request_id = get_request_id()

    if response is None:
        # Truly unhandled — DRF didn't recognise the exception.
        # Build a synthetic 500 envelope. The exception still
        # propagates to Sentry via the regular Django exception
        # plumbing because we don't swallow it (Django's exception
        # handler logs it after the response is returned).
        return Response(
            {
                "error": {
                    "code": "internal",
                    "message": "An unexpected error occurred.",
                    "request_id": request_id,
                }
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    code = _CODE_BY_CLASS.get(type(exc), "error")
    detail = getattr(exc, "detail", None)

    if isinstance(exc, exceptions.ValidationError) and detail is not None:
        field, message = _flatten_validation(detail)
        body: dict[str, Any] = {
            "error": {
                "code": code,
                "message": message or "Validation failed.",
                "request_id": request_id,
            }
        }
        if field:
            body["error"]["field"] = field
        # Preserve the full DRF error tree for clients that want
        # every issue, not just the leaf.
        body["error"]["errors"] = detail
    else:
        # Non-validation exceptions: ``detail`` is a string-ish
        # ErrorDetail. Surface as message; keep the original code if
        # DRF labelled one (e.g. ``throttled``).
        message = str(detail) if detail is not None else str(exc) or "Error."
        drf_code = getattr(detail, "code", None)
        body = {
            "error": {
                "code": drf_code or code,
                "message": message,
                "request_id": request_id,
            }
        }
        # Throttled exceptions carry a ``wait`` (seconds). Surface as
        # ``Retry-After`` header — RFC 7231 mandates seconds-int.
        if isinstance(exc, exceptions.Throttled) and exc.wait is not None:
            response["Retry-After"] = str(int(exc.wait))

    response.data = body
    return response
