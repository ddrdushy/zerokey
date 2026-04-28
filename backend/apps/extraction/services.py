"""Extraction pipeline orchestration.

The flow for a single IngestionJob:

    received  --classify-->  classifying  --extract-->  extracting
                                                            |
                                                            v
        ready_for_review     <----------- success ----------+
                                                            |
                                                            v
                                                          error

Each transition emits an audit event. EngineCall rows record the per-call
telemetry. The Invoice / LineItem entities (the structured output) land in
the next slice; for now we store the raw text + chosen engine + confidence
on the IngestionJob row so the review screen can display it.

Phase 2 cut: only ``text_extract`` is wired end-to-end. Vision and
field-structure adapters exist and can be invoked manually but are not part
of the auto-pipeline yet — they require the Invoice schema to land first.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.extraction.capabilities import EngineUnavailable, TextExtractEngine
from apps.extraction.models import Engine, EngineCall
from apps.extraction.registry import get_adapter
from apps.extraction.router import NoRouteFound, pick_engine
from apps.identity.tenancy import set_tenant, super_admin_context
from apps.ingestion.models import IngestionJob

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractionResult:
    job: IngestionJob
    engine_name: str
    confidence: float
    text_length: int


def run_extraction(job_id: UUID | str) -> ExtractionResult:
    """Drive a single IngestionJob through the extraction pipeline.

    Idempotent on terminal states: if the job is already past ``received``,
    returns without doing work. The Celery task may fire the same job_id
    twice (network retry, dead-letter requeue); the second run aborts.

    The Celery worker has no tenant context set on the connection. We use
    a brief super-admin context to discover the job's tenant, then switch
    to that tenant for the rest of the run so RLS filters everything to
    one customer's data.
    """
    with super_admin_context(reason="extraction.pipeline:job_lookup"):
        try:
            job = IngestionJob.objects.get(id=job_id)
        except IngestionJob.DoesNotExist:
            logger.warning("run_extraction: job %s not found", job_id)
            raise

    # Pin the rest of the run to this tenant. Every subsequent query, every
    # audit event, every EngineCall write is scoped to the right org.
    set_tenant(job.organization_id)

    if job.status != IngestionJob.Status.RECEIVED:
        logger.info(
            "run_extraction: job %s already past received (status=%s); skipping",
            job_id,
            job.status,
        )
        return ExtractionResult(
            job=job,
            engine_name=job.extraction_engine,
            confidence=job.extraction_confidence or 0.0,
            text_length=len(job.extracted_text),
        )

    _transition(job, IngestionJob.Status.CLASSIFYING, payload={"reason": "extraction.started"})

    try:
        decision = pick_engine(
            capability=Engine.Capability.TEXT_EXTRACT,
            mime_type=job.file_mime_type,
        )
    except NoRouteFound as exc:
        _fail(job, error=str(exc))
        raise

    _transition(
        job,
        IngestionJob.Status.EXTRACTING,
        payload={"engine": decision.engine.name, "rule_id": decision.matched_rule_id},
    )

    body = _read_object(job)

    try:
        adapter = get_adapter(decision.engine.name)
    except KeyError as exc:
        _fail(job, error=str(exc))
        raise

    if not isinstance(adapter, TextExtractEngine):
        _fail(
            job,
            error=(
                f"Adapter {decision.engine.name!r} is registered for "
                f"{decision.engine.capability} but isn't a TextExtractEngine."
            ),
        )
        raise TypeError(f"Adapter {decision.engine.name} is not a TextExtractEngine")

    started_at = timezone.now()
    started_perf = time.perf_counter()
    try:
        result = adapter.extract_text(body=body, mime_type=job.file_mime_type)
    except EngineUnavailable as exc:
        _record_call(
            engine=decision.engine,
            job=job,
            started_at=started_at,
            duration_ms=int((time.perf_counter() - started_perf) * 1000),
            outcome=EngineCall.Outcome.UNAVAILABLE,
            error_class=type(exc).__name__,
            cost_micros=0,
            confidence=None,
            diagnostics={"detail": str(exc)},
        )
        _fail(job, error=str(exc))
        raise
    except Exception as exc:
        _record_call(
            engine=decision.engine,
            job=job,
            started_at=started_at,
            duration_ms=int((time.perf_counter() - started_perf) * 1000),
            outcome=EngineCall.Outcome.FAILURE,
            error_class=type(exc).__name__,
            cost_micros=0,
            confidence=None,
            diagnostics={"detail": str(exc)[:500]},
        )
        _fail(job, error=f"{type(exc).__name__}: {exc}")
        raise

    _record_call(
        engine=decision.engine,
        job=job,
        started_at=started_at,
        duration_ms=int((time.perf_counter() - started_perf) * 1000),
        outcome=EngineCall.Outcome.SUCCESS,
        error_class="",
        cost_micros=result.cost_micros,
        confidence=result.confidence,
        diagnostics=result.diagnostics,
    )

    _complete(
        job,
        engine_name=decision.engine.name,
        text=result.text,
        confidence=result.confidence,
        page_count=result.page_count,
    )

    return ExtractionResult(
        job=job,
        engine_name=decision.engine.name,
        confidence=result.confidence,
        text_length=len(result.text),
    )


# --- transitions ---------------------------------------------------------------------


def _transition(
    job: IngestionJob,
    new_status: IngestionJob.Status,
    *,
    payload: dict | None = None,
) -> None:
    previous = job.status
    job.status = new_status
    job.state_transitions = (job.state_transitions or []) + [
        {"status": new_status.value, "at": _iso(timezone.now())}
    ]
    job.save(update_fields=["status", "state_transitions", "updated_at"])

    record_event(
        action_type="ingestion.job.state_changed",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="extraction.pipeline",
        organization_id=str(job.organization_id),
        affected_entity_type="IngestionJob",
        affected_entity_id=str(job.id),
        payload={"from": previous, "to": new_status.value, **(payload or {})},
    )


@transaction.atomic
def _complete(
    job: IngestionJob,
    *,
    engine_name: str,
    text: str,
    confidence: float,
    page_count: int,
) -> None:
    job.extracted_text = text
    job.extraction_engine = engine_name
    job.extraction_confidence = confidence
    job.completed_at = timezone.now()
    job.status = IngestionJob.Status.READY_FOR_REVIEW
    job.state_transitions = (job.state_transitions or []) + [
        {"status": IngestionJob.Status.READY_FOR_REVIEW.value, "at": _iso(job.completed_at)}
    ]
    job.save(
        update_fields=[
            "extracted_text",
            "extraction_engine",
            "extraction_confidence",
            "completed_at",
            "status",
            "state_transitions",
            "updated_at",
        ]
    )

    record_event(
        action_type="ingestion.job.extracted",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="extraction.pipeline",
        organization_id=str(job.organization_id),
        affected_entity_type="IngestionJob",
        affected_entity_id=str(job.id),
        payload={
            "engine": engine_name,
            "confidence": str(confidence),
            "page_count": page_count,
            "text_length": len(text),
        },
    )


@transaction.atomic
def _fail(job: IngestionJob, *, error: str) -> None:
    previous = job.status
    job.status = IngestionJob.Status.ERROR
    job.error_message = error[:8000]
    job.completed_at = timezone.now()
    job.state_transitions = (job.state_transitions or []) + [
        {"status": IngestionJob.Status.ERROR.value, "at": _iso(job.completed_at)}
    ]
    job.save(
        update_fields=[
            "status",
            "error_message",
            "completed_at",
            "state_transitions",
            "updated_at",
        ]
    )

    record_event(
        action_type="ingestion.job.errored",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="extraction.pipeline",
        organization_id=str(job.organization_id),
        affected_entity_type="IngestionJob",
        affected_entity_id=str(job.id),
        payload={"from": previous, "error": error[:255]},
    )


# --- I/O helpers ---------------------------------------------------------------------


def _read_object(job: IngestionJob) -> bytes:
    """Pull the original from S3 into memory.

    Phase 2 ingests up to 25 MB so in-memory is fine. Larger formats (Excel
    workbooks, ZIPs) stream in a later iteration.
    """
    from apps.integrations.storage import _client

    response = _client().get_object(Bucket=settings.S3_BUCKET_UPLOADS, Key=job.s3_object_key)
    return response["Body"].read()


def _record_call(
    *,
    engine: Engine,
    job: IngestionJob,
    started_at: datetime,
    duration_ms: int,
    outcome: str,
    error_class: str,
    cost_micros: int,
    confidence: float | None,
    diagnostics: dict,
) -> None:
    EngineCall.objects.create(
        engine=engine,
        request_id=job.id,
        organization_id=job.organization_id,
        started_at=started_at,
        duration_ms=duration_ms,
        outcome=outcome,
        error_class=error_class,
        cost_micros=cost_micros,
        confidence=confidence,
        diagnostics=diagnostics,
    )


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds")
