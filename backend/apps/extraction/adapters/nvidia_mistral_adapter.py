"""NVIDIA NIM adapter — FieldStructure capability.

Slice 108 — adds a third FieldStructure engine alongside the existing
Ollama Cloud and Anthropic Claude rails. NVIDIA NIM
(integrate.api.nvidia.com) hosts a roster of open-weight models
behind an OpenAI-compatible ``/v1/chat/completions`` endpoint.

The default we ship is ``nvidia/llama-3.3-nemotron-super-49b-v1`` —
NVIDIA's fine-tuned Llama 3.3 70B, the fastest of the structuring-
quality models on NIM (cold-start round-trip under 1s, full invoice
prompt around 15s). We tested with ``mistralai/mistral-large-3-...``
first; it produced clean JSON but routinely took 80-180s per call
which is incompatible with a synchronous "user pressed Re-extract
and is waiting" UX. The model is configurable per-Engine via the
``model`` credential so an operator can swap to whatever NIM hosts
this month.

Why a separate adapter and not "OpenAI-compatible adapter": the
endpoint paths are the same as OpenAI but the auth shape, default
host, and pricing context differ — bundling them under one
"openai-compatible" class would invite a misconfigured Engine
credentials blob to point at the wrong vendor. Per-vendor adapters
keep the contract obvious.

Graceful degrade — on non-2xx response, malformed JSON, or transport
failure raise ``EngineUnavailable``. The router treats that as
"try the next rule"; this engine runs at priority 25 so the
downstream chain is Ollama (50) → Anthropic Claude (100).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from apps.extraction.capabilities import (
    EngineUnavailable,
    FieldStructureEngine,
    StructuredExtractResult,
)
from apps.extraction.credentials import engine_credential, require_engine_credential
from apps.extraction.prompts import build_field_structure_prompt

logger = logging.getLogger(__name__)

ADAPTER_NAME = "nvidia-mistral-structure"

# Cost: NVIDIA NIM is metered per-token but the API response does not
# include a billable cost field. We leave cost_micros at 0 and
# reconstruct from usage tokens via ``diagnostics`` if we need to.
COST_MICROS = 0

# Defaults match the NVIDIA NIM catalog at the time of writing.
# Override per deployment via ``Engine.credentials`` (preferred) or
# env (dev fallback).
_DEFAULT_HOST = "https://integrate.api.nvidia.com"
_DEFAULT_MODEL = "nvidia/llama-3.3-nemotron-super-49b-v1"

_HOST_FIELD = "host"
_API_KEY_FIELD = "api_key"
_MODEL_FIELD = "model"

_HOST_ENV_FALLBACK = "NVIDIA_HOST"
_API_KEY_ENV_FALLBACK = "NVIDIA_API_KEY"
_MODEL_ENV_FALLBACK = "NVIDIA_MODEL"

# 180s is intentional — the NIM Mistral Large 3 endpoint regularly takes
# 60-120s end-to-end on cold start (verified: 82s for a 16-token prompt)
# and a multi-page invoice prompt can push to 150s. Override per env via
# NVIDIA_STRUCTURING_TIMEOUT for tenants on a faster model.
_DEFAULT_TIMEOUT_SECONDS = 180.0

# Generation params. Low temperature for deterministic JSON; high enough
# max_tokens for a 20-line invoice (each line ~80 tokens of JSON).
_TEMPERATURE = 0.15
_MAX_TOKENS = 4096


def _timeout_seconds() -> float:
    raw = os.environ.get("NVIDIA_STRUCTURING_TIMEOUT", "")
    if not raw:
        return _DEFAULT_TIMEOUT_SECONDS
    try:
        return float(raw)
    except ValueError:
        return _DEFAULT_TIMEOUT_SECONDS


def _resolve_config(*, engine_name: str) -> tuple[str, str, str]:
    """Return (host, api_key, model). All three required."""
    host = (
        engine_credential(
            engine_name=engine_name,
            key=_HOST_FIELD,
            env_fallback=_HOST_ENV_FALLBACK,
        )
        or _DEFAULT_HOST
    )
    api_key = require_engine_credential(
        engine_name=engine_name,
        key=_API_KEY_FIELD,
        env_fallback=_API_KEY_ENV_FALLBACK,
    )
    model = (
        engine_credential(
            engine_name=engine_name,
            key=_MODEL_FIELD,
            env_fallback=_MODEL_ENV_FALLBACK,
        )
        or _DEFAULT_MODEL
    )
    return host.rstrip("/"), api_key, model


def _parse_json_payload(text: str) -> dict[str, Any]:
    """Strip code fences then JSON-load. Returns the dict as-is.

    The downstream materialiser handles list values for ``line_items`` —
    we keep them intact (not stringified) so the receiver doesn't have
    to undo a round-trip on the happy path.
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
    return parsed


class NvidiaMistralFieldStructureAdapter(FieldStructureEngine):
    """Structures raw text → LHDN fields via NVIDIA NIM chat completions."""

    name = ADAPTER_NAME

    def structure_fields(self, *, text: str, target_schema: list[str]) -> StructuredExtractResult:
        host, api_key, model = _resolve_config(engine_name=self.name)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": build_field_structure_prompt(text=text, target_schema=target_schema),
                }
            ],
            "max_tokens": _MAX_TOKENS,
            "temperature": _TEMPERATURE,
            "top_p": 1.0,
            "frequency_penalty": 0.0,
            "presence_penalty": 0.0,
            "stream": False,
            # OpenAI-compatible JSON-mode signal. Most NIM models honour
            # this; the prompt also asks for JSON so model variants that
            # ignore the param still produce parseable output.
            "response_format": {"type": "json_object"},
        }

        endpoint = f"{host}/v1/chat/completions"
        try:
            with httpx.Client(timeout=_timeout_seconds()) as client:
                response = client.post(endpoint, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise EngineUnavailable(
                f"NVIDIA NIM request to {endpoint} failed: {exc}"
            ) from exc

        if response.status_code >= 400:
            # Don't echo the response body — it can contain our prompt
            # (invoice text) which would land in audit/inbox detail.
            # Status code is enough for ops to debug from the access log.
            raise EngineUnavailable(
                f"NVIDIA NIM returned HTTP {response.status_code} from {endpoint}"
            )

        try:
            envelope = response.json()
        except ValueError as exc:
            raise EngineUnavailable("NVIDIA NIM response was not JSON") from exc

        choices = envelope.get("choices") or []
        if not choices:
            raise EngineUnavailable("NVIDIA NIM response had no choices")
        message = choices[0].get("message") or {}
        raw_content = str(message.get("content") or "")
        parsed = _parse_json_payload(raw_content)

        # Flatten to ``dict[str, str]`` per the StructuredExtractResult
        # contract. ``line_items`` (the only structured key) stays as a
        # JSON-encoded string so the receiver can parse the list back.
        fields: dict[str, str] = {}
        for key, value in parsed.items():
            if value is None:
                fields[str(key)] = ""
            elif isinstance(value, (list, dict)):
                fields[str(key)] = json.dumps(value)
            else:
                fields[str(key)] = str(value)

        # Per-field confidence: 0.85 when the model populated a non-empty
        # value, 0.0 otherwise. Matches the Ollama adapter so downstream
        # consumers don't have to special-case per engine. An empty list
        # for ``line_items`` (``"[]"``) does NOT count as confident.
        def _is_populated(key: str) -> bool:
            value = parsed.get(key)
            if value is None or value == "":
                return False
            if isinstance(value, (list, dict)):
                return len(value) > 0
            return True

        per_field_confidence = {f: (0.85 if _is_populated(f) else 0.0) for f in target_schema}
        overall = sum(per_field_confidence.values()) / max(len(per_field_confidence), 1)

        usage = envelope.get("usage") or {}
        return StructuredExtractResult(
            fields=fields,
            per_field_confidence=per_field_confidence,
            overall_confidence=overall,
            cost_micros=COST_MICROS,
            diagnostics={
                "model": model,
                "host": host,
                "finish_reason": choices[0].get("finish_reason", ""),
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
        )
