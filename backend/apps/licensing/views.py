"""Licensing HTTP surface.

Two audiences:

  - The **desktop app** calls ``/validate/``, ``/heartbeat/``, and
    fetches the public key from ``/public-key/``. These are
    unauthenticated (the license key is the credential).
  - **Super admin operators** call ``/admin/issue/``, ``/admin/list/``,
    ``/admin/<id>/`` etc., gated by ``IsPlatformStaff``.

Customer self-serve (viewing your own licenses, regenerating your
own key) lives at ``/me/...`` and uses the standard session-cookie
auth from the rest of the platform.

We treat IP extraction as best-effort: behind the nginx proxy we trust
``X-Forwarded-For`` first non-private hop. The licensing service
records whatever we give it without further interpretation.
"""

from __future__ import annotations

import logging
from datetime import datetime

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.administration.permissions import IsPlatformStaff

from . import services
from .entitlements import public_key_pem
from .models import DesktopTelemetry, License, LicenseHeartbeat

logger = logging.getLogger(__name__)


# --- helpers -----------------------------------------------------------------------


def _client_ip(request: Request) -> str | None:
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        # First entry is the original client. We don't bother stripping
        # private addrs — the IP is for fraud forensics, not access
        # control.
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _serialise_license(lic: License) -> dict:
    return {
        "id": str(lic.id),
        "owner_user_id": str(lic.owner_user_id),
        "organization_legal_name": lic.organization_legal_name,
        "organization_tin": lic.organization_tin,
        "plan": lic.plan,
        "status": lic.status,
        "issued_at": lic.issued_at.isoformat(),
        "expires_at": lic.expires_at.isoformat(),
        "bound_fingerprint_hash": lic.bound_fingerprint_hash[:12]
        if lic.bound_fingerprint_hash
        else "",
        "bound_at": lic.bound_at.isoformat() if lic.bound_at else None,
        "last_heartbeat_at": (
            lic.last_heartbeat_at.isoformat() if lic.last_heartbeat_at else None
        ),
        "last_heartbeat_ip": lic.last_heartbeat_ip,
        "last_desktop_version": lic.last_desktop_version,
        "revoked_at": lic.revoked_at.isoformat() if lic.revoked_at else None,
        "revoke_reason": lic.revoke_reason,
    }


def _service_error_response(exc: services.LicensingError) -> Response:
    """Map service-layer errors to HTTP responses with consistent shapes."""
    if isinstance(exc, services.UnknownLicenseKeyError):
        return Response(
            {"detail": "Unknown license key.", "code": "unknown_key"},
            status=status.HTTP_404_NOT_FOUND,
        )
    if isinstance(exc, services.FingerprintMismatchError):
        return Response(
            {"detail": str(exc), "code": "fingerprint_mismatch"},
            status=status.HTTP_409_CONFLICT,
        )
    if isinstance(exc, services.LicenseNotActiveError):
        return Response(
            {"detail": str(exc), "code": exc.status, "status": exc.status},
            status=status.HTTP_403_FORBIDDEN,
        )
    if isinstance(exc, services.DuplicateTinError):
        return Response(
            {"detail": str(exc), "code": "duplicate_tin"},
            status=status.HTTP_409_CONFLICT,
        )
    return Response(
        {"detail": str(exc), "code": "licensing_error"},
        status=status.HTTP_400_BAD_REQUEST,
    )


# --- desktop endpoints (unauthenticated; the key IS the credential) ----------------


@api_view(["GET"])
@permission_classes([AllowAny])
def public_key_view(_request: Request) -> Response:
    """The Ed25519 public key the desktop pins for verification."""
    return Response({"public_key_pem": public_key_pem()})


@api_view(["POST"])
@permission_classes([AllowAny])
def validate_view(request: Request) -> Response:
    """First-call activation from the desktop.

    Body: { "key": "ZK-...", "machine_fingerprint": "<hex>",
            "desktop_version": "1.2.3" }
    """
    key = (request.data.get("key") or "").strip()
    fingerprint = (request.data.get("machine_fingerprint") or "").strip()
    desktop_version = (request.data.get("desktop_version") or "").strip()
    if not key:
        return Response(
            {"detail": "key is required.", "code": "missing_key"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        result = services.validate_license(
            key=key,
            machine_fingerprint=fingerprint,
            desktop_version=desktop_version,
            ip=_client_ip(request),
        )
    except services.LicensingError as exc:
        return _service_error_response(exc)
    return Response(
        {
            "license_id": str(result.license_id),
            "organization_legal_name": result.organization_legal_name,
            "plan": result.plan,
            "status": result.status,
            "expires_at": result.expires_at.isoformat(),
            "entitlement": result.entitlement_wire,
        }
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def heartbeat_view(request: Request) -> Response:
    """Daily ping from the desktop. Refreshes the entitlement TTL.

    Body: { "license_id": "<uuid>", "machine_fingerprint": "<hex>",
            "desktop_version": "1.2.3" }
    """
    license_id = (request.data.get("license_id") or "").strip()
    fingerprint = (request.data.get("machine_fingerprint") or "").strip()
    desktop_version = (request.data.get("desktop_version") or "").strip()
    if not license_id:
        return Response(
            {"detail": "license_id is required.", "code": "missing_license_id"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        result = services.heartbeat_license(
            license_id=license_id,
            machine_fingerprint=fingerprint,
            desktop_version=desktop_version,
            ip=_client_ip(request),
        )
    except services.LicensingError as exc:
        return _service_error_response(exc)
    return Response(
        {
            "license_id": str(result.license_id),
            "organization_legal_name": result.organization_legal_name,
            "plan": result.plan,
            "status": result.status,
            "expires_at": result.expires_at.isoformat(),
            "entitlement": result.entitlement_wire,
        }
    )


# --- super admin endpoints ---------------------------------------------------------


@api_view(["POST"])
@permission_classes([IsPlatformStaff])
def admin_issue_view(request: Request) -> Response:
    """Issue a new license. The plaintext key is returned ONCE."""
    owner_user_id = request.data.get("owner_user_id")
    legal_name = (request.data.get("organization_legal_name") or "").strip()
    tin = (request.data.get("organization_tin") or "").strip()
    plan = (request.data.get("plan") or License.Plan.STARTER).strip()
    try:
        validity_days = int(request.data.get("validity_days") or 365)
    except (TypeError, ValueError):
        return Response(
            {"detail": "validity_days must be an integer."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not owner_user_id or not legal_name or not tin:
        return Response(
            {"detail": "owner_user_id, organization_legal_name, organization_tin required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        result = services.issue_license(
            owner_user_id=owner_user_id,
            organization_legal_name=legal_name,
            organization_tin=tin,
            plan=plan,
            validity_days=validity_days,
            actor_user_id=request.user.id,
        )
    except services.LicensingError as exc:
        return _service_error_response(exc)
    lic = License.objects.get(id=result.license_id)
    return Response(
        {
            "license": _serialise_license(lic),
            "plaintext_key": result.plaintext_key,
            "_warning": "Save this key now — it will not be shown again.",
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET"])
@permission_classes([IsPlatformStaff])
def admin_list_view(request: Request) -> Response:
    """Paginated license inventory."""
    qs = License.objects.all().select_related("owner_user")
    status_filter = request.query_params.get("status")
    if status_filter:
        qs = qs.filter(status=status_filter)
    plan_filter = request.query_params.get("plan")
    if plan_filter:
        qs = qs.filter(plan=plan_filter)
    search = (request.query_params.get("q") or "").strip()
    if search:
        qs = qs.filter(
            organization_legal_name__icontains=search
        ) | qs.filter(organization_tin__icontains=search)
    try:
        limit = max(1, min(int(request.query_params.get("limit", "50")), 200))
    except ValueError:
        return Response({"detail": "limit must be an integer."}, status=400)
    rows = [_serialise_license(lic) for lic in qs[:limit]]
    return Response({"results": rows, "count": len(rows)})


@api_view(["GET"])
@permission_classes([IsPlatformStaff])
def admin_detail_view(_request: Request, license_id) -> Response:
    try:
        lic = License.objects.get(id=license_id)
    except License.DoesNotExist:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    hbs = list(
        LicenseHeartbeat.objects.filter(license=lic)
        .order_by("-at")[:50]
        .values("id", "event_type", "result", "at", "ip", "desktop_version", "entitlement_id")
    )
    for h in hbs:
        if isinstance(h.get("at"), datetime):
            h["at"] = h["at"].isoformat()
        if h.get("entitlement_id"):
            h["entitlement_id"] = str(h["entitlement_id"])
        if h.get("id"):
            h["id"] = str(h["id"])

    # DESKTOP_PIVOT_PLAN Phase 6 — last 30 days of telemetry counters
    # so the operator can answer "is this customer actually using it?"
    # without paging into another screen. Counts only, never invoice data.
    telemetry_rows = list(
        DesktopTelemetry.objects.filter(license=lic)
        .order_by("-day")[:30]
        .values(
            "day",
            "invoices_ingested",
            "invoices_submitted",
            "invoices_failed",
            "consolidated_b2c_built",
            "desktop_version",
            "received_at",
        )
    )
    for t in telemetry_rows:
        t["day"] = t["day"].isoformat()
        if isinstance(t.get("received_at"), datetime):
            t["received_at"] = t["received_at"].isoformat()
    telemetry_summary = {
        "days_reporting": len(telemetry_rows),
        "invoices_submitted_total": sum(
            t["invoices_submitted"] for t in telemetry_rows
        ),
        "invoices_failed_total": sum(t["invoices_failed"] for t in telemetry_rows),
        "last_seen": telemetry_rows[0]["day"] if telemetry_rows else None,
    }

    return Response(
        {
            "license": _serialise_license(lic),
            "recent_heartbeats": hbs,
            "telemetry": telemetry_rows,
            "telemetry_summary": telemetry_summary,
        }
    )


@api_view(["POST"])
@permission_classes([IsPlatformStaff])
def admin_revoke_view(request: Request, license_id) -> Response:
    reason = (request.data.get("reason") or "").strip()
    if not reason:
        return Response(
            {"detail": "reason is required to revoke a license."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        lic = services.revoke_license(
            license_id=license_id, reason=reason, actor_user_id=request.user.id
        )
    except License.DoesNotExist:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response({"license": _serialise_license(lic)})


@api_view(["POST"])
@permission_classes([IsPlatformStaff])
def admin_regenerate_view(request: Request, license_id) -> Response:
    try:
        result = services.regenerate_license_key(
            license_id=license_id, actor_user_id=request.user.id
        )
    except License.DoesNotExist:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    except services.LicensingError as exc:
        return _service_error_response(exc)
    lic = License.objects.get(id=result.license_id)
    return Response(
        {
            "license": _serialise_license(lic),
            "plaintext_key": result.plaintext_key,
            "_warning": "Save this key now — it will not be shown again.",
        }
    )


@api_view(["POST"])
@permission_classes([IsPlatformStaff])
def admin_renew_view(request: Request, license_id) -> Response:
    try:
        days = int(request.data.get("days") or 365)
    except (TypeError, ValueError):
        return Response({"detail": "days must be an integer."}, status=400)
    try:
        lic = services.renew_license(
            license_id=license_id, days=days, actor_user_id=request.user.id
        )
    except License.DoesNotExist:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    except services.LicensingError as exc:
        return _service_error_response(exc)
    return Response({"license": _serialise_license(lic)})


# --- customer self-serve -----------------------------------------------------------


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me_list_view(request: Request) -> Response:
    """List the calling user's owned licenses."""
    rows = [
        _serialise_license(lic)
        for lic in License.objects.filter(owner_user=request.user)
    ]
    return Response({"results": rows, "count": len(rows)})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def me_regenerate_view(request: Request, license_id) -> Response:
    """Customer-initiated key regeneration (e.g. lost the key)."""
    try:
        lic = License.objects.get(id=license_id, owner_user=request.user)
    except License.DoesNotExist:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    try:
        result = services.regenerate_license_key(
            license_id=lic.id, actor_user_id=request.user.id
        )
    except services.LicensingError as exc:
        return _service_error_response(exc)
    lic.refresh_from_db()
    return Response(
        {
            "license": _serialise_license(lic),
            "plaintext_key": result.plaintext_key,
            "_warning": "Save this key now — it will not be shown again.",
        }
    )
