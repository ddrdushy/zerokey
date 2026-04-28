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
    TextExtractEngine,
    TextExtractResult,
)
from apps.extraction.models import Engine, EngineCall, EngineRoutingRule
from apps.extraction.services import run_extraction
from apps.identity.models import Organization, OrganizationMembership, Role, User
from apps.ingestion.models import IngestionJob


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
