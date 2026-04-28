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
from apps.extraction.capabilities import (
    EngineUnavailable,
    StructuredExtractResult,
    TextExtractEngine,
    VisionExtractEngine,
)
from apps.extraction.models import Engine, EngineCall
from apps.extraction.registry import get_adapter
from apps.extraction.router import NoRouteFound, pick_engine
from apps.identity.tenancy import set_tenant, super_admin_context
from apps.ingestion.models import IngestionJob

logger = logging.getLogger(__name__)


# Below this confidence the text-extract result is suspect (the document was
# probably scanned, not native), so the pipeline escalates the original bytes
# through a VisionExtract engine and uses its structured output directly.
# Configurable via ``settings.EXTRACTION_VISION_THRESHOLD``; tunable per-tenant
# in a later slice once we have data on what works for which document mix.
DEFAULT_VISION_ESCALATION_THRESHOLD = 0.5


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

    vision_outcome = _maybe_escalate_to_vision(
        job=job,
        primary_engine=decision.engine,
        primary_confidence=result.confidence,
        body=body,
    )

    _complete(
        job,
        engine_name=decision.engine.name,
        text=result.text,
        confidence=result.confidence,
        page_count=result.page_count,
        vision_outcome=vision_outcome,
    )

    return ExtractionResult(
        job=job,
        engine_name=decision.engine.name,
        confidence=result.confidence,
        text_length=len(result.text),
    )


# --- vision escalation --------------------------------------------------------------


@dataclass(frozen=True)
class VisionEscalationOutcome:
    """Result of the optional vision pass after a low-confidence text extract.

    ``applied`` is true only when the vision adapter ran and returned a
    structured result that was applied to the Invoice. ``False`` means the
    pipeline either didn't escalate (confidence above threshold) or escalated
    but couldn't apply (no route, adapter unavailable, vendor failure). In
    the unsuccessful cases, ``reason`` carries the explanation for the audit
    log; the regular FieldStructure path then runs as the fallback.
    """

    attempted: bool
    applied: bool
    engine_name: str
    fields: dict[str, str]
    per_field_confidence: dict[str, float]
    overall_confidence: float
    reason: str = ""


def _vision_threshold() -> float:
    return float(
        getattr(settings, "EXTRACTION_VISION_THRESHOLD", DEFAULT_VISION_ESCALATION_THRESHOLD)
    )


def _maybe_escalate_to_vision(
    *,
    job: IngestionJob,
    primary_engine: Engine,
    primary_confidence: float,
    body: bytes,
) -> VisionEscalationOutcome:
    """Run a vision pass when the primary text-extract returned low confidence.

    Failure modes are graceful — every "no, we can't" branch records the
    reason on the audit log and returns ``applied=False`` so the caller
    falls through to the regular text-then-FieldStructure path.
    """
    threshold = _vision_threshold()
    not_applied = VisionEscalationOutcome(
        attempted=False,
        applied=False,
        engine_name="",
        fields={},
        per_field_confidence={},
        overall_confidence=0.0,
    )
    if primary_confidence >= threshold:
        return not_applied

    record_event(
        action_type="ingestion.job.vision_escalation_started",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="extraction.pipeline",
        organization_id=str(job.organization_id),
        affected_entity_type="IngestionJob",
        affected_entity_id=str(job.id),
        payload={
            "primary_engine": primary_engine.name,
            "primary_confidence": str(primary_confidence),
            "threshold": str(threshold),
        },
    )

    try:
        decision = pick_engine(
            capability=Engine.Capability.VISION_EXTRACT,
            mime_type=job.file_mime_type,
        )
    except NoRouteFound as exc:
        return _record_escalation_failure(job, reason=f"no vision route: {exc}")

    try:
        adapter = get_adapter(decision.engine.name)
    except KeyError as exc:
        return _record_escalation_failure(job, reason=f"vision adapter missing: {exc}")

    if not isinstance(adapter, VisionExtractEngine):
        return _record_escalation_failure(
            job,
            reason=(
                f"adapter {decision.engine.name!r} is registered for "
                f"{decision.engine.capability} but isn't a VisionExtractEngine"
            ),
        )

    # Lazy import — avoids a circular extraction → submission → extraction
    # at module load. Cross-context service calls only.
    from apps.submission.services import INVOICE_HEADER_FIELDS, LINE_ITEMS_KEY

    target_schema = [*INVOICE_HEADER_FIELDS, LINE_ITEMS_KEY]

    started_at = timezone.now()
    started_perf = time.perf_counter()
    try:
        vision_result: StructuredExtractResult = adapter.extract_vision(
            body=body, mime_type=job.file_mime_type, target_schema=target_schema
        )
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
        return _record_escalation_failure(job, reason=f"vision unavailable: {exc}")
    except Exception as exc:  # adapter failures are graceful — escalation never breaks the pipeline
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
        return _record_escalation_failure(
            job, reason=f"vision failed: {type(exc).__name__}: {exc}"
        )

    _record_call(
        engine=decision.engine,
        job=job,
        started_at=started_at,
        duration_ms=int((time.perf_counter() - started_perf) * 1000),
        outcome=EngineCall.Outcome.SUCCESS,
        error_class="",
        cost_micros=vision_result.cost_micros,
        confidence=vision_result.overall_confidence,
        diagnostics=vision_result.diagnostics,
    )

    return VisionEscalationOutcome(
        attempted=True,
        applied=True,
        engine_name=decision.engine.name,
        fields=dict(vision_result.fields),
        per_field_confidence=dict(vision_result.per_field_confidence),
        overall_confidence=vision_result.overall_confidence,
    )


def _record_escalation_failure(job: IngestionJob, *, reason: str) -> VisionEscalationOutcome:
    """Audit a non-fatal vision escalation miss; caller falls back to text path."""
    record_event(
        action_type="ingestion.job.vision_escalation_skipped",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="extraction.pipeline",
        organization_id=str(job.organization_id),
        affected_entity_type="IngestionJob",
        affected_entity_id=str(job.id),
        payload={"reason": reason[:255]},
    )
    return VisionEscalationOutcome(
        attempted=True,
        applied=False,
        engine_name="",
        fields={},
        per_field_confidence={},
        overall_confidence=0.0,
        reason=reason,
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
    vision_outcome: VisionEscalationOutcome | None = None,
) -> None:
    # If vision escalation succeeded, the recorded extraction_engine reflects
    # the combined path so the audit trail makes the escalation visible.
    if vision_outcome and vision_outcome.applied:
        recorded_engine = f"{engine_name}+{vision_outcome.engine_name}"
        recorded_confidence = vision_outcome.overall_confidence
    else:
        recorded_engine = engine_name
        recorded_confidence = confidence

    job.extracted_text = text
    job.extraction_engine = recorded_engine
    job.extraction_confidence = recorded_confidence
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

    extracted_payload: dict = {
        "engine": recorded_engine,
        "confidence": str(recorded_confidence),
        "page_count": page_count,
        "text_length": len(text),
    }
    if vision_outcome and vision_outcome.applied:
        extracted_payload["primary_text_engine"] = engine_name
        extracted_payload["primary_text_confidence"] = str(confidence)
        extracted_payload["vision_engine"] = vision_outcome.engine_name
    record_event(
        action_type="ingestion.job.extracted",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="extraction.pipeline",
        organization_id=str(job.organization_id),
        affected_entity_type="IngestionJob",
        affected_entity_id=str(job.id),
        payload=extracted_payload,
    )

    # Create the Invoice row + chain a structuring task. Cross-context import
    # of services (not models) is allowed.
    from apps.submission.services import (
        apply_structured_fields,
        create_invoice_from_extraction,
    )

    invoice = create_invoice_from_extraction(
        organization_id=job.organization_id,
        ingestion_job_id=job.id,
        extracted_text=text,
    )

    if vision_outcome and vision_outcome.applied:
        # Vision already produced structured fields; write them straight to
        # the Invoice and skip the FieldStructure step. Same shape as a
        # successful FieldStructure pass, so the review UI sees no
        # difference between the two paths.
        apply_structured_fields(
            invoice=invoice,
            engine_name=vision_outcome.engine_name,
            fields=vision_outcome.fields,
            per_field_confidence=vision_outcome.per_field_confidence,
            overall_confidence=vision_outcome.overall_confidence,
        )
        return

    # Queue the structuring task when we have text to structure on. Otherwise
    # finalize directly: a totally empty extraction (e.g. scanned PDF + no
    # vision adapter available) still has to run validation so the review
    # UI surfaces the required-field errors honestly. Without this branch
    # the Invoice would sit in EXTRACTING forever and the review banner
    # would falsely report "looks good to submit".
    if text.strip():
        from django.db import transaction as _txn

        from apps.extraction.tasks import structure_invoice as structure_task

        _txn.on_commit(lambda: structure_task.delay(str(invoice.id)))
    else:
        from apps.submission.services import finalize_invoice_without_structuring

        finalize_invoice_without_structuring(
            invoice=invoice,
            reason="No extracted text and no vision adapter available.",
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
