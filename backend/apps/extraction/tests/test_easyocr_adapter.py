"""Tests for the EasyOCR text-extract adapter (Slice 31).

We mock ``easyocr.Reader`` and ``pypdfium2.PdfDocument`` so the suite
runs without the heavy native dependencies on CI. The adapter logic
under test:

  - Image MIME → single OCR call, joined text + averaged confidence.
  - PDF MIME → page rasterisation + per-page OCR + joined text +
    averaged page confidence.
  - Unsupported MIME → ``EngineUnavailable`` at the call site (rather
    than crashing inside the OCR layer).
  - Reader caching: a second invocation reuses the singleton — the
    factory mock asserts it was constructed at most once across two
    calls.
  - Empty image / blank page → confidence 0, empty text, no crash.
  - Diagnostics carry mode (image/pdf), DPI, page count.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.extraction.capabilities import EngineUnavailable


# Patch the cache directly so each test starts from a clean slate.
@pytest.fixture(autouse=True)
def _reset_reader_cache():
    from apps.extraction.adapters import easyocr_adapter

    easyocr_adapter._reader_cache = None
    yield
    easyocr_adapter._reader_cache = None


class _FakeReader:
    """Stand-in for ``easyocr.Reader``. Records calls for assertions."""

    construction_count = 0

    def __init__(self, languages, gpu=False, verbose=False):
        type(self).construction_count += 1
        self.languages = languages
        self.responses: list[list[tuple]] = []

    def readtext(self, image_bytes, detail=1, paragraph=False):
        # Pop the next queued response; empty queue returns []. Tests that
        # want a "blank page" outcome construct the factory with no responses.
        if self.responses:
            return self.responses.pop(0)
        return []


def _make_reader_factory(*responses):
    """Build a fake easyocr module whose Reader returns fixed responses.

    Constructing the fake_easyocr module installs a Reader callable that
    instantiates ``_FakeReader`` (so the construction counter increments)
    and pre-loads the response queue. Tests can call the factory once
    and expect the next `import easyocr; easyocr.Reader(...)` to bump
    the counter to 1 — re-instantiation across calls would push it to 2.
    """
    _FakeReader.construction_count = 0
    queued = list(responses)

    def _reader_init(*args, **kwargs):
        instance = _FakeReader(*args, **kwargs)
        instance.responses = queued
        return instance

    fake_easyocr = type("fake_easyocr_module", (), {"Reader": _reader_init})
    return fake_easyocr, queued


@pytest.fixture
def adapter():
    from apps.extraction.adapters.easyocr_adapter import EasyOCRAdapter

    return EasyOCRAdapter()


class TestImagePath:
    def test_image_jpeg_runs_ocr_and_returns_text(self, adapter) -> None:
        fake_easyocr, _queued = _make_reader_factory(
            [
                ([[0, 0], [50, 0], [50, 20], [0, 20]], "INVOICE", 0.95),
                ([[0, 30], [80, 30], [80, 50], [0, 50]], "INV-12345", 0.88),
                ([[0, 60], [40, 60], [40, 80], [0, 80]], "MYR 250.00", 0.91),
            ]
        )
        with patch.dict("sys.modules", {"easyocr": fake_easyocr}):
            result = adapter.extract_text(body=b"jpegbytes", mime_type="image/jpeg")

        assert "INVOICE" in result.text
        assert "INV-12345" in result.text
        assert "MYR 250.00" in result.text
        # Confidence is the mean of per-detection scores (0.95 + 0.88 + 0.91) / 3
        assert abs(result.confidence - (0.95 + 0.88 + 0.91) / 3) < 1e-6
        assert result.page_count == 1
        assert result.diagnostics["mode"] == "image"
        assert result.diagnostics["languages"] == ["en"]
        assert result.diagnostics["characters_extracted"] == len(result.text)

    def test_image_png_supported(self, adapter) -> None:
        fake_easyocr, _fake = _make_reader_factory(
            [([[0, 0], [10, 0], [10, 10], [0, 10]], "OK", 0.9)]
        )
        with patch.dict("sys.modules", {"easyocr": fake_easyocr}):
            result = adapter.extract_text(body=b"pngbytes", mime_type="image/png")
        assert "OK" in result.text

    def test_image_webp_supported(self, adapter) -> None:
        fake_easyocr, _fake = _make_reader_factory(
            [([[0, 0], [10, 0], [10, 10], [0, 10]], "OK", 0.9)]
        )
        with patch.dict("sys.modules", {"easyocr": fake_easyocr}):
            result = adapter.extract_text(body=b"webpbytes", mime_type="image/webp")
        assert "OK" in result.text

    def test_blank_image_returns_zero_confidence_no_crash(self, adapter) -> None:
        # An empty list of detections — what EasyOCR returns for a blank page.
        # Adapter must handle gracefully: empty text, 0.0 confidence, no
        # division-by-zero from averaging zero confidences.
        fake_easyocr, _ = _make_reader_factory([])
        with patch.dict("sys.modules", {"easyocr": fake_easyocr}):
            result = adapter.extract_text(body=b"blank", mime_type="image/jpeg")
        assert result.text == ""
        assert result.confidence == 0.0


class TestPDFPath:
    def test_pdf_rasterises_pages_and_ocrs_each(self, adapter) -> None:
        # Mock pypdfium2: PdfDocument returns 2 fake pages, each renders to
        # bytes. The mock easyocr produces different text per page.
        fake_easyocr, _queued = _make_reader_factory(
            [([[0, 0], [10, 0], [10, 10], [0, 10]], "PAGE ONE", 0.9)],
            [([[0, 0], [10, 0], [10, 10], [0, 10]], "PAGE TWO", 0.85)],
        )

        class _FakePage:
            def __init__(self, page_no):
                self.page_no = page_no

            def render(self, scale):
                return _FakeBitmap(self.page_no)

            def close(self):
                pass

        class _FakeBitmap:
            def __init__(self, page_no):
                self.page_no = page_no

            def to_pil(self):
                return _FakePIL(self.page_no)

        class _FakePIL:
            def __init__(self, page_no):
                self.page_no = page_no

            def save(self, buf, **kwargs):
                buf.write(f"page-{self.page_no}-png".encode())

        class _FakePdf:
            def __init__(self, body):
                self.body = body
                self.pages = [_FakePage(1), _FakePage(2)]

            def __iter__(self):
                return iter(self.pages)

            def close(self):
                pass

        fake_pdfium = type(
            "fake_pdfium_module", (), {"PdfDocument": _FakePdf}
        )

        with patch.dict(
            "sys.modules", {"easyocr": fake_easyocr, "pypdfium2": fake_pdfium}
        ):
            result = adapter.extract_text(
                body=b"%PDF-fake", mime_type="application/pdf"
            )

        assert "PAGE ONE" in result.text
        assert "PAGE TWO" in result.text
        assert result.page_count == 2
        # Mean of the two page confidences (0.9 + 0.85) / 2
        assert abs(result.confidence - 0.875) < 1e-6
        assert result.diagnostics["mode"] == "pdf"
        assert result.diagnostics["pages_ocrd"] == 2
        assert result.diagnostics["render_dpi"] == 200

    def test_pdf_rasterise_failure_raises_engine_unavailable(self, adapter) -> None:
        class _BoomPdf:
            def __init__(self, body):
                raise RuntimeError("not actually a PDF")

        fake_pdfium = type("fake_pdfium_module", (), {"PdfDocument": _BoomPdf})
        with patch.dict("sys.modules", {"pypdfium2": fake_pdfium}):
            with pytest.raises(EngineUnavailable, match="rasterise"):
                adapter.extract_text(body=b"junk", mime_type="application/pdf")


class TestUnsupportedMime:
    def test_unsupported_mime_raises(self, adapter) -> None:
        with pytest.raises(EngineUnavailable, match="only handles"):
            adapter.extract_text(body=b"x", mime_type="text/plain")


class TestReaderCaching:
    def test_reader_constructed_once_across_calls(self, adapter) -> None:
        # Two image OCR calls should share the same Reader instance — the
        # whole point of the module-level cache.
        fake_easyocr, _queued = _make_reader_factory(
            [([[0, 0], [10, 0], [10, 10], [0, 10]], "first", 0.9)],
            [([[0, 0], [10, 0], [10, 10], [0, 10]], "second", 0.9)],
        )
        with patch.dict("sys.modules", {"easyocr": fake_easyocr}):
            adapter.extract_text(body=b"a", mime_type="image/jpeg")
            adapter.extract_text(body=b"b", mime_type="image/jpeg")

        assert _FakeReader.construction_count == 1


class TestEasyOCRMissing:
    def test_easyocr_not_installed_raises_engine_unavailable(self, adapter) -> None:
        # Patch sys.modules to make `import easyocr` fail. This simulates a
        # deployment where the optional native dep wasn't installed.
        import sys

        sentinel = sys.modules.pop("easyocr", None)
        with patch.dict("sys.modules", {"easyocr": None}):
            with pytest.raises(EngineUnavailable, match="easyocr is not installed"):
                adapter.extract_text(body=b"x", mime_type="image/jpeg")
        if sentinel is not None:
            sys.modules["easyocr"] = sentinel
