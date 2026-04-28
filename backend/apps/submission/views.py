"""Submission context views.

Phase 2 surface (Phase 3 adds the actual signing + LHDN submission):
  GET   /api/v1/invoices/by-job/<job_id>/  — fetch the invoice for an IngestionJob
  GET   /api/v1/invoices/<id>/             — invoice detail with line items
  PATCH /api/v1/invoices/<id>/             — apply user corrections, re-validate
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from . import services
from .models import Invoice
from .serializers import InvoiceSerializer


def _active_org(request: Request) -> str | None:
    session = getattr(request, "session", None)
    return session.get("organization_id") if session is not None else None


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
