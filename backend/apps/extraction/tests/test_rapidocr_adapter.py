"""Tests for the RapidOCR text-extract adapter (Slice 72).

RapidOCR isn't installed on CI — we mock it the same way the
EasyOCR tests mock easyocr. The adapter logic under test:

  - Image MIME → single OCR call, joined text + averaged confidence.
  - PDF MIME → page rasterisation + per-page OCR + joined text +
    averaged page confidence.
  - Unsupported MIME → ``EngineUnavailable``.
  - Reader caching: second call reuses the singleton.
  - RapidOCR raising on bad input → ``EngineUnavailable`` so the
    router can degrade to EasyOCR.
  - Diagnostics carry mode (image/pdf), engine name, DPI.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.extraction.capabilities import EngineUnavailable


@pytest.fixture(autouse=True)
def _reset_reader_cache():
    from apps.extraction.adapters import rapidocr_adapter

    rapidocr_adapter._reader_cache = None
    yield
    rapidocr_adapter._reader_cache = None


class _FakeRapidOCR:
    """Stand-in for ``rapidocr_onnxruntime.RapidOCR``. Returns queued responses."""

    construction_count = 0

    def __init__(self, *args, **kwargs):
        type(self).construction_count += 1
        self.responses: list[list[tuple] | None] = []
        self.raise_next = False

    def __call__(self, image_bytes):
        if self.raise_next:
            raise RuntimeError("simulated rapidocr failure")
        if self.responses:
            return self.responses.pop(0), 0.123
        return [], 0.0


def _make_rapidocr_module(*responses, raise_on_call: bool = False):
    """Build a fake rapidocr_onnxruntime module that returns fixed responses."""
    _FakeRapidOCR.construction_count = 0
    queued = list(responses)

    def _rapid_init(*args, **kwargs):
        instance = _FakeRapidOCR(*args, **kwargs)
        instance.responses = queued
        instance.raise_next = raise_on_call
        return instance

    fake_module = type("fake_rapidocr_module", (), {"RapidOCR": _rapid_init})
    return fake_module


@pytest.fixture
def adapter():
    from apps.extraction.adapters.rapidocr_adapter import RapidOCRAdapter

    return RapidOCRAdapter()


# =============================================================================
# Image path
# =============================================================================


class TestImagePath:
    def test_jpeg_runs_ocr_and_joins(self, adapter) -> None:
        fake = _make_rapidocr_module(
            [
                ([[0, 0], [50, 0]], "INVOICE", 0.95),
                ([[0, 30], [80, 30]], "INV-12345", 0.88),
                ([[0, 60], [40, 60]], "MYR 250.00", 0.91),
            ]
        )
        with patch.dict("sys.modules", {"rapidocr_onnxruntime": fake}):
            result = adapter.extract_text(body=b"jpegbytes", mime_type="image/jpeg")

        assert "INVOICE" in result.text
        assert "INV-12345" in result.text
        assert "MYR 250.00" in result.text
        # Confidence = mean of (0.95, 0.88, 0.91)
        assert abs(result.confidence - (0.95 + 0.88 + 0.91) / 3) < 1e-6
        assert result.diagnostics["mode"] == "image"
        assert result.diagnostics["engine"] == "rapidocr"

    def test_png_path(self, adapter) -> None:
        fake = _make_rapidocr_module([([[0, 0], [10, 10]], "Hello", 0.9)])
        with patch.dict("sys.modules", {"rapidocr_onnxruntime": fake}):
            result = adapter.extract_text(body=b"pngbytes", mime_type="image/png")
        assert result.text == "Hello"

    def test_tiff_path(self, adapter) -> None:
        # TIFF is the differentiator vs the EasyOCR adapter (which doesn't
        # claim TIFF). Ensures the routing migration's mime-type list lines
        # up with the adapter's own allowlist.
        fake = _make_rapidocr_module([([[0, 0], [10, 10]], "TiffText", 0.85)])
        with patch.dict("sys.modules", {"rapidocr_onnxruntime": fake}):
            result = adapter.extract_text(body=b"tiffbytes", mime_type="image/tiff")
        assert result.text == "TiffText"

    def test_blank_image_returns_empty_zero_confidence(self, adapter) -> None:
        fake = _make_rapidocr_module()  # no responses → empty
        with patch.dict("sys.modules", {"rapidocr_onnxruntime": fake}):
            result = adapter.extract_text(body=b"blank", mime_type="image/jpeg")
        assert result.text == ""
        assert result.confidence == 0.0

    def test_rapidocr_call_failure_surfaces_unavailable(self, adapter) -> None:
        fake = _make_rapidocr_module(raise_on_call=True)
        with patch.dict("sys.modules", {"rapidocr_onnxruntime": fake}):
            with pytest.raises(EngineUnavailable):
                adapter.extract_text(body=b"bad", mime_type="image/jpeg")

    def test_unsupported_mime_unavailable(self, adapter) -> None:
        fake = _make_rapidocr_module()
        with patch.dict("sys.modules", {"rapidocr_onnxruntime": fake}):
            with pytest.raises(EngineUnavailable):
                adapter.extract_text(body=b"x", mime_type="application/zip")

    def test_reader_cached_across_calls(self, adapter) -> None:
        fake = _make_rapidocr_module(
            [([[0, 0]], "first", 0.9)],
            [([[0, 0]], "second", 0.9)],
        )
        with patch.dict("sys.modules", {"rapidocr_onnxruntime": fake}):
            adapter.extract_text(body=b"a", mime_type="image/jpeg")
            adapter.extract_text(body=b"b", mime_type="image/jpeg")
        # Second call must reuse the singleton — only one ctor call.
        assert _FakeRapidOCR.construction_count == 1


# =============================================================================
# Import unavailability
# =============================================================================


class TestImportUnavailable:
    def test_missing_rapidocr_raises_engine_unavailable(self, adapter) -> None:
        # Pretend rapidocr_onnxruntime can't be imported.
        with patch.dict("sys.modules", {"rapidocr_onnxruntime": None}):
            with pytest.raises(EngineUnavailable, match="rapidocr"):
                adapter.extract_text(body=b"x", mime_type="image/jpeg")


# =============================================================================
# PDF path
# =============================================================================


class TestPdfPath:
    def test_pdf_rasterises_and_ocrs_each_page(self, adapter) -> None:
        # Two-page PDF — one OCR response per page.
        fake_rapid = _make_rapidocr_module(
            [([[0, 0]], "PageOneText", 0.92)],
            [([[0, 0]], "PageTwoText", 0.87)],
        )

        # Fake pypdfium2 module with a 2-page PDF.
        class _FakeBitmap:
            def to_pil(self):

                # Minimal valid PNG header — adapter only re-saves it.
                class _FakePIL:
                    def save(self, buf, format=None):
                        buf.write(b"PNG-fake")

                return _FakePIL()

        class _FakePage:
            def render(self, scale):
                return _FakeBitmap()

            def close(self):
                pass

        class _FakePdfDoc:
            def __init__(self, body):
                self.body = body
                self._pages = [_FakePage(), _FakePage()]

            def __iter__(self):
                return iter(self._pages)

            def close(self):
                pass

        fake_pdfium = type(
            "fake_pdfium",
            (),
            {"PdfDocument": _FakePdfDoc},
        )

        with patch.dict(
            "sys.modules",
            {
                "rapidocr_onnxruntime": fake_rapid,
                "pypdfium2": fake_pdfium,
            },
        ):
            result = adapter.extract_text(body=b"%PDF-fake", mime_type="application/pdf")
        assert "PageOneText" in result.text
        assert "PageTwoText" in result.text
        assert result.page_count == 2
        assert result.diagnostics["mode"] == "pdf"
        assert result.diagnostics["pages_ocrd"] == 2
        assert result.diagnostics["render_dpi"] == 200
