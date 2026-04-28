"""Enrichment context views — the Customers UI surface.

  GET   /api/v1/customers/        — list buyers (most-used first)
  GET   /api/v1/customers/<id>/   — buyer detail
  PATCH /api/v1/customers/<id>/   — direct edits to a CustomerMaster

The PATCH path is for staff/users correcting things they know are wrong
on the master (a wrong MSIC code that's now polluting auto-fill on every
new invoice for this buyer, an outdated address). It mirrors the
``update_invoice`` editor: strict allowlist, single audit event, alias
filing on rename.
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from . import services
from .models import CustomerMaster
from .serializers import CustomerMasterSerializer


def _active_org(request: Request) -> str | None:
    session = getattr(request, "session", None)
    return session.get("organization_id") if session is not None else None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_customers(request: Request) -> Response:
    organization_id = _active_org(request)
    if not organization_id:
        return Response({"results": []})
    rows = services.list_customer_masters(organization_id=organization_id)
    return Response({"results": CustomerMasterSerializer(rows, many=True).data})


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def customer_detail(request: Request, customer_id: str) -> Response:
    organization_id = _active_org(request)
    if not organization_id:
        return Response(
            {"detail": "No active organization."}, status=status.HTTP_400_BAD_REQUEST
        )

    if request.method == "PATCH":
        return _customer_update(request, organization_id, customer_id)

    customer = services.get_customer_master(
        organization_id=organization_id, customer_id=customer_id
    )
    if customer is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(CustomerMasterSerializer(customer).data)


def _customer_update(
    request: Request, organization_id: str, customer_id: str
) -> Response:
    if not isinstance(request.data, dict):
        return Response(
            {"detail": "Body must be a JSON object."}, status=status.HTTP_400_BAD_REQUEST
        )
    try:
        master = services.update_customer_master(
            organization_id=organization_id,
            customer_id=customer_id,
            updates=request.data,
            actor_user_id=request.user.id,
        )
    except CustomerMaster.DoesNotExist:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    except services.CustomerUpdateError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(CustomerMasterSerializer(master).data)
