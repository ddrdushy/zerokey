"""Extraction pipeline tests.

The S3 read and the adapter call are both patched — these tests focus on
state-machine transitions, audit emission, and EngineCall recording. The
real pdfplumber adapter is exercised in a separate test against a fixture PDF.
"""

from __future__ import annotations

from io import BytesIO
from unittest.mock import patch
from uuid import uuid4

import pytest

from apps.audit.models import AuditEvent
from apps.extraction.capabilities import (
    EngineUnavailable,
    StructuredExtractResult,
    TextExtractEngine,
    TextExtractResult,
    VisionExtractEngine,
)
from apps.extraction.models import Engine, EngineCall, EngineRoutingRule
from apps.extraction.services import run_extraction
from apps.identity.models import Organization, OrganizationMembership, Role, User
from apps.ingestion.models import IngestionJob
from apps.submission.models import Invoice


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org_and_user(seeded) -> tuple[Organization, User]:
    org = Organization.objects.create(
        legal_name="ACME", tin="C10000000001", contact_email="ops@acme"
    )
    user = User.objects.create_user(email="o@acme.example", password="x")
    OrganizationMembership.objects.create(
        user=user,
        organization=org,
        role=Role.objects.get(name="owner"),
    )
    return org, user


@pytest.fixture
def pdf_engine_and_rule(db) -> Engine:
    engine, _ = Engine.objects.update_or_create(
        name="pdfplumber",
        defaults={"vendor": "pdfplumber", "capability": "text_extract"},
    )
    EngineRoutingRule.objects.update_or_create(
        capability="text_extract",
        priority=100,
        engine=engine,
        defaults={"match_mime_types": "application/pdf", "is_active": True},
    )
    return engine


@pytest.fixture
def easyocr_engine_and_rule(db) -> Engine:
    """Register an EasyOCR engine + priority-200 PDF rule.

    The Slice 32 escalation chain expects this rule to exist as the
    "second-priority" TextExtract for PDFs — the router's
    ``pick_fallback_engine`` skips pdfplumber (priority 100) and finds
    this. If the rule is missing, the OCR escalation function silently
    skips and the existing vision escalation runs.
    """
    engine, _ = Engine.objects.update_or_create(
        name="easyocr",
        defaults={"vendor": "easyocr", "capability": "text_extract"},
    )
    EngineRoutingRule.objects.update_or_create(
        capability="text_extract",
        priority=200,
        engine=engine,
        match_mime_types="application/pdf",
        defaults={"is_active": True},
    )
    return engine


class _FakeOCRAdapter(TextExtractEngine):
    name = "easyocr"

    def __init__(self, result: TextExtractResult | None = None) -> None:
        self._result = result or TextExtractResult(
            text="OCR'd content goes here", confidence=0.85, page_count=1
        )
        self.calls: list[tuple[bytes, str]] = []

    def extract_text(self, *, body: bytes, mime_type: str) -> TextExtractResult:
        self.calls.append((body, mime_type))
        return self._result


@pytest.fixture
def vision_engine_and_rule(db) -> Engine:
    """Register a vision engine + routing rule that matches PDFs.

    Slice A (vision escalation) uses this when a low-confidence text-extract
    triggers a re-route through a VisionExtractEngine on the same bytes.
    """
    engine, _ = Engine.objects.update_or_create(
        name="anthropic-claude-sonnet-vision",
        defaults={"vendor": "anthropic", "capability": "vision_extract"},
    )
    EngineRoutingRule.objects.update_or_create(
        capability="vision_extract",
        priority=100,
        engine=engine,
        defaults={"match_mime_types": "application/pdf,image/png", "is_active": True},
    )
    return engine


def _make_job(org: Organization) -> IngestionJob:
    return IngestionJob.objects.create(
        organization=org,
        source_channel=IngestionJob.SourceChannel.WEB_UPLOAD,
        original_filename="invoice.pdf",
        file_size=10,
        file_mime_type="application/pdf",
        s3_object_key=f"tenants/{org.id}/ingestion/{uuid4()}/invoice.pdf",
        status=IngestionJob.Status.RECEIVED,
    )


class _FakeAdapter(TextExtractEngine):
    name = "pdfplumber"

    def __init__(self, result: TextExtractResult | None = None) -> None:
        self._result = result or TextExtractResult(text="Hello", confidence=0.9, page_count=1)

    def extract_text(self, *, body: bytes, mime_type: str) -> TextExtractResult:
        return self._result


class _FakeVisionAdapter(VisionExtractEngine):
    name = "anthropic-claude-sonnet-vision"

    def __init__(
        self,
        result: StructuredExtractResult | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._result = result or StructuredExtractResult(
            fields={
                "invoice_number": "INV-001",
                "supplier_legal_name": "Vision Supplies",
                "grand_total": "1234.56",
            },
            per_field_confidence={
                "invoice_number": 0.92,
                "supplier_legal_name": 0.88,
                "grand_total": 0.90,
            },
            overall_confidence=0.90,
            cost_micros=8_000,
            diagnostics={"model": "fake"},
        )
        self._raises = raises
        self.calls: list[tuple[bytes, str]] = []

    def extract_vision(
        self, *, body: bytes, mime_type: str, target_schema: list[str]
    ) -> StructuredExtractResult:
        self.calls.append((body, mime_type))
        if self._raises is not None:
            raise self._raises
        return self._result


def _adapter_dispatcher(text_adapter, vision_adapter, ocr_adapter=None):
    """Return a stand-in for ``get_adapter`` that routes by adapter name."""

    def _resolve(name: str):
        if text_adapter is not None and name == text_adapter.name:
            return text_adapter
        if vision_adapter is not None and name == vision_adapter.name:
            return vision_adapter
        if ocr_adapter is not None and name == ocr_adapter.name:
            return ocr_adapter
        raise KeyError(name)

    return _resolve


@pytest.mark.django_db
class TestPipeline:
    def test_happy_path_completes_and_emits_audit_chain(
        self,
        org_and_user,
        pdf_engine_and_rule,
    ) -> None:
        org, _ = org_and_user
        job = _make_job(org)

        with (
            patch("apps.extraction.services._read_object", return_value=b"%PDF fake"),
            patch("apps.extraction.services.get_adapter", return_value=_FakeAdapter()),
        ):
            run_extraction(job.id)

        job.refresh_from_db()
        assert job.status == IngestionJob.Status.READY_FOR_REVIEW
        assert job.extracted_text == "Hello"
        assert job.extraction_engine == "pdfplumber"
        assert job.extraction_confidence == 0.9

        # Audit chain: two state_changed events plus the extracted event.
        actions = list(
            AuditEvent.objects.order_by("sequence").values_list("action_type", flat=True)
        )
        assert "ingestion.job.state_changed" in actions
        assert "ingestion.job.extracted" in actions

        # Engine call recorded with success.
        calls = list(EngineCall.objects.all())
        assert len(calls) == 1
        assert calls[0].outcome == EngineCall.Outcome.SUCCESS

    def test_engine_unavailable_marks_job_errored(self, org_and_user, pdf_engine_and_rule) -> None:
        org, _ = org_and_user
        job = _make_job(org)

        class _BrokenAdapter(TextExtractEngine):
            name = "pdfplumber"

            def extract_text(self, *, body: bytes, mime_type: str):
                raise EngineUnavailable("api key missing")

        with (
            patch("apps.extraction.services._read_object", return_value=b"%PDF fake"),
            patch("apps.extraction.services.get_adapter", return_value=_BrokenAdapter()),
            pytest.raises(EngineUnavailable),
        ):
            run_extraction(job.id)

        job.refresh_from_db()
        assert job.status == IngestionJob.Status.ERROR
        assert "api key missing" in job.error_message
        assert EngineCall.objects.filter(outcome=EngineCall.Outcome.UNAVAILABLE).count() == 1
        assert AuditEvent.objects.filter(action_type="ingestion.job.errored").count() == 1

    def test_rerun_on_completed_job_is_noop(self, org_and_user, pdf_engine_and_rule) -> None:
        org, _ = org_and_user
        job = _make_job(org)
        job.status = IngestionJob.Status.READY_FOR_REVIEW
        job.save(update_fields=["status"])

        # Should not call get_adapter or transition.
        with (
            patch("apps.extraction.services._read_object") as read_mock,
            patch("apps.extraction.services.get_adapter") as adapter_mock,
        ):
            run_extraction(job.id)
            assert not read_mock.called
            assert not adapter_mock.called


class TestPdfplumberAdapterUnit:
    def test_native_pdf_text_extracts_with_high_confidence(self) -> None:
        from apps.extraction.adapters.pdfplumber_adapter import PdfplumberAdapter

        # Build a real text PDF in-memory with a few sentences (no fixture file).
        try:
            from reportlab.pdfgen import canvas  # type: ignore[import-not-found]
        except ImportError:
            pytest.skip("reportlab not installed; skipping native-PDF roundtrip test")
            return

        buf = BytesIO()
        c = canvas.Canvas(buf)
        c.drawString(100, 750, "Hello from pdfplumber test")
        c.drawString(100, 730, "Second line of text for length check")
        c.showPage()
        c.save()

        result = PdfplumberAdapter().extract_text(body=buf.getvalue(), mime_type="application/pdf")
        assert result.confidence > 0.5
        assert "Hello" in result.text

    def test_unsupported_mime_raises_unavailable(self) -> None:
        from apps.extraction.adapters.pdfplumber_adapter import PdfplumberAdapter

        with pytest.raises(EngineUnavailable):
            PdfplumberAdapter().extract_text(body=b"x", mime_type="image/png")


@pytest.mark.django_db
class TestVisionEscalation:
    """Low-confidence text extracts re-route through VisionExtract.

    Per ENGINE_REGISTRY.md: native PDFs go to pdfplumber; if pdfplumber's
    confidence is below the escalation threshold (default 0.5), the bytes
    are re-routed through a VisionExtract engine which returns structured
    fields directly. The Invoice is populated from the vision result; the
    FieldStructure path is short-circuited.
    """

    def _low_text_result(self) -> TextExtractResult:
        # pdfplumber synthesizes 0.10 when it can't pull any text out — this
        # mirrors the scanned-PDF case where the bytes are basically images.
        return TextExtractResult(text="", confidence=0.10, page_count=1)

    def test_low_confidence_triggers_vision_and_skips_field_structure(
        self, org_and_user, pdf_engine_and_rule, vision_engine_and_rule
    ) -> None:
        org, _ = org_and_user
        job = _make_job(org)

        text_adapter = _FakeAdapter(self._low_text_result())
        vision_adapter = _FakeVisionAdapter()

        with (
            patch("apps.extraction.services._read_object", return_value=b"%PDF fake"),
            patch(
                "apps.extraction.services.get_adapter",
                side_effect=_adapter_dispatcher(text_adapter, vision_adapter),
            ),
            patch("apps.extraction.tasks.structure_invoice.delay") as structure_task,
        ):
            run_extraction(job.id)

        # Vision was called with the original bytes + mime, not just text.
        assert len(vision_adapter.calls) == 1
        call_body, call_mime = vision_adapter.calls[0]
        assert call_body == b"%PDF fake"
        assert call_mime == "application/pdf"

        # FieldStructure task NOT queued — vision short-circuited it.
        assert not structure_task.called

        # Job records the combined engine path so the audit trail is honest.
        job.refresh_from_db()
        assert job.status == IngestionJob.Status.READY_FOR_REVIEW
        assert job.extraction_engine == "pdfplumber+anthropic-claude-sonnet-vision"
        assert job.extraction_confidence == pytest.approx(0.90)

        # Invoice was populated from vision result, not left empty.
        invoice = Invoice.objects.get(ingestion_job_id=job.id)
        assert invoice.invoice_number == "INV-001"
        assert invoice.supplier_legal_name == "Vision Supplies"
        assert invoice.structuring_engine == "anthropic-claude-sonnet-vision"
        assert invoice.status == Invoice.Status.READY_FOR_REVIEW

        # Two engine calls — the text extract + the vision pass — both success.
        outcomes = list(EngineCall.objects.values_list("outcome", flat=True))
        assert outcomes.count(EngineCall.Outcome.SUCCESS) == 2

        # Audit chain has the escalation start + the final extracted event.
        actions = set(AuditEvent.objects.values_list("action_type", flat=True))
        assert "ingestion.job.vision_escalation_started" in actions
        assert "ingestion.job.extracted" in actions

    def test_high_confidence_does_not_escalate(
        self, org_and_user, pdf_engine_and_rule, vision_engine_and_rule
    ) -> None:
        """Above-threshold confidence keeps the regular text → FieldStructure path."""
        org, _ = org_and_user
        job = _make_job(org)

        text_adapter = _FakeAdapter(
            TextExtractResult(text="Lots of native text", confidence=0.95, page_count=1)
        )
        vision_adapter = _FakeVisionAdapter()

        with (
            patch("apps.extraction.services._read_object", return_value=b"%PDF fake"),
            patch(
                "apps.extraction.services.get_adapter",
                side_effect=_adapter_dispatcher(text_adapter, vision_adapter),
            ),
            patch("apps.extraction.tasks.structure_invoice.delay"),
        ):
            run_extraction(job.id)

        assert len(vision_adapter.calls) == 0

        job.refresh_from_db()
        assert job.extraction_engine == "pdfplumber"
        # No escalation events at all on the audit chain.
        actions = set(AuditEvent.objects.values_list("action_type", flat=True))
        assert "ingestion.job.vision_escalation_started" not in actions
        assert "ingestion.job.vision_escalation_skipped" not in actions

    def test_escalation_records_skip_when_no_vision_route(
        self, org_and_user, pdf_engine_and_rule
    ) -> None:
        """No active vision routing rule → audit a skip and fall back to FieldStructure."""
        org, _ = org_and_user
        job = _make_job(org)

        text_adapter = _FakeAdapter(self._low_text_result())

        with (
            patch("apps.extraction.services._read_object", return_value=b"%PDF fake"),
            patch(
                "apps.extraction.services.get_adapter",
                side_effect=_adapter_dispatcher(text_adapter, None),
            ),
            patch("apps.extraction.tasks.structure_invoice.delay"),
        ):
            # No vision_engine_and_rule fixture → pick_engine raises NoRouteFound
            # → escalation records a skip and the regular path proceeds.
            run_extraction(job.id)

        actions = list(AuditEvent.objects.values_list("action_type", flat=True))
        assert "ingestion.job.vision_escalation_started" in actions
        assert "ingestion.job.vision_escalation_skipped" in actions
        # Job still completes; engine name is the original because vision
        # didn't apply.
        job.refresh_from_db()
        assert job.extraction_engine == "pdfplumber"

    def test_empty_text_no_vision_still_finalizes_and_validates(
        self, org_and_user, pdf_engine_and_rule, vision_engine_and_rule
    ) -> None:
        """Regression: an extraction with no text + no vision must NOT leave
        the Invoice stuck in EXTRACTING with no validation issues.

        Previously the pipeline only queued FieldStructure when text.strip()
        was truthy; the empty-text + vision-unavailable case fell through
        and the Invoice sat in EXTRACTING forever. The review UI then
        falsely reported "looks good to submit" because no rules had run.
        Now the empty-text branch routes directly to
        ``finalize_invoice_without_structuring`` which runs validation and
        surfaces the required-field errors.
        """
        org, _ = org_and_user
        job = _make_job(org)

        text_adapter = _FakeAdapter(
            TextExtractResult(text="", confidence=0.10, page_count=1)
        )
        vision_adapter = _FakeVisionAdapter(raises=EngineUnavailable("no api key"))

        with (
            patch("apps.extraction.services._read_object", return_value=b"%PDF fake"),
            patch(
                "apps.extraction.services.get_adapter",
                side_effect=_adapter_dispatcher(text_adapter, vision_adapter),
            ),
        ):
            run_extraction(job.id)

        invoice = Invoice.objects.get(ingestion_job_id=job.id)
        assert invoice.status == Invoice.Status.READY_FOR_REVIEW
        # Validation actually ran — required-field rules fired on the empty header.
        from apps.validation.models import ValidationIssue

        codes = set(
            ValidationIssue.objects.filter(invoice_id=invoice.id).values_list(
                "code", flat=True
            )
        )
        assert "required.invoice_number" in codes
        assert "required.supplier_legal_name" in codes
        # The audit log captured the structuring-skipped event with a clear reason.
        actions = list(AuditEvent.objects.values_list("action_type", flat=True))
        assert "invoice.structuring_skipped" in actions
        assert "invoice.validated" in actions

    def test_escalation_records_skip_when_vision_unavailable(
        self, org_and_user, pdf_engine_and_rule, vision_engine_and_rule
    ) -> None:
        """Vision adapter raising EngineUnavailable falls back gracefully."""
        org, _ = org_and_user
        job = _make_job(org)

        text_adapter = _FakeAdapter(self._low_text_result())
        vision_adapter = _FakeVisionAdapter(raises=EngineUnavailable("no api key"))

        with (
            patch("apps.extraction.services._read_object", return_value=b"%PDF fake"),
            patch(
                "apps.extraction.services.get_adapter",
                side_effect=_adapter_dispatcher(text_adapter, vision_adapter),
            ),
            patch("apps.extraction.tasks.structure_invoice.delay"),
        ):
            run_extraction(job.id)

        actions = list(AuditEvent.objects.values_list("action_type", flat=True))
        assert "ingestion.job.vision_escalation_skipped" in actions

        # Vision call recorded as UNAVAILABLE (graceful), not FAILURE.
        unavailable = EngineCall.objects.filter(outcome=EngineCall.Outcome.UNAVAILABLE).count()
        assert unavailable == 1

        # Final job state: regular text engine, NOT the escalation combo.
        job.refresh_from_db()
        assert job.status == IngestionJob.Status.READY_FOR_REVIEW
        assert job.extraction_engine == "pdfplumber"
        # Invoice is finalized (READY_FOR_REVIEW) with validation issues —
        # text is empty here (low-confidence baseline) so the pipeline
        # short-circuits to finalize_invoice_without_structuring rather
        # than queueing the FieldStructure task on no text. Validation
        # runs inside the finalize path, so the review UI never falsely
        # reports "looks good to submit" on an empty invoice.
        invoice = Invoice.objects.get(ingestion_job_id=job.id)
        assert invoice.status == Invoice.Status.READY_FOR_REVIEW


class TestClaudeVisionAdapterMimeDispatch:
    """Vision adapter handles both image and PDF inputs.

    The PDF path is needed for the Slice A escalation: when pdfplumber
    confidence is low, the same PDF bytes are re-sent to vision; the adapter
    must know to wrap them in a Claude ``document`` content block, not the
    image block it uses for image/* inputs.
    """

    def test_pdf_yields_document_content_block(self) -> None:
        from apps.extraction.adapters.claude_adapter import _document_block

        block = _document_block(body=b"%PDF-1.4 fake", mime_type="application/pdf")
        assert block["type"] == "document"
        assert block["source"]["media_type"] == "application/pdf"

    def test_image_yields_image_content_block(self) -> None:
        from apps.extraction.adapters.claude_adapter import _document_block

        block = _document_block(body=b"\x89PNG", mime_type="image/png")
        assert block["type"] == "image"
        assert block["source"]["media_type"] == "image/png"

    def test_unsupported_mime_raises_unavailable(self) -> None:
        from apps.extraction.adapters.claude_adapter import _document_block

        with pytest.raises(EngineUnavailable):
            _document_block(body=b"...", mime_type="application/zip")


@pytest.mark.django_db
class TestOCREscalation:
    """Slice 32: pdfplumber low confidence -> EasyOCR -> (else vision).

    The escalation chain has three tiers:
      1. pdfplumber on the PDF — fast, free, works for native PDFs.
      2. If confidence < threshold (sparse text → likely scanned),
         pick_fallback_engine returns the priority-200 EasyOCR rule and
         the OCR adapter runs. If its confidence ≥ threshold, the OCR
         text replaces the primary result; the rest of the pipeline
         (FieldStructure with Ollama) proceeds unchanged.
      3. If OCR also fails / is unavailable / returns low confidence,
         the existing vision escalation runs.
    """

    def _scanned(self) -> TextExtractResult:
        # pdfplumber's "I couldn't pull anything" return value — empty text,
        # 0.10 confidence floor.
        return TextExtractResult(text="", confidence=0.10, page_count=1)

    def test_low_pdf_confidence_triggers_ocr_and_skips_vision(
        self,
        org_and_user,
        pdf_engine_and_rule,
        easyocr_engine_and_rule,
        vision_engine_and_rule,
    ) -> None:
        org, _ = org_and_user
        job = _make_job(org)

        text_adapter = _FakeAdapter(self._scanned())
        ocr_adapter = _FakeOCRAdapter(
            TextExtractResult(
                text="OCR'd full invoice text from the scanned PDF.",
                confidence=0.85,
                page_count=2,
            )
        )
        vision_adapter = _FakeVisionAdapter()

        with (
            patch("apps.extraction.services._read_object", return_value=b"%PDF fake"),
            patch(
                "apps.extraction.services.get_adapter",
                side_effect=_adapter_dispatcher(text_adapter, vision_adapter, ocr_adapter),
            ),
            patch("apps.extraction.tasks.structure_invoice.delay"),
        ):
            run_extraction(job.id)

        # OCR was called with the original bytes + mime.
        assert len(ocr_adapter.calls) == 1
        assert ocr_adapter.calls[0] == (b"%PDF fake", "application/pdf")

        # Vision NOT called — OCR succeeded so the chain stopped there.
        # Asserting through the audit log + job state below proves the
        # post-OCR pipeline took the FieldStructure path (the structuring
        # task is wrapped in transaction.on_commit which doesn't fire in
        # the test's transaction).

        job.refresh_from_db()
        assert job.status == IngestionJob.Status.READY_FOR_REVIEW
        # Combined engine name records the chain step.
        assert job.extraction_engine == "pdfplumber+easyocr"
        # Confidence reflects the OCR pass, not pdfplumber's 0.10.
        assert job.extraction_confidence == pytest.approx(0.85)
        # The OCR text becomes the job's extracted_text.
        assert "OCR'd full invoice text" in job.extracted_text

        # Two engine calls succeeded (pdfplumber + easyocr).
        outcomes = list(EngineCall.objects.values_list("outcome", flat=True))
        assert outcomes.count(EngineCall.Outcome.SUCCESS) == 2

        # Audit chain has the OCR escalation events.
        actions = set(AuditEvent.objects.values_list("action_type", flat=True))
        assert "ingestion.job.ocr_escalation_started" in actions
        assert "ingestion.job.ocr_escalation_applied" in actions
        # Vision escalation was NOT started — chain stopped at OCR.
        assert "ingestion.job.vision_escalation_started" not in actions

    def test_ocr_low_confidence_falls_through_to_vision(
        self,
        org_and_user,
        pdf_engine_and_rule,
        easyocr_engine_and_rule,
        vision_engine_and_rule,
    ) -> None:
        """OCR ran but its own confidence was sub-threshold → vision still runs."""
        org, _ = org_and_user
        job = _make_job(org)

        text_adapter = _FakeAdapter(self._scanned())
        # OCR confidence below threshold — bad scan that even OCR couldn't
        # read confidently.
        ocr_adapter = _FakeOCRAdapter(
            TextExtractResult(text="garbled fragments", confidence=0.20, page_count=1)
        )
        vision_adapter = _FakeVisionAdapter()

        with (
            patch("apps.extraction.services._read_object", return_value=b"%PDF fake"),
            patch(
                "apps.extraction.services.get_adapter",
                side_effect=_adapter_dispatcher(text_adapter, vision_adapter, ocr_adapter),
            ),
            patch("apps.extraction.tasks.structure_invoice.delay"),
        ):
            run_extraction(job.id)

        # Both OCR + vision were tried.
        assert len(ocr_adapter.calls) == 1
        assert len(vision_adapter.calls) == 1

        # Audit log shows OCR was attempted but skipped, then vision applied.
        actions = list(AuditEvent.objects.values_list("action_type", flat=True))
        assert "ingestion.job.ocr_escalation_started" in actions
        assert "ingestion.job.ocr_escalation_skipped" in actions
        assert "ingestion.job.vision_escalation_started" in actions

    def test_high_pdf_confidence_does_not_trigger_ocr(
        self,
        org_and_user,
        pdf_engine_and_rule,
        easyocr_engine_and_rule,
        vision_engine_and_rule,
    ) -> None:
        """Native PDF (high confidence) bypasses OCR entirely."""
        org, _ = org_and_user
        job = _make_job(org)

        text_adapter = _FakeAdapter(
            TextExtractResult(text="Native text content", confidence=0.95, page_count=1)
        )
        ocr_adapter = _FakeOCRAdapter()  # default response — should be untouched
        vision_adapter = _FakeVisionAdapter()

        with (
            patch("apps.extraction.services._read_object", return_value=b"%PDF fake"),
            patch(
                "apps.extraction.services.get_adapter",
                side_effect=_adapter_dispatcher(text_adapter, vision_adapter, ocr_adapter),
            ),
            patch("apps.extraction.tasks.structure_invoice.delay"),
        ):
            run_extraction(job.id)

        # Neither OCR nor vision was called.
        assert ocr_adapter.calls == []
        assert vision_adapter.calls == []

        # No OCR escalation events on the audit chain.
        actions = list(AuditEvent.objects.values_list("action_type", flat=True))
        assert "ingestion.job.ocr_escalation_started" not in actions

    def test_ocr_unavailable_falls_through_to_vision(
        self,
        org_and_user,
        pdf_engine_and_rule,
        easyocr_engine_and_rule,
        vision_engine_and_rule,
    ) -> None:
        """OCR adapter raises EngineUnavailable → audit + fall through."""
        org, _ = org_and_user
        job = _make_job(org)

        text_adapter = _FakeAdapter(self._scanned())

        class _BoomOCR(TextExtractEngine):
            name = "easyocr"

            def __init__(self):
                self.calls: list = []

            def extract_text(self, *, body, mime_type):
                self.calls.append((body, mime_type))
                raise EngineUnavailable("easyocr is not installed")

        ocr_adapter = _BoomOCR()
        vision_adapter = _FakeVisionAdapter()

        with (
            patch("apps.extraction.services._read_object", return_value=b"%PDF fake"),
            patch(
                "apps.extraction.services.get_adapter",
                side_effect=_adapter_dispatcher(text_adapter, vision_adapter, ocr_adapter),
            ),
            patch("apps.extraction.tasks.structure_invoice.delay"),
        ):
            run_extraction(job.id)

        # OCR was attempted, raised, vision then ran.
        assert len(ocr_adapter.calls) == 1
        assert len(vision_adapter.calls) == 1

        actions = list(AuditEvent.objects.values_list("action_type", flat=True))
        assert "ingestion.job.ocr_escalation_skipped" in actions
        # The skip reason carried the EngineUnavailable message — UI can
        # surface it on the inbox detail.
        skip_event = AuditEvent.objects.filter(
            action_type="ingestion.job.ocr_escalation_skipped"
        ).first()
        assert "easyocr is not installed" in skip_event.payload["reason"]
