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
from datetime import timedelta
from typing import IO, Any
from uuid import UUID

from django.conf import settings
from django.db import models, transaction
from django.db.models.functions import TruncDate
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


# Slice 101 — file types we'll unpack out of a ZIP. Anything else inside
# the archive (Word docs, .DS_Store, nested zips) is silently skipped so
# a sloppy archive doesn't fail the whole upload.
_ZIP_INNER_ALLOWED_EXT = (
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".csv",
    ".xls",
    ".xlsx",
)
# Hard cap on inner file count — if a zip-bomb has thousands of entries
# we refuse rather than fan-out a runaway extraction queue.
_ZIP_MAX_INNER_FILES = 200


def _ext_to_mime(filename: str) -> str:
    f = filename.lower()
    if f.endswith(".pdf"):
        return "application/pdf"
    if f.endswith(".png"):
        return "image/png"
    if f.endswith(".webp"):
        return "image/webp"
    if f.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if f.endswith(".csv"):
        return "text/csv"
    if f.endswith(".xls"):
        return "application/vnd.ms-excel"
    if f.endswith(".xlsx"):
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return ""


@dataclass(frozen=True)
class BulkUploadResult:
    """Result of a multi-file ZIP unpack — N inner jobs + the parent zip."""

    parent_job: IngestionJob
    child_jobs: list[IngestionJob]


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

    # Kick off extraction asynchronously. on_commit so the task only runs after
    # the row is durable — otherwise the worker can race the transaction.
    from django.db import transaction as _txn

    from apps.extraction.tasks import extract_invoice

    _txn.on_commit(lambda: extract_invoice.delay(str(job.id)))

    return UploadResult(job=job)


def upload_zip_archive(
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    file_obj: IO[bytes],
    original_filename: str,
    size: int,
) -> BulkUploadResult:
    """Unpack a ZIP into one IngestionJob per supported inner file.

    Slice 101 — closes the PRD Domain 1 promise: "A single ZIP file
    containing many invoices uploads as a single action and unpacks
    into individual jobs."

    The parent ZIP itself is recorded as an IngestionJob with status
    BUNDLE so the upload audit chain still has a row that anchors the
    user's "I uploaded archive.zip" gesture; that row is marked
    skipped (no extraction runs on it) and links to the children via
    its payload. Each child job is a fully independent extraction
    target — the existing pipeline doesn't need to know it came
    from a bundle.

    Hard caps: 25 MB total upload (same as the single-file ceiling),
    200 inner files max. Inner files with unsupported extensions
    are silently skipped — typical archives include .DS_Store /
    desktop.ini / nested zips that aren't invoices.
    """
    import zipfile

    if size > MAX_UPLOAD_BYTES:
        raise IngestionError(
            f"ZIP exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit."
        )

    # Read the whole archive into memory so we can rewind for both the
    # parent-blob upload and the per-entry unpacking. Bounded by
    # MAX_UPLOAD_BYTES so this is at most 25 MB.
    raw = file_obj.read()
    if not raw:
        raise IngestionError("ZIP archive is empty.")

    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise IngestionError(f"Not a valid ZIP archive: {exc}") from exc

    members = [m for m in archive.namelist() if not m.endswith("/")]
    if len(members) > _ZIP_MAX_INNER_FILES:
        raise IngestionError(
            f"ZIP contains {len(members)} files — limit is {_ZIP_MAX_INNER_FILES}."
        )

    # First pass: figure out which entries are real invoices we can
    # extract from. We do this BEFORE creating the parent row so a
    # ZIP with zero supported files fails fast with a clear message.
    candidates: list[tuple[str, str, bytes]] = []
    for name in members:
        # Strip leading directory components — Mac archives often nest
        # everything under "__MACOSX/" or the original folder name.
        leaf = name.rsplit("/", 1)[-1]
        if not leaf or leaf.startswith(".") or "__MACOSX" in name:
            continue
        mime = _ext_to_mime(leaf)
        if not mime:
            continue
        try:
            inner_bytes = archive.read(name)
        except (zipfile.BadZipFile, RuntimeError):
            continue
        if not inner_bytes:
            continue
        if len(inner_bytes) > MAX_UPLOAD_BYTES:
            continue  # individual file inside is too big — skip silently
        candidates.append((leaf, mime, inner_bytes))

    if not candidates:
        raise IngestionError(
            "ZIP contained no supported invoice files (PDF / image / Excel / CSV)."
        )

    # Now do the work in one transaction so a partial unpack never leaves
    # orphan rows.
    with transaction.atomic():
        parent_job_id = uuid.uuid4()
        parent_object_key = storage.ingestion_object_key(
            organization_id=organization_id,
            job_id=parent_job_id,
            filename=original_filename,
        )
        parent_stored = storage.put_object(
            bucket=settings.S3_BUCKET_UPLOADS,
            key=parent_object_key,
            body=io.BytesIO(raw),
            content_type="application/zip",
        )
        # Parent stays in BUNDLE state — the extraction pipeline never
        # touches it. The presence of children below is the audit story.
        parent_job = IngestionJob.objects.create(
            id=parent_job_id,
            organization_id=organization_id,
            source_channel=IngestionJob.SourceChannel.WEB_UPLOAD,
            original_filename=original_filename,
            file_size=parent_stored.size,
            file_mime_type="application/zip",
            s3_object_key=parent_object_key,
            status=IngestionJob.Status.BUNDLE,
            state_transitions=[
                {"status": IngestionJob.Status.BUNDLE.value, "at": _now_iso()}
            ],
        )

        children: list[IngestionJob] = []
        for leaf, mime, inner_bytes in candidates:
            child_id = uuid.uuid4()
            child_key = storage.ingestion_object_key(
                organization_id=organization_id,
                job_id=child_id,
                filename=leaf,
            )
            stored = storage.put_object(
                bucket=settings.S3_BUCKET_UPLOADS,
                key=child_key,
                body=io.BytesIO(inner_bytes),
                content_type=mime,
            )
            child = IngestionJob.objects.create(
                id=child_id,
                organization_id=organization_id,
                source_channel=IngestionJob.SourceChannel.WEB_UPLOAD,
                original_filename=leaf,
                file_size=stored.size,
                file_mime_type=mime,
                s3_object_key=child_key,
                status=IngestionJob.Status.RECEIVED,
                state_transitions=[
                    {"status": IngestionJob.Status.RECEIVED.value, "at": _now_iso()}
                ],
                source_identifier=f"bundle:{parent_job_id}",
            )
            children.append(child)

        record_event(
            action_type="ingestion.bundle.unpacked",
            actor_type=AuditEvent.ActorType.USER,
            actor_id=str(actor_user_id),
            organization_id=str(organization_id),
            affected_entity_type="IngestionJob",
            affected_entity_id=str(parent_job.id),
            payload={
                "original_filename": original_filename,
                "file_size": parent_stored.size,
                "child_count": len(children),
                "child_ids": [str(c.id) for c in children],
                "skipped_count": len(members) - len(candidates),
            },
        )

        from django.db import transaction as _txn

        from apps.extraction.tasks import extract_invoice

        # Fire one extract task per child, after the txn commits so
        # the worker doesn't race the inserts.
        child_ids = [str(c.id) for c in children]
        _txn.on_commit(
            lambda ids=child_ids: [extract_invoice.delay(cid) for cid in ids]
        )

    return BulkUploadResult(parent_job=parent_job, child_jobs=children)


import io  # placed here to keep the upload_zip_archive helper self-contained


@transaction.atomic
def upload_api_file(
    *,
    organization_id: UUID,
    actor_api_key_id: UUID,
    file_obj: IO[bytes],
    original_filename: str,
    mime_type: str,
    size: int,
    source_identifier: str = "",
) -> UploadResult:
    """API-key-driven sibling of ``upload_web_file`` (Slice 78).

    The customer's vendor system / custom script POSTs an invoice
    via the public API. Otherwise identical to the web upload path —
    same S3 storage + same extraction pipeline + same audit shape —
    just:

      - ``source_channel`` is ``API`` not ``WEB_UPLOAD``.
      - Audit ``actor_type`` is ``EXTERNAL`` (the actor is an
        external system, not a logged-in user); ``actor_id`` is the
        APIKey row id so audit replay can join back to which key
        was used.
      - Optional ``source_identifier`` carries the integrator's
        own reference for the document (their invoice number,
        vendor system row id, etc.) — surfaces in the audit
        payload + on the IngestionJob row for downstream dedup.
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
        source_channel=IngestionJob.SourceChannel.API,
        source_identifier=(source_identifier or "")[:255],
        original_filename=original_filename,
        file_size=stored.size,
        file_mime_type=stored.content_type,
        s3_object_key=object_key,
        status=IngestionJob.Status.RECEIVED,
        state_transitions=[{"status": IngestionJob.Status.RECEIVED.value, "at": _now_iso()}],
    )

    record_event(
        action_type="ingestion.job.received",
        actor_type=AuditEvent.ActorType.EXTERNAL,
        actor_id=str(actor_api_key_id),
        organization_id=str(organization_id),
        affected_entity_type="IngestionJob",
        affected_entity_id=str(job.id),
        payload={
            "source_channel": IngestionJob.SourceChannel.API.value,
            "source_identifier": (source_identifier or "")[:255],
            "original_filename": original_filename,
            "file_size": stored.size,
            "file_mime_type": stored.content_type,
            "s3_object_key": object_key,
        },
    )

    from django.db import transaction as _txn

    from apps.extraction.tasks import extract_invoice

    _txn.on_commit(lambda: extract_invoice.delay(str(job.id)))

    return UploadResult(job=job)


def list_jobs_for_organization(*, organization_id: UUID, limit: int = 50) -> list[IngestionJob]:
    return list(
        IngestionJob.objects.filter(organization_id=organization_id).order_by("-upload_timestamp")[
            :limit
        ]
    )


def get_job(*, organization_id: UUID, job_id: UUID) -> IngestionJob | None:
    return IngestionJob.objects.filter(organization_id=organization_id, id=job_id).first()


# Status buckets for the dashboard throughput chart. The chart has two
# series ("validated" and "needs review"); everything else is excluded
# from the chart but surfaced in the totals so the user understands the
# full picture.
_VALIDATED_STATUSES = frozenset({IngestionJob.Status.VALIDATED})
_REVIEW_STATUSES = frozenset(
    {
        IngestionJob.Status.READY_FOR_REVIEW,
        IngestionJob.Status.AWAITING_APPROVAL,
    }
)
_FAILED_STATUSES = frozenset(
    {IngestionJob.Status.ERROR, IngestionJob.Status.REJECTED, IngestionJob.Status.CANCELLED}
)


def throughput_for_organization(*, organization_id: UUID | str, days: int = 7) -> dict[str, Any]:
    """Daily ingestion throughput for the dashboard chart.

    Buckets jobs by ``upload_timestamp`` date over the trailing ``days`` window
    (gap-filled with zeroes), splitting each bucket into ``validated`` (jobs
    that reached LHDN-validated) and ``review`` (jobs sitting in human-review
    states). Jobs in transient pipeline states are counted under ``in_flight``
    in the summary block but not plotted; failed jobs roll into ``failed``.

    Returns:
        ``series``  — list of ``{date, day, validated, review}`` for the
                      window, oldest first, length ``days``.
        ``totals``  — totals across the window:
                      ``validated``, ``review``, ``in_flight``, ``failed``,
                      ``uploads``.
    """
    base = IngestionJob.objects.filter(organization_id=organization_id)
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)

    # Window-restricted slice for the daily series; totals over the same window
    # so the summary line reconciles with the chart.
    windowed = base.filter(upload_timestamp__date__gte=start)

    daily_rows = (
        windowed.annotate(day=TruncDate("upload_timestamp"))
        .values("day", "status")
        .annotate(count=models.Count("id"))
    )

    # day_iso → {validated, review}
    by_day: dict[str, dict[str, int]] = {}
    totals = {
        "validated": 0,
        "review": 0,
        "in_flight": 0,
        "failed": 0,
        "uploads": 0,
    }
    for row in daily_rows:
        day_iso = row["day"].isoformat()
        bucket = by_day.setdefault(day_iso, {"validated": 0, "review": 0})
        count = int(row["count"])
        totals["uploads"] += count
        status_value = row["status"]
        if status_value in _VALIDATED_STATUSES:
            bucket["validated"] += count
            totals["validated"] += count
        elif status_value in _REVIEW_STATUSES:
            bucket["review"] += count
            totals["review"] += count
        elif status_value in _FAILED_STATUSES:
            totals["failed"] += count
        else:
            totals["in_flight"] += count

    series: list[dict[str, Any]] = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        day_iso = day.isoformat()
        bucket = by_day.get(day_iso, {"validated": 0, "review": 0})
        series.append(
            {
                "date": day_iso,
                "day": day.strftime("%a"),
                "validated": bucket["validated"],
                "review": bucket["review"],
            }
        )

    return {"series": series, "totals": totals}


def presigned_download(*, job: IngestionJob, ttl: int = storage.DEFAULT_PRESIGNED_URL_TTL) -> str:
    return storage.presigned_download_url(
        bucket=settings.S3_BUCKET_UPLOADS,
        key=job.s3_object_key,
        ttl=ttl,
    )


def _now_iso() -> str:
    return timezone.now().isoformat(timespec="milliseconds")
