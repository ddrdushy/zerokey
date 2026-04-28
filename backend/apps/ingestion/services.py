"""Service-layer interface for the ingestion context.

Other contexts (and the views in this app) call these functions; nothing else
talks to the IngestionJob table directly.

Phase 1 / 2 cut: the upload pipeline writes the file to S3, creates the job
in ``received`` state, and emits the audit event. Subsequent slices add the
state-machine transitions that drive classification → extraction → submission.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import IO
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.integrations import storage

from .models import IngestionJob

logger = logging.getLogger(__name__)


# Per docs/PRODUCT_REQUIREMENTS.md "drag-and-drop web upload" — 25 MB per file.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

ALLOWED_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/webp",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/csv",
        "application/zip",
    }
)


class IngestionError(Exception):
    """Raised when an upload fails validation or storage."""


@dataclass(frozen=True)
class UploadResult:
    job: IngestionJob


@transaction.atomic
def upload_web_file(
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    file_obj: IO[bytes],
    original_filename: str,
    mime_type: str,
    size: int,
) -> UploadResult:
    """Persist a freshly-uploaded file to S3 and record the job.

    The file is uploaded *before* the row is created so a successful return
    means the artifact and metadata are consistent. If S3 succeeds and the DB
    insert fails, we orphan a blob (cleaned up by a retention sweep); if S3
    fails, no DB row is created.
    """
    if size > MAX_UPLOAD_BYTES:
        raise IngestionError(
            f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit."
        )
    if mime_type not in ALLOWED_MIME_TYPES:
        raise IngestionError(f"Unsupported file type: {mime_type}")

    job_id = uuid.uuid4()
    object_key = storage.ingestion_object_key(
        organization_id=organization_id,
        job_id=job_id,
        filename=original_filename,
    )

    stored = storage.put_object(
        bucket=settings.S3_BUCKET_UPLOADS,
        key=object_key,
        body=file_obj,
        content_type=mime_type,
    )

    job = IngestionJob.objects.create(
        id=job_id,
        organization_id=organization_id,
        source_channel=IngestionJob.SourceChannel.WEB_UPLOAD,
        original_filename=original_filename,
        file_size=stored.size,
        file_mime_type=stored.content_type,
        s3_object_key=object_key,
        status=IngestionJob.Status.RECEIVED,
        state_transitions=[{"status": IngestionJob.Status.RECEIVED.value, "at": _now_iso()}],
    )

    record_event(
        action_type="ingestion.job.received",
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(actor_user_id),
        organization_id=str(organization_id),
        affected_entity_type="IngestionJob",
        affected_entity_id=str(job.id),
        payload={
            "source_channel": IngestionJob.SourceChannel.WEB_UPLOAD.value,
            "original_filename": original_filename,
            "file_size": stored.size,
            "file_mime_type": stored.content_type,
            "s3_object_key": object_key,
        },
    )

    return UploadResult(job=job)


def list_jobs_for_organization(*, organization_id: UUID, limit: int = 50) -> list[IngestionJob]:
    return list(
        IngestionJob.objects.filter(organization_id=organization_id).order_by("-upload_timestamp")[
            :limit
        ]
    )


def get_job(*, organization_id: UUID, job_id: UUID) -> IngestionJob | None:
    return IngestionJob.objects.filter(organization_id=organization_id, id=job_id).first()


def presigned_download(*, job: IngestionJob, ttl: int = storage.DEFAULT_PRESIGNED_URL_TTL) -> str:
    return storage.presigned_download_url(
        bucket=settings.S3_BUCKET_UPLOADS,
        key=job.s3_object_key,
        ttl=ttl,
    )


def _now_iso() -> str:
    return timezone.now().isoformat(timespec="milliseconds")
