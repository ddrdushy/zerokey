"""EasyOCR adapter — TextExtract for images + scanned PDFs.

Plugs the gap that was hiding behind the routing table since Slice 1:
the ingestion service accepts ``image/jpeg / image/png / image/webp``
uploads, but the only seeded TextExtract route was for
``application/pdf`` (pdfplumber). An image upload would hit
``NoRouteFound`` and fail. This adapter is the launch primary for
images, and a future-ready fallback for scanned PDFs (when the
pdfplumber escalation slice lands).

Why EasyOCR specifically: free, in-process, multilingual, accurate
on real-world receipts. Tesseract is leaner but accuracy on
photographed/scanned Malaysian invoices (mixed-language, low
contrast, varied fonts) is noticeably worse. The trade-off is a
heavier install — torch CPU + opencv-python-headless + Pillow add
~250MB compressed image weight and EasyOCR downloads its English
model on first use (~64MB cached under ``easyocr/``).

Reader caching
--------------
``easyocr.Reader(...)`` loads the model into memory at construction
time (multi-second cost). We cache it as a module-level singleton
so the adapter is cheap to instantiate per request.

PDF support
-----------
Each PDF page is rasterised to a 200-DPI bitmap via pypdfium2,
then OCR'd. 200 DPI is the sweet spot — 100 DPI loses text on
small fonts, 300 DPI is 2x slower with marginal accuracy gain.
For text-native PDFs, pdfplumber should win at routing priority
100; this adapter is the fallback when pdfplumber returns a
low-confidence (likely-scanned) result. For now we register a
priority-200 PDF route so the wiring is in place for a future
pdfplumber-failure escalation slice.

Confidence
----------
EasyOCR returns per-detection confidence in [0, 1]. We average
non-trivial detections (≥ 1 character of text) to produce the
overall confidence. ``0.95 vs 0.10`` floor logic from pdfplumber
doesn't apply here — EasyOCR's confidence is calibrated by the
model itself.
"""

from __future__ import annotations

import io
import logging
import threading

from apps.extraction.capabilities import (
    EngineUnavailable,
    TextExtractEngine,
    TextExtractResult,
)

logger = logging.getLogger(__name__)

ADAPTER_NAME = "easyocr"

_IMAGE_MIMES = ("image/jpeg", "image/png", "image/webp")
_PDF_MIME = "application/pdf"

# DPI to rasterise PDF pages at before OCR. 200 DPI is the empirical sweet
# spot between accuracy (small fonts stay legible) and speed.
_PDF_RENDER_DPI = 200

# Limit pages to OCR per PDF. A 100-page document would otherwise blow the
# request budget; 30 matches MAX_LINE_ITEMS in submission as a sanity cap.
_MAX_PDF_PAGES = 30

# EasyOCR languages. English is the launch primary for Malaysian invoices —
# Bahasa Malaysia uses Latin script so the English model handles it well;
# adding the malay language pack is straightforward when needed.
_LANGUAGES = ["en"]

# Module-level Reader cache. ``Reader.__init__`` loads the language model
# (multi-second + 64MB) — keeping a singleton means the second call within
# a worker process is instant.
_reader_lock = threading.Lock()
_reader_cache: object | None = None


def _get_reader() -> object:
    global _reader_cache
    if _reader_cache is not None:
        return _reader_cache
    with _reader_lock:
        if _reader_cache is not None:
            return _reader_cache
        try:
            import easyocr  # type: ignore[import-untyped]
        except ImportError as exc:
            raise EngineUnavailable("easyocr is not installed") from exc
        # gpu=False: keep the worker container CPU-only. EasyOCR auto-detects
        # CUDA but a missing GPU triggers a confusing fallback warning every
        # call; explicit is better.
        _reader_cache = easyocr.Reader(_LANGUAGES, gpu=False, verbose=False)
        return _reader_cache


def _rasterize_pdf_pages(body: bytes, max_pages: int = _MAX_PDF_PAGES) -> list[bytes]:
    """Render up to ``max_pages`` PDF pages to PNG bytes via pypdfium2.

    pypdfium2 is a single Python wheel — no poppler-utils system dep
    needed. The ``200 / 72`` scale matches DPI-to-PDF-points convention
    (PDFs are 72 DPI native).
    """
    try:
        import pypdfium2 as pdfium  # type: ignore[import-untyped]
    except ImportError as exc:
        raise EngineUnavailable("pypdfium2 is not installed") from exc

    images: list[bytes] = []
    pdf = pdfium.PdfDocument(body)
    try:
        for index, page in enumerate(pdf):
            if index >= max_pages:
                break
            try:
                bitmap = page.render(scale=_PDF_RENDER_DPI / 72)
                pil_image = bitmap.to_pil()
                buf = io.BytesIO()
                pil_image.save(buf, format="PNG")
                images.append(buf.getvalue())
            finally:
                page.close()
    finally:
        pdf.close()
    return images


def _ocr_image(image_bytes: bytes) -> tuple[str, float]:
    """Run EasyOCR on a single image. Returns (joined_text, mean_confidence)."""
    reader = _get_reader()
    # detail=1: returns [(bbox, text, confidence), ...]. We discard the bbox
    # (no use yet) but keep the per-detection confidence to compute an
    # honest average.
    detections = reader.readtext(image_bytes, detail=1, paragraph=False)  # type: ignore[attr-defined]

    text_parts: list[str] = []
    confidences: list[float] = []
    for detection in detections:
        # EasyOCR returns 3-tuples; defensive unpack guards future changes.
        if len(detection) < 3:
            continue
        _bbox, text, confidence = detection[0], detection[1], detection[2]
        if not text or not isinstance(text, str):
            continue
        text_parts.append(text)
        try:
            confidences.append(float(confidence))
        except (TypeError, ValueError):
            continue

    joined = "\n".join(text_parts).strip()
    mean_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    return joined, mean_confidence


class EasyOCRAdapter(TextExtractEngine):
    """OCR adapter for images and scanned PDFs."""

    name = ADAPTER_NAME

    def extract_text(self, *, body: bytes, mime_type: str) -> TextExtractResult:
        if mime_type in _IMAGE_MIMES:
            text, confidence = _ocr_image(body)
            return TextExtractResult(
                text=text,
                confidence=confidence,
                page_count=1,
                cost_micros=0,
                diagnostics={
                    "mode": "image",
                    "characters_extracted": len(text),
                    "languages": _LANGUAGES,
                },
            )

        if mime_type == _PDF_MIME:
            try:
                page_images = _rasterize_pdf_pages(body)
            except EngineUnavailable:
                raise
            except Exception as exc:
                logger.warning("pypdfium2 failed", extra={"error": str(exc)})
                raise EngineUnavailable(
                    f"easyocr could not rasterise PDF pages: {exc}"
                ) from exc

            page_texts: list[str] = []
            page_confidences: list[float] = []
            for image_bytes in page_images:
                page_text, page_confidence = _ocr_image(image_bytes)
                page_texts.append(page_text)
                if page_confidence > 0:
                    page_confidences.append(page_confidence)

            joined = "\n\n".join(t for t in page_texts if t).strip()
            confidence = (
                sum(page_confidences) / len(page_confidences)
                if page_confidences
                else 0.0
            )
            return TextExtractResult(
                text=joined,
                confidence=confidence,
                page_count=len(page_images),
                cost_micros=0,
                diagnostics={
                    "mode": "pdf",
                    "characters_extracted": len(joined),
                    "pages_ocrd": len(page_images),
                    "languages": _LANGUAGES,
                    "render_dpi": _PDF_RENDER_DPI,
                },
            )

        raise EngineUnavailable(
            f"{ADAPTER_NAME} only handles {(*_IMAGE_MIMES, _PDF_MIME)}, got {mime_type}"
        )
