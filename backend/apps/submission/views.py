"""Submission context views.

Phase 2 surface (Phase 3 adds the actual signing + LHDN submission):
  GET   /api/v1/invoices/                  — all-invoices list with filters
  GET   /api/v1/invoices/by-job/<job_id>/  — fetch the invoice for an IngestionJob
  GET   /api/v1/invoices/<id>/             — invoice detail with line items
  PATCH /api/v1/invoices/<id>/             — apply user corrections, re-validate
"""

from __future__ import annotations

from datetime import datetime

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from . import services
from .models import Invoice
from .serializers import InvoiceListSummarySerializer, InvoiceSerializer


def _active_org(request: Request) -> str | None:
    session = getattr(request, "session", None)
    return session.get("organization_id") if session is not None else None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_invoices(request: Request) -> Response:
    """All-invoices list, scoped to the active org.

    Filters: ``?status=<exact>``, ``?search=<substring>``,
    ``?limit=<n>``, ``?before_created_at=<iso>`` (cursor pagination).
    """
    organization_id = _active_org(request)
    if not organization_id:
        return Response({"results": [], "total": 0})

    status_filter = request.query_params.get("status") or None
    search = request.query_params.get("search") or None

    try:
        limit = int(request.query_params.get("limit", "50"))
    except ValueError:
        return Response(
            {"detail": "limit must be an integer."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    limit = max(1, min(limit, 200))

    raw_before = request.query_params.get("before_created_at")
    before: datetime | None = None
    if raw_before:
        try:
            before = datetime.fromisoformat(raw_before)
        except ValueError:
            return Response(
                {"detail": "before_created_at must be ISO 8601."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    rows = services.list_invoices_for_organization(
        organization_id=organization_id,
        status=status_filter,
        search=search,
        limit=limit,
        before_created_at=before,
    )
    total = services.count_invoices_for_organization(organization_id=organization_id)
    return Response(
        {
            "results": InvoiceListSummarySerializer(rows, many=True).data,
            "total": total,
        }
    )


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def invoice_detail(request: Request, invoice_id: str) -> Response:
    organization_id = _active_org(request)
    if not organization_id:
        return Response({"detail": "No active organization."}, status=status.HTTP_400_BAD_REQUEST)

    if request.method == "PATCH":
        return _invoice_update(request, organization_id, invoice_id)

    invoice = services.get_invoice(organization_id=organization_id, invoice_id=invoice_id)
    if invoice is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(InvoiceSerializer(invoice).data)


def _invoice_update(request: Request, organization_id: str, invoice_id: str) -> Response:
    """Apply user corrections and return the re-validated invoice."""
    if not isinstance(request.data, dict):
        return Response(
            {"detail": "Body must be a JSON object."}, status=status.HTTP_400_BAD_REQUEST
        )
    try:
        result = services.update_invoice(
            organization_id=organization_id,
            invoice_id=invoice_id,
            updates=request.data,
            actor_user_id=request.user.id,
        )
    except Invoice.DoesNotExist:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    except services.InvoiceUpdateError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(InvoiceSerializer(result.invoice).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def invoice_by_job(request: Request, job_id: str) -> Response:
    organization_id = _active_org(request)
    if not organization_id:
        return Response({"detail": "No active organization."}, status=status.HTTP_400_BAD_REQUEST)
    invoice = services.get_invoice_for_job(organization_id=organization_id, ingestion_job_id=job_id)
    if invoice is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(InvoiceSerializer(invoice).data)


# --- Slice 59B: LHDN lifecycle endpoints ----------------------------------


def _can_user_submit_lhdn(user, organization_id) -> bool:
    """Roles that may submit/cancel LHDN documents.

    Owner / admin / approver / submitter may submit. Viewer cannot.
    Backend gate is the source of truth; UI mirrors for cleanliness.
    """
    from apps.identity.models import OrganizationMembership

    return OrganizationMembership.objects.filter(
        user=user,
        organization_id=organization_id,
        is_active=True,
        role__name__in=["owner", "admin", "approver", "submitter"],
    ).exists()


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def submit_invoice_to_lhdn_view(request: Request, invoice_id: str) -> Response:
    """Sign + submit one invoice to LHDN.

    Synchronous response — the operator wants to see the immediate
    outcome (LHDN typically returns 202 + a submissionUid in <2s).
    Polling for the validation status happens via the separate
    /poll-lhdn/ endpoint.

    Returns the updated Invoice payload so the FE can re-render in
    place without a fetch.
    """
    organization_id = _active_org(request)
    if not organization_id:
        return Response(
            {"detail": "No active organization."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not _can_user_submit_lhdn(request.user, organization_id):
        return Response(
            {"detail": "You don't have permission to submit invoices."},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        invoice = Invoice.objects.get(
            id=invoice_id, organization_id=organization_id
        )
    except Invoice.DoesNotExist:
        return Response(
            {"detail": "Invoice not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Pre-flight checks before kicking off signing — surface the
    # most common errors here (cleaner than letting the orchestrator
    # raise + audit a generic failure).
    if not invoice.invoice_number:
        return Response(
            {
                "detail": (
                    "Invoice number is required before LHDN submission."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    if invoice.status in {
        Invoice.Status.SUBMITTING,
        Invoice.Status.VALIDATED,
        Invoice.Status.CANCELLED,
    }:
        return Response(
            {
                "detail": (
                    f"Invoice is already in {invoice.status} state."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    from . import lhdn_submission

    result = lhdn_submission.submit_invoice_to_lhdn(invoice.id)
    invoice.refresh_from_db()
    return Response(
        {
            "ok": result.get("ok", False),
            "reason": result.get("reason", ""),
            "submission_uid": result.get("submission_uid", ""),
            "invoice": InvoiceSerializer(invoice).data,
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def cancel_invoice_lhdn_view(request: Request, invoice_id: str) -> Response:
    """Cancel a validated LHDN invoice within the 72-hour window.

    Body: ``{"reason": "..."}``. Reason is required (LHDN's contract,
    enforced both client-side + by the orchestrator).
    """
    organization_id = _active_org(request)
    if not organization_id:
        return Response(
            {"detail": "No active organization."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not _can_user_submit_lhdn(request.user, organization_id):
        return Response(
            {"detail": "You don't have permission to cancel invoices."},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        invoice = Invoice.objects.get(
            id=invoice_id, organization_id=organization_id
        )
    except Invoice.DoesNotExist:
        return Response(
            {"detail": "Invoice not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    body = request.data or {}
    reason = str(body.get("reason") or "").strip()

    from . import lhdn_submission

    result = lhdn_submission.cancel_invoice(
        invoice_id=invoice.id,
        reason=reason,
        actor_user_id=request.user.id,
    )
    invoice.refresh_from_db()
    return Response(
        {
            "ok": result.get("ok", False),
            "reason": result.get("reason", ""),
            "code": result.get("code", ""),
            "invoice": InvoiceSerializer(invoice).data,
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def poll_invoice_lhdn_view(request: Request, invoice_id: str) -> Response:
    """Trigger one synchronous status poll for the invoice.

    Used by the FE's "Refresh status" button. The Celery beat
    scheduler also polls in the background; this endpoint is the
    operator-on-demand path.
    """
    organization_id = _active_org(request)
    if not organization_id:
        return Response(
            {"detail": "No active organization."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        invoice = Invoice.objects.get(
            id=invoice_id, organization_id=organization_id
        )
    except Invoice.DoesNotExist:
        return Response(
            {"detail": "Invoice not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    from . import lhdn_submission

    result = lhdn_submission.poll_invoice_status(invoice.id)
    invoice.refresh_from_db()
    return Response(
        {
            "ok": result.get("ok", False),
            "reason": result.get("reason", ""),
            "document_status": result.get("document_status", ""),
            "lhdn_uuid": result.get("lhdn_uuid", ""),
            "invoice": InvoiceSerializer(invoice).data,
        }
    )
