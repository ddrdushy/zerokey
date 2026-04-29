"""Anthropic Claude adapter — VisionExtract + FieldStructure.

Claude Sonnet 4.6 is the launch primary for both VisionExtract (image →
structured fields, bypassing text extraction) and FieldStructure (raw text →
structured fields).

Graceful degrade
----------------
If ``ANTHROPIC_API_KEY`` is unset, ``EngineUnavailable`` is raised. The
router treats that as the engine being unavailable; the job's state-machine
transition records the reason and surfaces it in the UI rather than
crashing.

Phase 2 cut: this returns a *plausible* structure that exercises the
end-to-end shape (status flips, EngineCall row recorded, audit event
written). The real prompt + LHDN field schema lands when the Invoice
entity is added in the next slice.
"""

from __future__ import annotations

import base64
import json
import logging

from apps.extraction.capabilities import (
    EngineUnavailable,
    FieldStructureEngine,
    StructuredExtractResult,
    VisionExtractEngine,
)
from apps.extraction.credentials import require_engine_credential
from apps.extraction.prompts import build_field_structure_prompt

logger = logging.getLogger(__name__)

VISION_ADAPTER_NAME = "anthropic-claude-sonnet-vision"
STRUCTURE_ADAPTER_NAME = "anthropic-claude-sonnet-structure"

# Cost is rough; calibrated against EngineCall rows once we have data.
VISION_COST_MICROS = 8_000  # ~$0.008 per page
STRUCTURE_COST_MICROS = 4_000  # ~$0.004 per call

# 4.6 is the Sonnet line that's vision-capable and stable for production.
# (Per the model knowledge cutoff: Sonnet 4.6 ID is "claude-sonnet-4-6".)
DEFAULT_MODEL = "claude-sonnet-4-6"

# Credential key on the Engine.credentials JSONField. The same key is used
# by both Anthropic adapter rows (vision + structure) so the super-admin
# typically populates them with the same value, but they CAN diverge for
# customers who maintain separate Anthropic accounts per use case.
_API_KEY_FIELD = "api_key"
_API_KEY_ENV_FALLBACK = "ANTHROPIC_API_KEY"


def _client(*, engine_name: str):
    api_key = require_engine_credential(
        engine_name=engine_name,
        key=_API_KEY_FIELD,
        env_fallback=_API_KEY_ENV_FALLBACK,
    )
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise EngineUnavailable("anthropic SDK is not installed") from exc
    return Anthropic(api_key=api_key)


def _parse_json_payload(text: str) -> dict[str, str]:
    """Models occasionally wrap JSON in prose or fences; strip both.

    Header fields come back as strings; ``line_items`` comes back as a
    list of dicts. We flatten to ``dict[str, str]`` per the
    StructuredExtractResult contract by JSON-encoding the list back into
    a string — the receiver
    (``submission.services._materialise_line_items``) parses it.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    flat: dict[str, str] = {}
    for k, v in parsed.items():
        if v is None:
            flat[str(k)] = ""
        elif isinstance(v, (list, dict)):
            flat[str(k)] = json.dumps(v)
        else:
            flat[str(k)] = str(v)
    return flat


_IMAGE_MIME_PREFIX = "image/"
_PDF_MIME = "application/pdf"


def _document_block(*, body: bytes, mime_type: str) -> dict:
    """Build the right Anthropic content block for the input mime type.

    Claude accepts PDFs natively as a ``document`` block and images as an
    ``image`` block. We dispatch on the mime so the same adapter can handle
    both the image-first VisionExtract case and the PDF-escalation case
    (low-confidence native-PDF text extraction routes the original PDF
    here for a layout-aware second pass).
    """
    b64 = base64.b64encode(body).decode("ascii")
    if mime_type == _PDF_MIME:
        return {
            "type": "document",
            "source": {"type": "base64", "media_type": _PDF_MIME, "data": b64},
        }
    if mime_type.startswith(_IMAGE_MIME_PREFIX):
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": mime_type, "data": b64},
        }
    raise EngineUnavailable(
        f"Claude vision adapter does not handle mime {mime_type!r} "
        f"(supported: {_PDF_MIME}, image/*)"
    )


class ClaudeVisionAdapter(VisionExtractEngine):
    name = VISION_ADAPTER_NAME

    def extract_vision(
        self, *, body: bytes, mime_type: str, target_schema: list[str]
    ) -> StructuredExtractResult:
        client = _client(engine_name=self.name)

        document_block = _document_block(body=body, mime_type=mime_type)
        # Vision and text-structure share the same target schema, so the
        # text prompt builder works here too — we just stuff a placeholder
        # string for the "invoice text" section since the document is
        # passed via the binary block instead.
        text_prompt = build_field_structure_prompt(
            text="(see attached document)", target_schema=target_schema
        )

        message = client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": [
                        document_block,
                        {"type": "text", "text": text_prompt},
                    ],
                }
            ],
        )

        text_blocks = [b.text for b in message.content if getattr(b, "type", "") == "text"]
        raw = "\n".join(text_blocks)
        fields = _parse_json_payload(raw)

        # Confidence: same heuristic as the structuring path; "[]" is the
        # JSON-encoded empty list of line items, which should NOT count.
        def _populated(field: str) -> bool:
            value = fields.get(field, "")
            if not value:
                return False
            if value in ("[]", "{}"):
                return False
            return True

        per_field_confidence = {f: (0.85 if _populated(f) else 0.0) for f in target_schema}
        overall = sum(per_field_confidence.values()) / max(len(per_field_confidence), 1)

        return StructuredExtractResult(
            fields=fields,
            per_field_confidence=per_field_confidence,
            overall_confidence=overall,
            cost_micros=VISION_COST_MICROS,
            diagnostics={
                "model": DEFAULT_MODEL,
                "stop_reason": getattr(message, "stop_reason", ""),
                "input_tokens": getattr(message.usage, "input_tokens", 0),
                "output_tokens": getattr(message.usage, "output_tokens", 0),
            },
        )


class ClaudeFieldStructureAdapter(FieldStructureEngine):
    name = STRUCTURE_ADAPTER_NAME

    def structure_fields(self, *, text: str, target_schema: list[str]) -> StructuredExtractResult:
        client = _client(engine_name=self.name)

        message = client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": build_field_structure_prompt(text=text, target_schema=target_schema),
                }
            ],
        )

        text_blocks = [b.text for b in message.content if getattr(b, "type", "") == "text"]
        raw = "\n".join(text_blocks)
        fields = _parse_json_payload(raw)

        # Confidence: 0.85 if populated. The flat dict has line_items as a
        # JSON-encoded string; "[]" is two chars and would naively count as
        # populated. Detect and demote to 0.0.
        def _populated(field: str) -> bool:
            value = fields.get(field, "")
            if not value:
                return False
            if value in ("[]", "{}"):
                return False
            return True

        per_field_confidence = {f: (0.85 if _populated(f) else 0.0) for f in target_schema}
        overall = sum(per_field_confidence.values()) / max(len(per_field_confidence), 1)

        return StructuredExtractResult(
            fields=fields,
            per_field_confidence=per_field_confidence,
            overall_confidence=overall,
            cost_micros=STRUCTURE_COST_MICROS,
            diagnostics={
                "model": DEFAULT_MODEL,
                "stop_reason": getattr(message, "stop_reason", ""),
                "input_tokens": getattr(message.usage, "input_tokens", 0),
                "output_tokens": getattr(message.usage, "output_tokens", 0),
            },
        )
