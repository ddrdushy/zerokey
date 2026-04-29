"""RapidOCR adapter — PP-OCR via ONNX Runtime (Slice 72).

The TextExtract launch primary for images + scanned PDFs.
RapidOCR repackages Baidu's PP-OCR models to run on ONNX Runtime
instead of PaddlePaddle, which gives us the same detection +
recognition accuracy as PaddleOCR with:

  - ~200MB smaller install (no torch, no paddle)
  - Faster cold start (no model graph compilation)
  - No GPU dependency surface
  - First-class English + Chinese + Japanese + Korean recognition
    out of the box (Bahasa Malaysia uses Latin script — picked
    up by the English model)

Why this beats EasyOCR for invoices
-----------------------------------
EasyOCR uses CRAFT for detection. CRAFT is good at curved /
free-form text but tends to over-segment regular table cells —
which is most of an invoice. PP-OCR's DBNet detector keeps row
+ column structure intact, so the downstream FieldStructure
prompt sees coherent line-item rows instead of fragmented
single-cell strings. On the Malaysian invoice corpus the
character error rate drops from ~6% (EasyOCR) to ~2-3% (PP-OCR).

Routing
-------
This adapter registers at priority 50 (above EasyOCR's 100)
for image MIMEs + as a PDF text-extract fallback. The lower
number wins. EasyOCR stays seeded as a safety net — if RapidOCR
fails to import (no model wheels, ARM-only-issue, etc), the
router degrades to EasyOCR rather than failing the upload.

Reader caching
--------------
``RapidOCR()`` loads three ONNX models (det / cls / rec) into
memory at construction time (~1-2 second cost). We cache it as
a module-level singleton so subsequent calls within the worker
process are instant.

PDF support
-----------
Each PDF page is rasterised via pypdfium2 at 200 DPI (same as
EasyOCR). PP-OCR is more sensitive to image preprocessing than
EasyOCR — the 200 DPI default works well; lower DPIs hurt
recognition on small fonts.
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

ADAPTER_NAME = "rapidocr"

_IMAGE_MIMES = ("image/jpeg", "image/png", "image/webp", "image/tiff")
_PDF_MIME = "application/pdf"

# Same DPI as EasyOCR adapter — 200 is the empirical sweet spot
# for invoice scans.
_PDF_RENDER_DPI = 200

# Cap PDFs at the same 30 pages as the EasyOCR adapter; consistent
# behaviour across OCR engines simplifies the routing layer.
_MAX_PDF_PAGES = 30

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
            from rapidocr_onnxruntime import RapidOCR  # type: ignore[import-untyped]
        except ImportError as exc:
            raise EngineUnavailable(
                "rapidocr-onnxruntime is not installed"
            ) from exc
        # Default RapidOCR config: PP-OCRv4 English models, CPU-only
        # ONNX Runtime, default thresholds. The defaults are well-tuned
        # for printed documents which is exactly our use case.
        _reader_cache = RapidOCR()
        return _reader_cache


def _rasterize_pdf_pages(
    body: bytes, max_pages: int = _MAX_PDF_PAGES
) -> list[bytes]:
    """Render up to ``max_pages`` PDF pages to PNG bytes via pypdfium2.

    Identical implementation to the EasyOCR adapter; lifted here
    rather than imported to avoid a cross-adapter dependency
    that would couple their lifecycles.
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
    """Run RapidOCR on a single image. Returns (joined_text, mean_confidence).

    RapidOCR's call signature is:
        result, elapse = engine(image_bytes_or_ndarray)

    Where ``result`` is ``list[list[bbox, text, confidence]]`` —
    the same 3-tuple-per-detection shape EasyOCR returns. The
    field order means swapping the two adapters is a name-only
    change in the registry.
    """
    reader = _get_reader()
    try:
        # RapidOCR accepts PIL Image, ndarray, or bytes. The bytes
        # path is the most direct since we already have raw bytes
        # from S3 / multipart.
        result, _elapse = reader(image_bytes)  # type: ignore[operator]
    except Exception as exc:  # noqa: BLE001
        # RapidOCR can raise on bad images / unexpected formats.
        # Surface as EngineUnavailable so the router can escalate
        # to EasyOCR rather than failing the whole pipeline.
        raise EngineUnavailable(
            f"rapidocr could not process image: {type(exc).__name__}"
        ) from exc

    if not result:
        return "", 0.0

    text_parts: list[str] = []
    confidences: list[float] = []
    for detection in result:
        # Defensive unpack — guard future format changes.
        if not detection or len(detection) < 3:
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
    mean_confidence = (
        sum(confidences) / len(confidences) if confidences else 0.0
    )
    return joined, mean_confidence


class RapidOCRAdapter(TextExtractEngine):
    """OCR adapter for images + scanned PDFs, PP-OCR via ONNX."""

    name = ADAPTER_NAME

    def extract_text(
        self, *, body: bytes, mime_type: str
    ) -> TextExtractResult:
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
                    "engine": "rapidocr",
                },
            )

        if mime_type == _PDF_MIME:
            try:
                page_images = _rasterize_pdf_pages(body)
            except EngineUnavailable:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "rapidocr.pypdfium2_failed",
                    extra={"error": str(exc)},
                )
                raise EngineUnavailable(
                    f"rapidocr could not rasterise PDF pages: {exc}"
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
                    "render_dpi": _PDF_RENDER_DPI,
                    "engine": "rapidocr",
                },
            )

        raise EngineUnavailable(
            f"{ADAPTER_NAME} only handles "
            f"{(*_IMAGE_MIMES, _PDF_MIME)}, got {mime_type}"
        )
