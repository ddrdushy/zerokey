"""Embedded-invoice QR decoder.

Slice 109 — when an invoice PDF already carries a QR (e.g. a
LHDN-validated e-invoice with the verification QR at the top-right),
read it during extraction and surface the encoded data alongside the
text. The data is then promoted to ``Invoice.lhdn_uuid`` /
``Invoice.lhdn_qr_code_url`` if the QR is an LHDN-validation URL —
the supplier resubmitting a verified e-invoice doesn't need to
re-type the UUID, and the validation rule "must have a valid UUID"
passes immediately.

Why decode on the backend rather than the frontend: extraction runs
once per upload on a worker that already has the original PDF bytes
in memory and a barcode-decoding pipeline is shared infrastructure;
pushing it to the browser would mean every reviewer's machine
re-decodes the same QR every page load. Server-side keeps the cost
on a single beat-of-pipeline, deterministically, and lets us audit
the result.

Render path: ``pypdfium2`` is already a dependency for OCR
rasterisation. We render at 2x scale — enough resolution for a
typical 1-cm-square QR to decode reliably without bloating memory.

Decoder: pyzbar (binds libzbar0). Tried OpenCV's QRCodeDetector but
opencv-python's GUI build wouldn't import in our slim runtime, and
opencv-python-headless conflicts with the easyocr-pulled
opencv-python. libzbar0 is a 70 KB system lib with no GUI deps.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Render scale for QR detection. 2x of a 72-dpi PDF page is ~144 dpi —
# QRs at typical invoice density (~25 modules square in a 2.5 cm box)
# decode reliably at this resolution while keeping pages under ~8 MP.
_RENDER_SCALE = 2

# LHDN MyInvois host patterns. Both prod and sandbox tenants land here.
# Lowercased for case-insensitive compare.
_LHDN_HOSTS = (
    "myinvois.hasil.gov.my",
    "preprod.myinvois.hasil.gov.my",
    "preprod-api.myinvois.hasil.gov.my",
)

# Stand-alone UUID in text (24-char base32, LHDN convention) — used
# when a QR's plain payload isn't a URL but a raw UUID.
_LHDN_UUID_RE = re.compile(r"^[A-Z0-9]{24,32}$")


@dataclass(frozen=True)
class DecodedQR:
    """Single QR read out of a PDF page."""

    page_index: int
    raw_data: str
    # Heuristic-typed payload:
    #   - "lhdn_validation_url": URL pointing to a MyInvois validation page
    #   - "url": some other URL
    #   - "uuid": looks like a raw LHDN UUID
    #   - "other": anything else (raw_data still carries the value)
    kind: str
    # When kind="lhdn_validation_url", the longId / UUID segment lifted
    # out of the URL path so callers don't have to re-parse.
    lhdn_uuid: str = ""
    lhdn_long_id: str = ""


def decode_qrs_from_pdf(pdf_bytes: bytes) -> list[DecodedQR]:
    """Decode every QR in every page of the PDF. Returns [] if none found.

    Best-effort — any exception from the decoder is logged and turned
    into an empty result so a missing system library or a corrupt PDF
    can never break the extraction pipeline. Callers treat the empty
    list and a list-of-zero-LHDN-QRs identically.
    """
    try:
        import pypdfium2 as pdfium  # noqa: PLC0415
        from pyzbar.pyzbar import ZBarSymbol, decode  # noqa: PLC0415
    except ImportError as exc:
        logger.info("decode_qrs_from_pdf: skipped (%s)", exc)
        return []

    results: list[DecodedQR] = []
    try:
        doc = pdfium.PdfDocument(pdf_bytes)
    except Exception as exc:
        logger.info("decode_qrs_from_pdf: failed to open PDF: %s", exc)
        return []

    for index in range(len(doc)):
        try:
            page = doc[index]
            bitmap = page.render(scale=_RENDER_SCALE)
            pil_img = bitmap.to_pil()
        except Exception as exc:
            logger.info("decode_qrs_from_pdf: render failed page %s: %s", index, exc)
            continue
        try:
            # Restrict to QR symbols — we don't care about Code-128
            # / EAN / etc. on an invoice.
            decoded = decode(pil_img, symbols=[ZBarSymbol.QRCODE])
        except Exception as exc:
            logger.info("decode_qrs_from_pdf: zbar failed page %s: %s", index, exc)
            continue
        for symbol in decoded:
            try:
                raw = symbol.data.decode("utf-8", errors="replace").strip()
            except Exception:
                raw = ""
            if not raw:
                continue
            results.append(_classify(page_index=index, raw=raw))
    return results


def _classify(*, page_index: int, raw: str) -> DecodedQR:
    """Tag a raw QR payload with its likely meaning."""
    parsed = None
    try:
        parsed = urlparse(raw)
    except Exception:
        parsed = None

    host = (parsed.netloc.lower() if parsed and parsed.netloc else "")
    if parsed and parsed.scheme in ("http", "https") and any(host == h or host.endswith("." + h) for h in _LHDN_HOSTS):
        uuid, long_id = _split_lhdn_path(parsed.path or "")
        return DecodedQR(
            page_index=page_index,
            raw_data=raw,
            kind="lhdn_validation_url",
            lhdn_uuid=uuid,
            lhdn_long_id=long_id,
        )

    if parsed and parsed.scheme in ("http", "https"):
        return DecodedQR(page_index=page_index, raw_data=raw, kind="url")

    if _LHDN_UUID_RE.match(raw):
        return DecodedQR(page_index=page_index, raw_data=raw, kind="uuid", lhdn_uuid=raw)

    return DecodedQR(page_index=page_index, raw_data=raw, kind="other")


def _split_lhdn_path(path: str) -> tuple[str, str]:
    """Pull the UUID + longId out of a MyInvois validation URL path.

    MyInvois validation URLs follow several shapes across portal
    versions; the two we've seen are:

      /document/{uuid}/{longId}
      /{longId}                       (UUID embedded in longId)

    We accept either by walking the segments and applying the
    same UUID regex used for plain-text QRs. The first segment that
    matches is treated as the UUID; whatever comes after is the
    longId.
    """
    parts = [p for p in path.split("/") if p]
    uuid = ""
    long_id = ""
    for i, part in enumerate(parts):
        if _LHDN_UUID_RE.match(part):
            uuid = part
            if i + 1 < len(parts):
                long_id = parts[i + 1]
            break
    if not uuid and parts:
        # Heuristic — longId is typically the last segment when no
        # explicit /document/ prefix is present.
        long_id = parts[-1]
    return uuid, long_id


def pick_lhdn_qr(qrs: Iterable[DecodedQR]) -> DecodedQR | None:
    """First LHDN-validation QR in document order, or None."""
    for qr in qrs:
        if qr.kind == "lhdn_validation_url":
            return qr
    return None
