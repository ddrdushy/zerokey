"""Platform-administration views (super-admin surface).

Read-mostly today — the first endpoint is just an "are you staff?" probe
the frontend uses to gate the /admin route. Subsequent slices add
cross-tenant audit log, tenant list, engine credentials management.

Every endpoint is protected by ``IsPlatformStaff``; no fallthrough to
tenant-context. The actual cross-tenant queries elevate via
``super_admin_context`` so RLS lets them read across all customers,
with the elevation reason recorded in the audit log per call.
"""

from __future__ import annotations

from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from .permissions import IsPlatformStaff


@api_view(["GET"])
@permission_classes([IsPlatformStaff])
def admin_me(request: Request) -> Response:
    """Probe endpoint — returns the staff identity if the caller is staff.

    The frontend's /admin route fetches this on mount. A 403 means
    "not staff — redirect to /dashboard"; a 200 means "render the
    admin shell".
    """
    user = request.user
    return Response(
        {
            "id": str(user.id),
            "email": user.email,
            "is_staff": True,
            "is_superuser": bool(getattr(user, "is_superuser", False)),
        }
    )
