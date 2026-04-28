"""Ingestion context views.

Phase 1/2 surface:
  POST /api/v1/ingestion/jobs/   — multipart upload, creates IngestionJob
  GET  /api/v1/ingestion/jobs/   — list recent jobs for the active org
  GET  /api/v1/ingestion/jobs/<id>/ — detail with pre-signed download URL
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from . import services
from .serializers import IngestionJobSerializer


def _active_org(request: Request) -> str | None:
    session = getattr(request, "session", None)
    return session.get("organization_id") if session is not None else None


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser])
def upload(request: Request) -> Response:
    organization_id = _active_org(request)
    if not organization_id:
        return Response(
            {"detail": "No active organization. Switch organization first."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    upload_file = request.FILES.get("file")
    if upload_file is None:
        return Response(
            {"detail": "Field 'file' is required (multipart/form-data)."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        result = services.upload_web_file(
            organization_id=organization_id,
            actor_user_id=request.user.id,
            file_obj=upload_file,
            original_filename=upload_file.name,
            mime_type=upload_file.content_type or "application/octet-stream",
            size=upload_file.size,
        )
    except services.IngestionError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(
        IngestionJobSerializer(result.job, context={"request": request}).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_jobs(request: Request) -> Response:
    organization_id = _active_org(request)
    if not organization_id:
        return Response({"results": []})
    jobs = services.list_jobs_for_organization(organization_id=organization_id)
    return Response(
        {"results": IngestionJobSerializer(jobs, many=True, context={"request": request}).data}
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def throughput(request: Request) -> Response:
    organization_id = _active_org(request)
    if not organization_id:
        return Response(
            {"detail": "No active organization. Switch organization first."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        days = int(request.query_params.get("days", "7"))
    except ValueError:
        return Response({"detail": "days must be an integer."}, status=status.HTTP_400_BAD_REQUEST)
    days = max(1, min(days, 90))
    return Response(
        services.throughput_for_organization(organization_id=organization_id, days=days)
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def job_detail(request: Request, job_id: str) -> Response:
    organization_id = _active_org(request)
    if not organization_id:
        return Response({"detail": "No active organization."}, status=status.HTTP_400_BAD_REQUEST)
    job = services.get_job(organization_id=organization_id, job_id=job_id)
    if job is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(
        IngestionJobSerializer(job, context={"request": request, "include_download_url": True}).data
    )
