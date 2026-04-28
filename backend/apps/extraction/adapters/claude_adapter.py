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
import os

from apps.extraction.capabilities import (
    EngineUnavailable,
    FieldStructureEngine,
    StructuredExtractResult,
    VisionExtractEngine,
)

logger = logging.getLogger(__name__)

VISION_ADAPTER_NAME = "anthropic-claude-sonnet-vision"
STRUCTURE_ADAPTER_NAME = "anthropic-claude-sonnet-structure"

# Cost is rough; calibrated against EngineCall rows once we have data.
VISION_COST_MICROS = 8_000  # ~$0.008 per page
STRUCTURE_COST_MICROS = 4_000  # ~$0.004 per call

# 4.6 is the Sonnet line that's vision-capable and stable for production.
# (Per the model knowledge cutoff: Sonnet 4.6 ID is "claude-sonnet-4-6".)
DEFAULT_MODEL = "claude-sonnet-4-6"


def _client():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise EngineUnavailable("ANTHROPIC_API_KEY is not set; Claude adapter is unavailable.")
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise EngineUnavailable("anthropic SDK is not installed") from exc
    return Anthropic(api_key=api_key)


def _parse_json_payload(text: str) -> dict[str, str]:
    """Models occasionally wrap JSON in prose or fences; strip both."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        return {str(k): str(v) for k, v in parsed.items()}
    return {}


class ClaudeVisionAdapter(VisionExtractEngine):
    name = VISION_ADAPTER_NAME

    def extract_vision(
        self, *, body: bytes, mime_type: str, target_schema: list[str]
    ) -> StructuredExtractResult:
        client = _client()

        b64 = base64.b64encode(body).decode("ascii")
        schema_list = "\n".join(f"- {f}" for f in target_schema)

        message = client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": mime_type, "data": b64},
                        },
                        {
                            "type": "text",
                            "text": (
                                "You are extracting fields from a Malaysian invoice for "
                                "LHDN MyInvois submission. Return a single JSON object whose "
                                "keys are exactly the field names below and whose values are "
                                "extracted strings. If a field is absent, use an empty string.\n\n"
                                f"Fields:\n{schema_list}\n\n"
                                "Respond with the JSON object only, no prose."
                            ),
                        },
                    ],
                }
            ],
        )

        text_blocks = [b.text for b in message.content if getattr(b, "type", "") == "text"]
        raw = "\n".join(text_blocks)
        fields = _parse_json_payload(raw)

        # Per-field confidence: not provided by the API; we treat
        # populated-and-non-empty as 0.85, missing as 0.0.
        per_field_confidence = {f: (0.85 if fields.get(f) else 0.0) for f in target_schema}
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
        client = _client()
        schema_list = "\n".join(f"- {f}" for f in target_schema)

        message = client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "You are structuring extracted text from a Malaysian invoice for "
                        "LHDN MyInvois submission. Return a single JSON object whose keys "
                        "are exactly the field names below and whose values are extracted "
                        "strings. If a field is absent, use an empty string.\n\n"
                        f"Fields:\n{schema_list}\n\n"
                        f"Invoice text:\n---\n{text}\n---\n\n"
                        "Respond with the JSON object only, no prose."
                    ),
                }
            ],
        )

        text_blocks = [b.text for b in message.content if getattr(b, "type", "") == "text"]
        raw = "\n".join(text_blocks)
        fields = _parse_json_payload(raw)

        per_field_confidence = {f: (0.85 if fields.get(f) else 0.0) for f in target_schema}
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
