"""DRF endpoints for the connectors initiative (Slice 77).

Surface for the customer-facing UI:

  GET    /api/v1/connectors/configs/                          — list integrations
  POST   /api/v1/connectors/configs/                          — create one
  DELETE /api/v1/connectors/configs/<id>/                     — soft-delete
  POST   /api/v1/connectors/configs/<id>/sync-csv/            — upload + propose
  GET    /api/v1/connectors/proposals/<id>/                   — read diff
  POST   /api/v1/connectors/proposals/<id>/apply/             — apply
  POST   /api/v1/connectors/proposals/<id>/revert/            — revert
  GET    /api/v1/connectors/conflicts/                        — list (open by default)
  POST   /api/v1/connectors/conflicts/<id>/resolve/           — resolve
  POST   /api/v1/connectors/locks/                            — lock a field
  POST   /api/v1/connectors/locks/unlock/                     — unlock a field

All endpoints are owner / admin gated for write operations,
viewable by any active member for read operations.
"""

from __future__ import annotations

import json

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    parser_classes,
    permission_classes,
)
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.identity import services as identity_services

from . import sync_services
from .adapters import ConnectorError, get_adapter_class
from .models import (
    IntegrationConfig,
    MasterFieldConflict,
    MasterType,
    SyncProposal,
)
from .serializers import (
    IntegrationConfigSerializer,
    MasterFieldConflictSerializer,
    MasterFieldLockSerializer,
    SyncProposalSerializer,
)


def _active_org_id(request: Request) -> str | None:
    session = getattr(request, "session", None)
    return session.get("organization_id") if session is not None else None


def _gate_active_org(request: Request) -> str | Response:
    org_id = _active_org_id(request)
    if not org_id:
        return Response(
            {"detail": "No active organization."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not identity_services.can_user_act_for_organization(request.user, org_id):
        return Response(
            {"detail": "You are not a member of that organization."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return org_id


def _is_owner_or_admin(user, org_id: str) -> bool:
    """Mirror the membership-role check used elsewhere in the codebase."""
    from apps.identity.models import OrganizationMembership

    role = (
        OrganizationMembership.objects.filter(user=user, organization_id=org_id)
        .values_list("role__name", flat=True)
        .first()
    )
    return role in ("owner", "admin")


# --- IntegrationConfig ------------------------------------------------------


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def configs(request: Request) -> Response:
    org_or_response = _gate_active_org(request)
    if isinstance(org_or_response, Response):
        return org_or_response
    org_id = org_or_response

    if request.method == "GET":
        rows = IntegrationConfig.objects.filter(organization_id=org_id, deleted_at__isnull=True)
        return Response({"results": IntegrationConfigSerializer(rows, many=True).data})

    if not _is_owner_or_admin(request.user, org_id):
        return Response(
            {"detail": "Only owners and admins can configure connectors."},
            status=status.HTTP_403_FORBIDDEN,
        )

    body = request.data or {}
    connector_type = str(body.get("connector_type") or "").strip()
    if not connector_type:
        return Response(
            {"detail": "connector_type is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if connector_type not in IntegrationConfig.ConnectorType.values:
        return Response(
            {
                "detail": (
                    f"Unknown connector_type {connector_type!r}. "
                    f"Allowed: {sorted(IntegrationConfig.ConnectorType.values)}"
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # If an active config already exists for this connector_type +
    # org, return it instead of creating a duplicate (UniqueConstraint
    # would also block, but a clean 200 + existing row is friendlier
    # than a 500 from the constraint).
    existing = IntegrationConfig.objects.filter(
        organization_id=org_id,
        connector_type=connector_type,
        deleted_at__isnull=True,
    ).first()
    if existing is not None:
        return Response(
            IntegrationConfigSerializer(existing).data,
            status=status.HTTP_200_OK,
        )

    config = IntegrationConfig.objects.create(organization_id=org_id, connector_type=connector_type)
    return Response(
        IntegrationConfigSerializer(config).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def config_delete(request: Request, config_id: str) -> Response:
    org_or_response = _gate_active_org(request)
    if isinstance(org_or_response, Response):
        return org_or_response
    org_id = org_or_response
    if not _is_owner_or_admin(request.user, org_id):
        return Response(
            {"detail": "Only owners and admins can disconnect connectors."},
            status=status.HTTP_403_FORBIDDEN,
        )
    config = IntegrationConfig.objects.filter(
        organization_id=org_id, id=config_id, deleted_at__isnull=True
    ).first()
    if config is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    config.deleted_at = timezone.now()
    config.save(update_fields=["deleted_at", "updated_at"])
    return Response(IntegrationConfigSerializer(config).data)


# --- CSV upload + propose ---------------------------------------------------


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser])
def sync_csv(request: Request, config_id: str) -> Response:
    """Upload a CSV + run propose_sync against it.

    Body (multipart):
      file: the CSV upload
      column_mapping: JSON string mapping source CSV columns to
                      ZeroKey master field names
      target: "customers" or "items" (default "customers")

    Returns the created SyncProposal payload so the FE can render
    the preview screen immediately without an extra fetch.
    """
    org_or_response = _gate_active_org(request)
    if isinstance(org_or_response, Response):
        return org_or_response
    org_id = org_or_response
    if not _is_owner_or_admin(request.user, org_id):
        return Response(
            {"detail": "Only owners and admins can run a sync."},
            status=status.HTTP_403_FORBIDDEN,
        )

    config = IntegrationConfig.objects.filter(
        organization_id=org_id, id=config_id, deleted_at__isnull=True
    ).first()
    if config is None:
        return Response(
            {"detail": "Connector not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    if config.connector_type != IntegrationConfig.ConnectorType.CSV:
        return Response(
            {
                "detail": (
                    f"This endpoint only handles CSV connectors. Got {config.connector_type}."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    upload = request.FILES.get("file")
    if upload is None:
        return Response(
            {"detail": "Field 'file' is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    raw_mapping = request.data.get("column_mapping")
    if not raw_mapping:
        return Response(
            {"detail": "Field 'column_mapping' is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        column_mapping = raw_mapping if isinstance(raw_mapping, dict) else json.loads(raw_mapping)
    except (TypeError, ValueError):
        return Response(
            {"detail": "column_mapping must be a JSON object."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    target = (request.data.get("target") or "customers").strip()

    try:
        adapter_class = get_adapter_class(config.connector_type)
    except ConnectorError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    try:
        adapter = adapter_class(
            csv_bytes=upload.read(),
            column_mapping=column_mapping,
            target=target,
        )
    except ConnectorError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    customer_records = list(adapter.fetch_customers()) if target == "customers" else []
    item_records = list(adapter.fetch_items()) if target == "items" else []

    try:
        proposal = sync_services.propose_sync(
            integration_config_id=config.id,
            customer_records=customer_records,
            item_records=item_records,
            actor_user_id=request.user.id,
        )
    except sync_services.SyncError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(
        SyncProposalSerializer(proposal).data,
        status=status.HTTP_201_CREATED,
    )


# --- AutoCount upload + propose (Slice 85) --------------------------------


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser])
def sync_autocount(request: Request, config_id: str) -> Response:
    """Upload an AutoCount CSV export + run propose_sync.

    Body (multipart):
      file: the AutoCount Debtor / Stock-Item CSV export
      target: "customers" or "items" (default "customers")

    Unlike the generic CSV endpoint there's no column_mapping —
    the adapter applies the standard AutoCount column names. If
    the customer's installation has been customised they should
    use the generic CSV connector + the column-mapping wizard.
    """
    org_or_response = _gate_active_org(request)
    if isinstance(org_or_response, Response):
        return org_or_response
    org_id = org_or_response
    if not _is_owner_or_admin(request.user, org_id):
        return Response(
            {"detail": "Only owners and admins can run a sync."},
            status=status.HTTP_403_FORBIDDEN,
        )

    config = IntegrationConfig.objects.filter(
        organization_id=org_id, id=config_id, deleted_at__isnull=True
    ).first()
    if config is None:
        return Response(
            {"detail": "Connector not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    # Slice 98 — same endpoint handles AutoCount, SQL Account and
    # Sage UBS. All three are CSV-driven adapters with baked-in
    # column mappings; the dispatch is via ``get_adapter_class`` so
    # the only thing that varies is which mapping table fires.
    _CSV_DRIVEN_ACCOUNTING = {
        IntegrationConfig.ConnectorType.AUTOCOUNT,
        IntegrationConfig.ConnectorType.SQL_ACCOUNT,
        IntegrationConfig.ConnectorType.SAGE_UBS,
    }
    if config.connector_type not in _CSV_DRIVEN_ACCOUNTING:
        return Response(
            {
                "detail": (
                    f"This endpoint handles AutoCount / SQL Account / Sage UBS connectors. "
                    f"Got {config.connector_type}."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    upload = request.FILES.get("file")
    if upload is None:
        return Response(
            {"detail": "Field 'file' is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    target = (request.data.get("target") or "customers").strip()

    try:
        adapter_class = get_adapter_class(config.connector_type)
    except ConnectorError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    try:
        adapter = adapter_class(csv_bytes=upload.read(), target=target)
    except ConnectorError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    customer_records = list(adapter.fetch_customers()) if target == "customers" else []
    item_records = list(adapter.fetch_items()) if target == "items" else []

    try:
        proposal = sync_services.propose_sync(
            integration_config_id=config.id,
            customer_records=customer_records,
            item_records=item_records,
            actor_user_id=request.user.id,
        )
    except sync_services.SyncError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(
        SyncProposalSerializer(proposal).data,
        status=status.HTTP_201_CREATED,
    )


# --- Proposal lifecycle -----------------------------------------------------


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def proposal_detail(request: Request, proposal_id: str) -> Response:
    org_or_response = _gate_active_org(request)
    if isinstance(org_or_response, Response):
        return org_or_response
    org_id = org_or_response
    proposal = SyncProposal.objects.filter(organization_id=org_id, id=proposal_id).first()
    if proposal is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(SyncProposalSerializer(proposal).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def proposal_apply(request: Request, proposal_id: str) -> Response:
    org_or_response = _gate_active_org(request)
    if isinstance(org_or_response, Response):
        return org_or_response
    org_id = org_or_response
    if not _is_owner_or_admin(request.user, org_id):
        return Response(
            {"detail": "Only owners and admins can apply a sync."},
            status=status.HTTP_403_FORBIDDEN,
        )
    proposal = SyncProposal.objects.filter(organization_id=org_id, id=proposal_id).first()
    if proposal is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    try:
        proposal = sync_services.apply_sync_proposal(
            proposal_id=proposal.id, actor_user_id=request.user.id
        )
    except sync_services.SyncError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(SyncProposalSerializer(proposal).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def proposal_revert(request: Request, proposal_id: str) -> Response:
    org_or_response = _gate_active_org(request)
    if isinstance(org_or_response, Response):
        return org_or_response
    org_id = org_or_response
    if not _is_owner_or_admin(request.user, org_id):
        return Response(
            {"detail": "Only owners and admins can revert a sync."},
            status=status.HTTP_403_FORBIDDEN,
        )
    proposal = SyncProposal.objects.filter(organization_id=org_id, id=proposal_id).first()
    if proposal is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    reason = str((request.data or {}).get("reason") or "").strip()
    try:
        proposal = sync_services.revert_sync_proposal(
            proposal_id=proposal.id,
            actor_user_id=request.user.id,
            reason=reason,
        )
    except sync_services.RevertWindowExpired as exc:
        return Response(
            {"detail": str(exc), "code": "revert_window_expired"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except sync_services.SyncError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(SyncProposalSerializer(proposal).data)


# --- Conflict queue ---------------------------------------------------------


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_conflicts(request: Request) -> Response:
    org_or_response = _gate_active_org(request)
    if isinstance(org_or_response, Response):
        return org_or_response
    org_id = org_or_response
    qs = MasterFieldConflict.objects.filter(organization_id=org_id)
    state = request.query_params.get("state", "open")
    if state == "open":
        qs = qs.filter(resolved_at__isnull=True)
    elif state == "resolved":
        qs = qs.filter(resolved_at__isnull=False)
    elif state != "all":
        return Response(
            {"detail": "state must be one of: open, resolved, all"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    qs = qs[:200]
    return Response({"results": MasterFieldConflictSerializer(qs, many=True).data})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def conflict_resolve(request: Request, conflict_id: str) -> Response:
    org_or_response = _gate_active_org(request)
    if isinstance(org_or_response, Response):
        return org_or_response
    org_id = org_or_response
    if not _is_owner_or_admin(request.user, org_id):
        return Response(
            {"detail": "Only owners and admins can resolve conflicts."},
            status=status.HTTP_403_FORBIDDEN,
        )
    conflict = MasterFieldConflict.objects.filter(organization_id=org_id, id=conflict_id).first()
    if conflict is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    body = request.data or {}
    resolution = str(body.get("resolution") or "").strip()
    custom_value = body.get("custom_value")
    try:
        conflict = sync_services.resolve_field_conflict(
            conflict_id=conflict.id,
            resolution=resolution,
            actor_user_id=request.user.id,
            custom_value=custom_value,
        )
    except sync_services.SyncError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(MasterFieldConflictSerializer(conflict).data)


# --- Field locks ------------------------------------------------------------


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def lock_create(request: Request) -> Response:
    org_or_response = _gate_active_org(request)
    if isinstance(org_or_response, Response):
        return org_or_response
    org_id = org_or_response
    if not _is_owner_or_admin(request.user, org_id):
        return Response(
            {"detail": "Only owners and admins can lock master fields."},
            status=status.HTTP_403_FORBIDDEN,
        )
    body = request.data or {}
    master_type = str(body.get("master_type") or "").strip()
    master_id = str(body.get("master_id") or "").strip()
    field_name = str(body.get("field_name") or "").strip()
    reason = str(body.get("reason") or "").strip()
    if master_type not in {MasterType.CUSTOMER, MasterType.ITEM} or not master_id or not field_name:
        return Response(
            {"detail": ("master_type (customer|item), master_id, field_name are required.")},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        lock = sync_services.lock_field(
            organization_id=org_id,
            master_type=master_type,
            master_id=master_id,
            field_name=field_name,
            actor_user_id=request.user.id,
            reason=reason,
        )
    except sync_services.SyncError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(MasterFieldLockSerializer(lock).data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def lock_remove(request: Request) -> Response:
    org_or_response = _gate_active_org(request)
    if isinstance(org_or_response, Response):
        return org_or_response
    org_id = org_or_response
    if not _is_owner_or_admin(request.user, org_id):
        return Response(
            {"detail": "Only owners and admins can unlock master fields."},
            status=status.HTTP_403_FORBIDDEN,
        )
    body = request.data or {}
    master_type = str(body.get("master_type") or "").strip()
    master_id = str(body.get("master_id") or "").strip()
    field_name = str(body.get("field_name") or "").strip()
    if master_type not in {MasterType.CUSTOMER, MasterType.ITEM} or not master_id or not field_name:
        return Response(
            {"detail": ("master_type (customer|item), master_id, field_name are required.")},
            status=status.HTTP_400_BAD_REQUEST,
        )
    removed = sync_services.unlock_field(
        organization_id=org_id,
        master_type=master_type,
        master_id=master_id,
        field_name=field_name,
        actor_user_id=request.user.id,
    )
    return Response({"removed": removed})
