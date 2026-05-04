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
    TextExtractResult,
    VisionExtractEngine,
)
from apps.extraction.models import Engine, EngineCall
from apps.extraction.registry import get_adapter
from apps.extraction.router import NoRouteFound, pick_engine, pick_fallback_engine
from apps.identity.tenancy import set_tenant, super_admin_context
from apps.ingestion.models import IngestionJob

logger = logging.getLogger(__name__)


# Below this confidence the text-extract result is suspect (the document was
# probably scanned, not native), so the pipeline escalates the original bytes
# through a VisionExtract engine and uses its structured output directly.
# Configurable via ``settings.EXTRACTION_VISION_THRESHOLD``; tunable per-tenant
# in a later slice once we have data on what works for which document mix.
DEFAULT_VISION_ESCALATION_THRESHOLD = 0.5

# When pdfplumber returns sparse text on a PDF (likely scanned), the pipeline
# tries a second TextExtract engine (EasyOCR) BEFORE paying for vision. If
# the OCR pass returns text whose confidence beats this floor, we use it as
# the primary text and let the regular FieldStructure path proceed (free
# Ollama structuring). If OCR also falls below this floor, the vision
# escalation runs as before. ``settings.EXTRACTION_OCR_THRESHOLD`` overrides.
DEFAULT_OCR_ESCALATION_THRESHOLD = 0.5


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

    # Slice 32: when the primary text-extract returned sparse text (likely
    # a scanned PDF), try a second TextExtract engine (EasyOCR) BEFORE paying
    # for vision. If OCR returns text whose confidence beats the floor, we
    # use it as the primary text — the rest of the pipeline (free Ollama
    # structuring) proceeds unchanged. If OCR also fails, the vision
    # escalation kicks in as before.
    ocr_outcome = _maybe_escalate_to_ocr(
        job=job,
        primary_engine=decision.engine,
        primary_confidence=result.confidence,
        body=body,
    )
    if ocr_outcome.applied:
        # Substitute the OCR result for the rest of the pipeline. Engine
        # name is recorded as "pdfplumber+easyocr" so the audit trail
        # makes the escalation visible without inventing a new field.
        result = ocr_outcome.replacement_result
        recorded_engine_name = f"{decision.engine.name}+{ocr_outcome.engine_name}"
    else:
        recorded_engine_name = decision.engine.name

    # Slice 54: respect the per-tenant extraction mode. ``ocr_only`` mode
    # short-circuits the vision-escalation path so customers in the
    # cost-saver lane never pay for an LLM vision call. The
    # FieldStructure step (downstream of _complete) reads the same flag
    # and uses the regex floor structurer instead of Claude/Ollama.
    if _extraction_mode_for_org(job.organization_id) == "ocr_only":
        vision_outcome = VisionEscalationOutcome(
            attempted=False,
            applied=False,
            engine_name="",
            fields={},
            per_field_confidence={},
            overall_confidence=0.0,
            reason="ocr_only_mode",
        )
    else:
        vision_outcome = _maybe_escalate_to_vision(
            job=job,
            primary_engine=decision.engine,
            primary_confidence=result.confidence,
            body=body,
        )

    _complete(
        job,
        engine_name=recorded_engine_name,
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


# --- extraction-mode lookup (Slice 54) ----------------------------------------------


def _extraction_mode_for_org(organization_id) -> str:
    """Return the org's chosen extraction lane (``ai_vision`` | ``ocr_only``).

    Lazy import + super-admin elevation so the worker (which has just
    ``set_tenant`` to this org) can always read the row regardless of
    its RLS policy. Falls back to ``ai_vision`` if the org row is
    missing — same default as the model field.
    """
    from apps.identity.models import Organization
    from apps.identity.tenancy import super_admin_context

    with super_admin_context(reason="extraction.mode_lookup"):
        mode = (
            Organization.objects.filter(id=organization_id)
            .values_list("extraction_mode", flat=True)
            .first()
        )
    return mode or "ai_vision"


# --- OCR escalation (Slice 32) -------------------------------------------------------


@dataclass(frozen=True)
class OCREscalationOutcome:
    """Result of the optional OCR pass after a low-confidence primary TextExtract.

    ``applied`` is True only when a fallback TextExtract engine ran AND
    returned text whose confidence cleared
    ``EXTRACTION_OCR_THRESHOLD``. ``replacement_result`` is the new
    primary text/confidence to use for the rest of the pipeline.

    All "no, we couldn't" branches return ``applied=False`` with a
    populated ``reason`` for the audit log; the caller falls through to
    the vision escalation path unchanged.
    """

    attempted: bool
    applied: bool
    engine_name: str
    replacement_result: TextExtractResult | None
    reason: str = ""


def _ocr_threshold() -> float:
    return float(getattr(settings, "EXTRACTION_OCR_THRESHOLD", DEFAULT_OCR_ESCALATION_THRESHOLD))


def _maybe_escalate_to_ocr(
    *,
    job: IngestionJob,
    primary_engine: Engine,
    primary_confidence: float,
    body: bytes,
) -> OCREscalationOutcome:
    """Run a fallback TextExtract pass when the primary returned sparse text.

    The router has the OCR rule pre-wired at a lower priority for the same
    MIME (Slice 31's seed migration). We use ``pick_fallback_engine`` to
    skip the engine that already ran (``primary_engine``) and pick the
    next-priority match. If no fallback rule exists, we just return
    ``applied=False`` and let the existing vision escalation handle it.

    Failure modes are graceful — every "no, we can't" branch records the
    reason on the audit log and returns ``applied=False`` so the caller
    falls through.
    """
    threshold = _ocr_threshold()
    not_applied = OCREscalationOutcome(
        attempted=False,
        applied=False,
        engine_name="",
        replacement_result=None,
    )
    if primary_confidence >= threshold:
        return not_applied

    try:
        decision = pick_fallback_engine(
            capability=Engine.Capability.TEXT_EXTRACT,
            mime_type=job.file_mime_type,
            exclude_engine_id=str(primary_engine.id),
        )
    except NoRouteFound as exc:
        # No fallback rule wired — silently skip; vision escalation runs.
        # Don't audit because this is the steady-state for documents
        # without an OCR fallback (and emitting an event on every clean
        # PDF would be noise).
        logger.debug("ocr escalation skipped — no fallback rule: %s", exc)
        return not_applied

    record_event(
        action_type="ingestion.job.ocr_escalation_started",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="extraction.pipeline",
        organization_id=str(job.organization_id),
        affected_entity_type="IngestionJob",
        affected_entity_id=str(job.id),
        payload={
            "primary_engine": primary_engine.name,
            "primary_confidence": str(primary_confidence),
            "fallback_engine": decision.engine.name,
            "threshold": str(threshold),
        },
    )

    try:
        adapter = get_adapter(decision.engine.name)
    except KeyError as exc:
        return _record_ocr_skip(job, reason=f"ocr adapter missing: {exc}")

    if not isinstance(adapter, TextExtractEngine):
        return _record_ocr_skip(
            job,
            reason=(
                f"adapter {decision.engine.name!r} is registered for "
                f"{decision.engine.capability} but isn't a TextExtractEngine"
            ),
        )

    started_at = timezone.now()
    started_perf = time.perf_counter()
    try:
        ocr_result = adapter.extract_text(body=body, mime_type=job.file_mime_type)
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
        return _record_ocr_skip(job, reason=f"ocr unavailable: {exc}")
    except Exception as exc:  # graceful — escalation never breaks the pipeline
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
        return _record_ocr_skip(job, reason=f"ocr failed: {type(exc).__name__}: {exc}")

    _record_call(
        engine=decision.engine,
        job=job,
        started_at=started_at,
        duration_ms=int((time.perf_counter() - started_perf) * 1000),
        outcome=EngineCall.Outcome.SUCCESS,
        error_class="",
        cost_micros=ocr_result.cost_micros,
        confidence=ocr_result.confidence,
        diagnostics=ocr_result.diagnostics,
    )

    # Even when the OCR call "succeeded", if its confidence is below the
    # threshold we treat it as "OCR also couldn't read it" and fall through
    # to vision. The audit event records that we tried.
    if ocr_result.confidence < threshold:
        return _record_ocr_skip(
            job,
            reason=(
                f"ocr confidence {ocr_result.confidence:.2f} below threshold "
                f"{threshold:.2f}; falling through to vision"
            ),
        )

    record_event(
        action_type="ingestion.job.ocr_escalation_applied",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="extraction.pipeline",
        organization_id=str(job.organization_id),
        affected_entity_type="IngestionJob",
        affected_entity_id=str(job.id),
        payload={
            "engine": decision.engine.name,
            "confidence": str(ocr_result.confidence),
            "text_length": len(ocr_result.text),
        },
    )

    return OCREscalationOutcome(
        attempted=True,
        applied=True,
        engine_name=decision.engine.name,
        replacement_result=ocr_result,
    )


def _record_ocr_skip(job: IngestionJob, *, reason: str) -> OCREscalationOutcome:
    """Audit a non-fatal OCR escalation miss; caller falls back to vision."""
    record_event(
        action_type="ingestion.job.ocr_escalation_skipped",
        actor_type=AuditEvent.ActorType.SERVICE,
        actor_id="extraction.pipeline",
        organization_id=str(job.organization_id),
        affected_entity_type="IngestionJob",
        affected_entity_id=str(job.id),
        payload={"reason": reason[:255]},
    )
    return OCREscalationOutcome(
        attempted=True,
        applied=False,
        engine_name="",
        replacement_result=None,
        reason=reason,
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
        return _record_escalation_failure(job, reason=f"vision failed: {type(exc).__name__}: {exc}")

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


# --- Slice 106: re-extract with a chosen engine ---------------------------------


class ReExtractError(Exception):
    """Raised when a manually-triggered re-extraction can't proceed."""


# Statuses where re-extraction is safe. We exclude in-flight states (the
# pipeline is already running) and BUNDLE (parents never extract). We
# also exclude SUBMITTING / SIGNING — re-extracting an invoice mid-LHDN
# call would race the submission service. VALIDATED + REJECTED + ERROR
# are all fine: VALIDATED has already shipped to LHDN (re-extracting
# only changes our local copy, not what we filed), REJECTED is what the
# user fixes, ERROR is the typical "the engine got it wrong" entry
# point.
_RE_EXTRACTABLE_STATUSES = frozenset(
    {
        IngestionJob.Status.READY_FOR_REVIEW,
        IngestionJob.Status.AWAITING_APPROVAL,
        IngestionJob.Status.VALIDATED,
        IngestionJob.Status.REJECTED,
        IngestionJob.Status.CANCELLED,
        IngestionJob.Status.ERROR,
    }
)


@dataclass
class ReExtractResult:
    job: IngestionJob
    engine_name: str
    confidence: float
    text_length: int


def re_extract_job(
    *,
    job_id: UUID | str,
    engine_slug: str,
    actor_user_id: UUID | str | None = None,
) -> ReExtractResult:
    """Re-run extraction on an existing job using a caller-chosen engine.

    Reset path: replace the IngestionJob's extracted text + engine +
    confidence, blank the Invoice's structured fields, then re-run
    structuring synchronously so the response shape mirrors a fresh
    upload. We deliberately do NOT preserve user edits — the user
    explicitly asked for "try with a different engine" and expects to
    see what the new engine produced.

    Audit: emits ``ingestion.job.re_extracted`` with the from / to
    engine slugs and the actor so a customer can see who triggered
    the re-run + which engine they picked.
    """
    from django.db import transaction as _txn

    from apps.extraction.capabilities import VisionExtractEngine
    from apps.submission.models import Invoice
    from apps.submission.services import (
        apply_structured_fields,
        create_invoice_from_extraction,
        finalize_invoice_without_structuring,
        structure_invoice,
    )

    # Tenancy: caller has already set the active tenant (the view
    # runs with the user's session context). Look up directly.
    try:
        job = IngestionJob.objects.get(id=job_id)
    except IngestionJob.DoesNotExist as exc:
        raise ReExtractError("Job not found.") from exc

    if job.status not in _RE_EXTRACTABLE_STATUSES:
        raise ReExtractError(
            f"Job is in state {job.status!r}; re-extraction is only "
            "available once the previous run is complete."
        )

    # Engine validation: must exist, be active, and support either
    # text or vision extraction. We accept both because
    # ClaudeVisionAdapter etc. produce structured fields directly,
    # bypassing the text → structure split.
    try:
        engine = Engine.objects.get(name=engine_slug)
    except Engine.DoesNotExist as exc:
        raise ReExtractError(f"Unknown engine {engine_slug!r}.") from exc
    if engine.status != Engine.Status.ACTIVE:
        raise ReExtractError(f"Engine {engine_slug!r} is not active.")
    if engine.capability not in {
        Engine.Capability.TEXT_EXTRACT,
        Engine.Capability.VISION_EXTRACT,
    }:
        raise ReExtractError(
            f"Engine {engine_slug!r} (capability={engine.capability}) "
            "doesn't support extraction."
        )

    try:
        adapter = get_adapter(engine_slug)
    except KeyError as exc:
        raise ReExtractError(f"Engine {engine_slug!r} has no registered adapter.") from exc

    body = _read_object(job)
    previous_engine = job.extraction_engine

    started_at = timezone.now()
    started_perf = time.perf_counter()

    if isinstance(adapter, VisionExtractEngine):
        from apps.submission.services import INVOICE_HEADER_FIELDS, LINE_ITEMS_KEY  # noqa: PLC0415

        target_schema = [*INVOICE_HEADER_FIELDS, LINE_ITEMS_KEY]
        try:
            vision_result = adapter.extract_vision(
                body=body, mime_type=job.file_mime_type, target_schema=target_schema
            )
        except EngineUnavailable as exc:
            _record_call(
                engine=engine,
                job=job,
                started_at=started_at,
                duration_ms=int((time.perf_counter() - started_perf) * 1000),
                outcome=EngineCall.Outcome.UNAVAILABLE,
                error_class=type(exc).__name__,
                cost_micros=0,
                confidence=None,
                diagnostics={"detail": str(exc), "trigger": "re_extract"},
            )
            raise ReExtractError(f"{engine_slug} is unavailable: {exc}") from exc
        except Exception as exc:
            _record_call(
                engine=engine,
                job=job,
                started_at=started_at,
                duration_ms=int((time.perf_counter() - started_perf) * 1000),
                outcome=EngineCall.Outcome.FAILURE,
                error_class=type(exc).__name__,
                cost_micros=0,
                confidence=None,
                diagnostics={"detail": str(exc)[:500], "trigger": "re_extract"},
            )
            raise ReExtractError(f"{type(exc).__name__}: {exc}") from exc

        _record_call(
            engine=engine,
            job=job,
            started_at=started_at,
            duration_ms=int((time.perf_counter() - started_perf) * 1000),
            outcome=EngineCall.Outcome.SUCCESS,
            error_class="",
            cost_micros=vision_result.cost_micros,
            confidence=vision_result.overall_confidence,
            diagnostics={"trigger": "re_extract"},
        )
        # Vision adapters produce structured fields directly without
        # text. Leave raw_text empty — the user sees the populated
        # fields panel; the "raw extracted text" section just won't
        # render. We could later round-trip through OCR for the text
        # if a user demands it.
        text = ""
        confidence = vision_result.overall_confidence
        is_vision = True
    elif isinstance(adapter, TextExtractEngine):
        try:
            text_result = adapter.extract_text(body=body, mime_type=job.file_mime_type)
        except EngineUnavailable as exc:
            _record_call(
                engine=engine,
                job=job,
                started_at=started_at,
                duration_ms=int((time.perf_counter() - started_perf) * 1000),
                outcome=EngineCall.Outcome.UNAVAILABLE,
                error_class=type(exc).__name__,
                cost_micros=0,
                confidence=None,
                diagnostics={"detail": str(exc), "trigger": "re_extract"},
            )
            raise ReExtractError(f"{engine_slug} is unavailable: {exc}") from exc
        except Exception as exc:
            _record_call(
                engine=engine,
                job=job,
                started_at=started_at,
                duration_ms=int((time.perf_counter() - started_perf) * 1000),
                outcome=EngineCall.Outcome.FAILURE,
                error_class=type(exc).__name__,
                cost_micros=0,
                confidence=None,
                diagnostics={"detail": str(exc)[:500], "trigger": "re_extract"},
            )
            raise ReExtractError(f"{type(exc).__name__}: {exc}") from exc

        _record_call(
            engine=engine,
            job=job,
            started_at=started_at,
            duration_ms=int((time.perf_counter() - started_perf) * 1000),
            outcome=EngineCall.Outcome.SUCCESS,
            error_class="",
            cost_micros=text_result.cost_micros,
            confidence=text_result.confidence,
            diagnostics={"trigger": "re_extract"},
        )
        text = text_result.text or ""
        confidence = text_result.confidence
        is_vision = False
    else:
        raise ReExtractError(
            f"Engine {engine_slug!r} adapter type isn't text or vision."
        )

    # Persist the new extraction + reset the invoice in one transaction
    # so a partial failure can't leave the job claiming the new engine
    # while the invoice still shows the old structured fields.
    with _txn.atomic():
        job.extracted_text = text
        job.extraction_engine = engine_slug
        job.extraction_confidence = confidence
        job.status = IngestionJob.Status.READY_FOR_REVIEW
        job.completed_at = timezone.now()
        job.error_message = ""
        job.save(
            update_fields=[
                "extracted_text",
                "extraction_engine",
                "extraction_confidence",
                "status",
                "completed_at",
                "error_message",
                "updated_at",
            ]
        )

        # Replace the invoice. Cascade drops line items + corrections;
        # the new structuring run produces fresh ones from the new text.
        # NOTE: this overwrites any manual edits the user made — the
        # UI surfaces a confirm dialog before triggering re-extract so
        # the user knows.
        Invoice.objects.filter(ingestion_job_id=job.id).delete()
        invoice = create_invoice_from_extraction(
            organization_id=job.organization_id,
            ingestion_job_id=job.id,
            extracted_text=text,
        )

    record_event(
        action_type="ingestion.job.re_extracted",
        actor_type=AuditEvent.ActorType.USER if actor_user_id else AuditEvent.ActorType.SERVICE,
        actor_id=str(actor_user_id) if actor_user_id else "extraction.re_extract",
        organization_id=str(job.organization_id),
        affected_entity_type="IngestionJob",
        affected_entity_id=str(job.id),
        payload={
            "from_engine": previous_engine or "",
            "to_engine": engine_slug,
            "confidence": str(confidence),
            "text_length": len(text),
        },
    )

    if is_vision:
        # Vision adapters return structured fields alongside text;
        # write them straight to the invoice.
        apply_structured_fields(
            invoice=invoice,
            engine_name=engine_slug,
            fields=vision_result.fields,
            per_field_confidence=vision_result.per_field_confidence,
            overall_confidence=vision_result.overall_confidence,
        )
    elif text.strip():
        # Run structuring synchronously so the API response carries the
        # final review-ready state. The customer hit a button and is
        # waiting on the result; async would need extra polling rounds.
        try:
            structure_invoice(invoice.id)
        except Exception as exc:
            logger.warning(
                "re_extract: structuring failed for invoice %s: %s",
                invoice.id,
                exc,
            )
            finalize_invoice_without_structuring(
                invoice=invoice,
                reason=f"structuring failed after re-extract: {exc}",
            )
    else:
        finalize_invoice_without_structuring(
            invoice=invoice,
            reason="re-extract produced empty text",
        )

    job.refresh_from_db()
    return ReExtractResult(
        job=job,
        engine_name=engine_slug,
        confidence=confidence,
        text_length=len(text),
    )


def list_extraction_engines() -> list[dict]:
    """Return active text + vision extraction engines for the re-extract UI.

    Filters to engines that have a registered adapter (i.e., the slug
    is wired in code, not only in the DB). The frontend uses this to
    populate the "Re-extract with…" dropdown.
    """
    from apps.extraction.registry import _ADAPTER_FACTORIES  # noqa: PLC0415

    engines = Engine.objects.filter(
        status=Engine.Status.ACTIVE,
        capability__in=[
            Engine.Capability.TEXT_EXTRACT,
            Engine.Capability.VISION_EXTRACT,
        ],
    ).order_by("name")
    out: list[dict] = []
    for engine in engines:
        if engine.name not in _ADAPTER_FACTORIES:
            continue
        out.append(
            {
                "slug": engine.name,
                # Engine model has no display label — derive a
                # readable one from the slug for the UI.
                "label": _humanise_engine_name(engine.name),
                "capability": engine.capability,
                "vendor": engine.vendor,
            }
        )
    return out


def _humanise_engine_name(slug: str) -> str:
    """Turn ``anthropic-claude-sonnet-vision`` into ``Claude Sonnet (vision)``.

    Best-effort cosmetic mapping; falls through to the slug for
    unknown engines.
    """
    overrides = {
        "pdfplumber": "pdfplumber (native PDF)",
        "anthropic-claude-sonnet-vision": "Claude Sonnet (vision)",
        "anthropic-claude-sonnet-structure": "Claude Sonnet (structure)",
        "ollama-structure": "Ollama (local structure)",
        "easyocr": "EasyOCR",
        "rapidocr": "RapidOCR",
    }
    return overrides.get(slug, slug)


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


# --- Engine activity surface (customer-facing telemetry) -----------------------


def engine_summary_for_organization(*, organization_id: UUID | str) -> list[dict]:
    """Per-engine roll-up of the active org's EngineCall rows.

    Drives the "Engine activity" dashboard: shows the user which AI
    engines processed their invoices, how often, how reliably, and at
    what cost. Tenant-scoped — engine telemetry is platform-wide in
    storage, but this view is the customer's own slice.

    Returned rows: {engine_name, vendor, capability, total_calls,
    success_count, failure_count, unavailable_count, success_rate,
    avg_duration_ms, total_cost_micros}. Sorted by total_calls desc
    so the engines doing the most work for the customer come first.
    """
    from django.db.models import Avg, Count, Q, Sum

    rollups = (
        EngineCall.objects.filter(organization_id=organization_id)
        .values("engine_id", "engine__name", "engine__vendor", "engine__capability")
        .annotate(
            total_calls=Count("id"),
            success_count=Count("id", filter=Q(outcome=EngineCall.Outcome.SUCCESS)),
            failure_count=Count("id", filter=Q(outcome=EngineCall.Outcome.FAILURE)),
            timeout_count=Count("id", filter=Q(outcome=EngineCall.Outcome.TIMEOUT)),
            unavailable_count=Count("id", filter=Q(outcome=EngineCall.Outcome.UNAVAILABLE)),
            avg_duration_ms=Avg("duration_ms"),
            total_cost_micros=Sum("cost_micros"),
        )
        .order_by("-total_calls")
    )

    out: list[dict] = []
    for row in rollups:
        total = row["total_calls"]
        success = row["success_count"]
        out.append(
            {
                "engine_name": row["engine__name"],
                "vendor": row["engine__vendor"],
                "capability": row["engine__capability"],
                "total_calls": total,
                "success_count": success,
                "failure_count": row["failure_count"],
                "timeout_count": row["timeout_count"],
                "unavailable_count": row["unavailable_count"],
                # Float in [0,1]; UI renders as percent. Avoids storing the
                # ratio, which would go stale; computed on read.
                "success_rate": (success / total) if total else 0.0,
                "avg_duration_ms": int(row["avg_duration_ms"] or 0),
                "total_cost_micros": int(row["total_cost_micros"] or 0),
            }
        )
    return out


def list_engine_calls_for_organization(
    *,
    organization_id: UUID | str,
    limit: int = 50,
    before_started_at: datetime | None = None,
) -> list[EngineCall]:
    """Recent EngineCall rows for the active org.

    Cursor pagination on ``started_at`` mirrors the audit log surface
    pattern. Each call carries enough metadata for the operations view:
    engine, request id (the IngestionJob), outcome, duration, cost,
    confidence, and the diagnostic dict the adapter wrote.
    """
    qs = EngineCall.objects.filter(organization_id=organization_id).select_related("engine")
    if before_started_at is not None:
        qs = qs.filter(started_at__lt=before_started_at)
    return list(qs.order_by("-started_at")[:limit])
