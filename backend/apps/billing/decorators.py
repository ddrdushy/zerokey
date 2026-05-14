"""Feature-gating decorators for DRF views.

Wraps ``apps.billing.services.is_feature_enabled`` so view modules can
declare ``@feature_required("flag_slug")`` next to the action instead of
copying the same gate-and-403 dance everywhere. The flag resolution chain
(per-org override → plan default → global default) lives in services.

The decorator is fail-closed: if there's no active organization on the
request, the view is rejected as if the flag were off. That keeps the
guarantee that an unauthenticated or org-less request never bypasses a
flag gate accidentally.
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from rest_framework import status
from rest_framework.response import Response

from .services import is_feature_enabled


def _active_organization_id(request: Any) -> str | None:
    """Resolve the active organization for a request.

    Reads ``request.session["organization_id"]`` — the same source the
    rest of the codebase uses. API-key authenticated requests stamp this
    on the session via the auth class, so the same lookup works for both
    web and programmatic clients.
    """
    session = getattr(request, "session", None)
    if session is None:
        return None
    org_id = session.get("organization_id")
    return str(org_id) if org_id else None


def feature_required(flag_slug: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Reject the request with 403 when ``flag_slug`` is disabled for the org.

    Usage::

        @api_view(["POST"])
        @feature_required("csv_export")
        def export_invoices(request):
            ...

    Order matters: place ``@feature_required`` AFTER ``@api_view`` /
    ``@permission_classes`` so the auth + permission decorators run
    first. Returns the wrapped view unchanged when the flag is on.
    """

    def decorator(view: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view)
        def wrapped(request: Any, *args: Any, **kwargs: Any) -> Any:
            organization_id = _active_organization_id(request)
            if organization_id is None:
                return Response(
                    {
                        "detail": (
                            "Feature gate requires an active organization context. "
                            "Sign in or switch organization."
                        ),
                        "feature": flag_slug,
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
            if not is_feature_enabled(
                organization_id=organization_id,
                flag_slug=flag_slug,
            ):
                return Response(
                    {
                        "detail": (
                            "This feature isn't enabled on your plan. "
                            "Talk to support or upgrade to unlock it."
                        ),
                        "feature": flag_slug,
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
