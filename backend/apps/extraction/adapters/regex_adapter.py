"""Regex-based field structurer for the OCR-only extraction lane (Slice 54).

This is the *floor* structurer the OCR-only lane uses today. It pulls
the easy fields (invoice number, dates, totals, tax IDs, line totals)
out of the raw OCR text using deterministic regex. No LLM call.

Quality is intentionally modest — it gets ~60-70% of fields right on
clean Malaysian invoices. The two follow-up slices replace this:

  - **Slice 55**: PaddleOCR + PP-Structure detect tables → line items
    deterministically rather than guessing from flat text.
  - **Slice 56**: LayoutLMv3 KIE for invoice header fields → real
    ML-grade field accuracy without per-document AI cost.

After Slice 56 lands this adapter remains as the last-resort fallback
when LayoutLMv3 itself returns no answer, so the OCR lane never
silently produces an empty Invoice — there's always at least the
regex floor.

The adapter is registered in the engine registry via the seed data
in ``identity/migrations/seed_engines.py`` (separate slice). Today
the structuring service can resolve it by name explicitly when the
org is in OCR-only mode.
"""

from __future__ import annotations

import json
import re
from typing import Any

from apps.extraction.capabilities import (
    FieldStructureEngine,
    StructuredExtractResult,
)


# Field-level regex patterns. Each entry is (lhdn_field_code, [patterns]).
# The first pattern that matches wins. Patterns are intentionally
# conservative — false negatives (no field) are recoverable in
# review; false positives (wrong value) are a worse user experience.
_HEADER_PATTERNS: dict[str, list[str]] = {
    "invoice_number": [
        r"(?im)^\s*invoice\s*(?:no|number|#)\.?\s*[:#]?\s*([A-Z0-9][A-Z0-9\-_/]{2,32})",
        r"(?im)^\s*inv(?:oice)?\s*[:#]?\s*([A-Z0-9][A-Z0-9\-_/]{2,32})",
        r"(?im)^\s*ref\.?\s*(?:no|#)\.?\s*[:#]?\s*([A-Z0-9][A-Z0-9\-_/]{2,32})",
    ],
    "issue_date": [
        r"(?im)^\s*invoice\s*date\s*[:#]?\s*(\d{1,2}[\-/\s]\w{3,9}[\-/\s]\d{2,4})",
        r"(?im)^\s*invoice\s*date\s*[:#]?\s*(\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4})",
        r"(?im)^\s*date\s*[:#]?\s*(\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4})",
        r"(?im)^\s*date\s*[:#]?\s*(\d{4}[\-/]\d{1,2}[\-/]\d{1,2})",
    ],
    "due_date": [
        r"(?im)^\s*due\s*date\s*[:#]?\s*(\d{1,2}[\-/\s]\w{3,9}[\-/\s]\d{2,4})",
        r"(?im)^\s*due\s*date\s*[:#]?\s*(\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4})",
        r"(?im)^\s*payment\s*due\s*[:#]?\s*(\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4})",
    ],
    "currency_code": [
        r"\b(MYR|USD|SGD|EUR|GBP|JPY|CNY|AUD|HKD|THB|IDR|PHP|VND)\b",
    ],
    "supplier_tin": [
        # Malaysian TIN format: C + 10 digits for company, IG + digits
        # for individuals. The validator (Slice 11) enforces this
        # canonically; the regex is tolerant.
        r"\b(C\d{10}|IG\d{8,12})\b",
    ],
    "supplier_sst_number": [
        # SST = Sales & Service Tax registration. Format varies but
        # typically W + digits or 8-12 digits.
        r"(?i)\bsst\s*(?:no|#)?\.?\s*[:#]?\s*([A-Z]?\d[\d\-]{7,15})\b",
    ],
}

# Total / tax patterns are special-cased because they're often
# labelled across multiple lines + use thousand separators.
_TOTAL_PATTERN = re.compile(
    r"(?im)^\s*(?:grand\s*)?total\s*(?:amount)?\s*[:#]?\s*(?:RM|MYR|\$|USD)?\s*"
    r"([\d,]+\.\d{2})",
)
_SUBTOTAL_PATTERN = re.compile(
    r"(?im)^\s*sub[\s\-]?total\s*[:#]?\s*(?:RM|MYR|\$|USD)?\s*([\d,]+\.\d{2})",
)
_TAX_PATTERN = re.compile(
    r"(?im)^\s*(?:sst|tax|gst)\s*(?:\d+%)?\s*[:#]?\s*(?:RM|MYR|\$|USD)?\s*([\d,]+\.\d{2})",
)


def _normalize_amount(raw: str) -> str:
    """Strip thousand separators, keep the decimal."""
    return raw.replace(",", "").strip()


def _extract_header(text: str) -> tuple[dict[str, str], dict[str, float]]:
    fields: dict[str, str] = {}
    confidences: dict[str, float] = {}
    for field_name, patterns in _HEADER_PATTERNS.items():
        for pat in patterns:
            match = re.search(pat, text)
            if match:
                fields[field_name] = match.group(1).strip()
                # Regex hits get a fixed mid-confidence — we trust
                # the labelled-line heuristic but not enough to skip
                # human review by default.
                confidences[field_name] = 0.7
                break
    # Totals
    total_match = _TOTAL_PATTERN.search(text)
    if total_match:
        fields["total_amount"] = _normalize_amount(total_match.group(1))
        confidences["total_amount"] = 0.75
    subtotal_match = _SUBTOTAL_PATTERN.search(text)
    if subtotal_match:
        fields["subtotal_amount"] = _normalize_amount(subtotal_match.group(1))
        confidences["subtotal_amount"] = 0.75
    tax_match = _TAX_PATTERN.search(text)
    if tax_match:
        fields["tax_amount"] = _normalize_amount(tax_match.group(1))
        confidences["tax_amount"] = 0.7
    return fields, confidences


def _extract_line_items(text: str) -> list[dict[str, str]]:
    """Best-effort line-item extraction.

    Looks for lines matching ``<description>  <qty>  <unit>  <amount>``
    where amount is a decimal with 2 dp. This is a coarse heuristic;
    PP-Structure (Slice 55) replaces it with table-aware parsing.
    """
    items: list[dict[str, str]] = []
    line_pat = re.compile(
        r"^\s*(?P<desc>.{3,80}?)\s{2,}"
        r"(?P<qty>\d+(?:\.\d+)?)\s+"
        r"(?P<unit>\d+(?:[,.]\d+)?)\s+"
        r"(?P<amount>\d+(?:[,.]\d+)?)\s*$",
        re.MULTILINE,
    )
    for match in line_pat.finditer(text):
        items.append(
            {
                "description": match.group("desc").strip(),
                "quantity": match.group("qty"),
                "unit_price": _normalize_amount(match.group("unit")),
                "line_total": _normalize_amount(match.group("amount")),
            }
        )
    return items


class RegexFloorStructurer(FieldStructureEngine):
    """Last-resort field structurer used by the OCR-only lane.

    Implements ``FieldStructure`` so it slots into the same call site
    as the LLM structurers. No external dependencies; no per-call
    cost; deterministic output.
    """

    name = "regex-floor-structurer"

    def structure_fields(
        self, *, text: str, target_schema: list[str]
    ) -> StructuredExtractResult:
        fields, per_field_confidence = _extract_header(text)
        line_items = _extract_line_items(text)
        if line_items:
            # The LHDN line-items field key is documented in
            # ``submission.services.LINE_ITEMS_KEY`` ("line_items"). We
            # don't import that module here to avoid a load cycle —
            # the key is stable. ``_materialise_line_items`` accepts
            # both a JSON string and a parsed list; we use the string
            # form to match the LLM-structurer contract.
            fields["line_items"] = json.dumps(line_items)
            per_field_confidence["line_items"] = 0.6

        # Overall confidence is the mean of per-field hits, scaled
        # by coverage (0.0 if zero fields hit). A document that
        # gives us 8/10 fields scores meaningfully higher than one
        # that gives us 2/10, even if those 2 hits were high-quality.
        coverage = len(fields) / max(len(target_schema), 1)
        mean_conf = (
            sum(per_field_confidence.values()) / len(per_field_confidence)
            if per_field_confidence
            else 0.0
        )
        overall = round(mean_conf * (0.5 + 0.5 * coverage), 4)

        diagnostics: dict[str, Any] = {
            "structurer": "regex-floor",
            "fields_hit": sorted(fields.keys()),
            "coverage": round(coverage, 3),
        }
        return StructuredExtractResult(
            fields=fields,
            per_field_confidence=per_field_confidence,
            overall_confidence=overall,
            cost_micros=0,
            diagnostics={
                **diagnostics,
                "line_count": len(line_items),
            },
        )
