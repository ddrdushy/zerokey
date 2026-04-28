"""pdfplumber adapter — native (text-based) PDFs.

Free, in-process, fast. Works for any PDF whose text is selectable. For
scanned PDFs / images / PDFs of photographs the result will be empty or
garbage; the router escalates those to a vision engine.

Confidence model: pdfplumber doesn't return a confidence value. We synthesize
one from "did we extract any text at all?" — 0.95 if non-trivial text came
out, 0.10 otherwise. The router uses the low value as the trigger to route
the job to vision instead.
"""

from __future__ import annotations

import io
import logging

import pdfplumber

from apps.extraction.capabilities import (
    EngineUnavailable,
    TextExtractEngine,
    TextExtractResult,
)

logger = logging.getLogger(__name__)

ADAPTER_NAME = "pdfplumber"
SUPPORTED_MIME = "application/pdf"
# Below this character count we assume the PDF was scanned, not native.
NATIVE_PDF_TEXT_FLOOR = 40


class PdfplumberAdapter(TextExtractEngine):
    name = ADAPTER_NAME

    def extract_text(self, *, body: bytes, mime_type: str) -> TextExtractResult:
        if mime_type != SUPPORTED_MIME:
            raise EngineUnavailable(f"{ADAPTER_NAME} only handles application/pdf, got {mime_type}")

        try:
            with pdfplumber.open(io.BytesIO(body)) as pdf:
                pages_text = [page.extract_text() or "" for page in pdf.pages]
                page_count = len(pdf.pages)
        except Exception as exc:
            logger.warning("pdfplumber failed", extra={"error": str(exc)})
            raise EngineUnavailable(f"pdfplumber could not parse the PDF: {exc}") from exc

        text = "\n\n".join(pages_text).strip()
        confidence = 0.95 if len(text) >= NATIVE_PDF_TEXT_FLOOR else 0.10

        return TextExtractResult(
            text=text,
            confidence=confidence,
            page_count=page_count,
            cost_micros=0,
            diagnostics={
                "characters_extracted": len(text),
                "is_likely_native": confidence > 0.5,
            },
        )
