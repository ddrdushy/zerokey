"""Desktop telemetry receiver.

Phase 6 of DESKTOP_PIVOT_PLAN.md. The desktop POSTs a daily roll-up
(counts only — never invoice contents) so super admin can see install
health without violating the privacy promise.

Auth: entitlement bearer in ``X-ZK-Entitlement``. We verify the
signature, look up the License row, then upsert one telemetry row per
license per day. Replay/retry-safe via a unique constraint on
(license, day).

The desktop sends nothing until the user opts in locally — the cloud
trusts that contract; we don't have a way to enforce it from here.
"""

from __future__ import annotations

import logging
from datetime import date

from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from .entitlements import EntitlementError, verify_entitlement
from .models import DesktopTelemetry, License

logger = logging.getLogger(__name__)


def _client_ip(request: Request) -> str | None:
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


@api_view(["POST"])
@permission_classes([AllowAny])
def telemetry_post_view(request: Request) -> Response:
    """Accept a per-day telemetry roll-up from the desktop.

    Body:
      day:                      "YYYY-MM-DD"
      invoices_ingested:        int
      invoices_submitted:       int
      invoices_failed:          int
      consolidated_b2c_built:   int
      desktop_version:          string
    Header:
      X-ZK-Entitlement:         "<wire-format entitlement>"
    """
    raw = request.META.get("HTTP_X_ZK_ENTITLEMENT", "").strip()
    if not raw:
        return Response(
            {"detail": "Entitlement required.", "code": "missing_entitlement"},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    try:
        payload = verify_entitlement(raw)
    except EntitlementError as exc:
        return Response(
            {"detail": str(exc), "code": "invalid_entitlement"},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    license_id = payload.get("license_id")
    lic = License.objects.filter(id=license_id).first()
    if lic is None:
        return Response(
            {"detail": "Unknown license.", "code": "unknown_license"},
            status=status.HTTP_404_NOT_FOUND,
        )

    day_str = (request.data.get("day") or "").strip()
    try:
        day = date.fromisoformat(day_str)
    except ValueError:
        return Response(
            {"detail": "day must be YYYY-MM-DD.", "code": "bad_day"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    def _int(field: str) -> int:
        try:
            return max(0, int(request.data.get(field) or 0))
        except (TypeError, ValueError):
            return 0

    fields = {
        "invoices_ingested": _int("invoices_ingested"),
        "invoices_submitted": _int("invoices_submitted"),
        "invoices_failed": _int("invoices_failed"),
        "consolidated_b2c_built": _int("consolidated_b2c_built"),
        "desktop_version": (request.data.get("desktop_version") or "")[:32],
        "received_ip": _client_ip(request),
    }

    # Upsert one row per (license, day). Retries that hit the same
    # day overwrite the counts — the latest send wins.
    try:
        with transaction.atomic():
            row, created = DesktopTelemetry.objects.update_or_create(
                license=lic, day=day, defaults=fields
            )
    except IntegrityError as exc:
        # Race against the unique constraint — extremely unlikely
        # given the desktop sends serially, but be explicit.
        logger.warning("licensing.telemetry.race: %s", exc)
        return Response(
            {"detail": "Concurrent write conflict; retry.", "code": "conflict"},
            status=status.HTTP_409_CONFLICT,
        )

    return Response(
        {
            "id": str(row.id),
            "created": created,
            "license_id": str(lic.id),
            "day": day.isoformat(),
        }
    )
