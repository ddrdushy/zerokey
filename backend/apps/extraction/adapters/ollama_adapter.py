"""Ollama adapter — FieldStructure capability.

Single adapter that handles both local Ollama (``http://host.docker.internal:11434``)
and Ollama Cloud (``https://ollama.com``) by treating the host + optional API
key as per-engine credentials. The wire format is identical for both — same
``/api/chat`` endpoint, same JSON-mode parameter, only the ``Authorization``
header differs.

Why one adapter instead of two:
  - The Engine row carries the host + key + model as credentials, so a
    super-admin can swap a local install for a cloud subscription (or
    rotate keys) without touching code.
  - Routing only cares about *which engine* to pick; whether the engine
    happens to live on localhost or in someone else's data center is
    behind the credentials, not the routing rules.

Graceful degrade
----------------
If the host responds with a non-2xx, the response isn't valid JSON, or the
network request fails, ``EngineUnavailable`` is raised. The router treats
that as the engine being unavailable; the calling pipeline records the
reason and surfaces it in the inbox rather than crashing.

JSON mode
---------
Ollama's ``format: "json"`` parameter constrains the output to valid JSON.
This works on most cloud models and on most local models that follow
instructions. We still parse defensively (strip code fences, accept
top-level dicts only) because the model may produce JSON wrapped in a
trailing newline or, on edge cases, refuse JSON mode.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from apps.extraction.capabilities import (
    EngineUnavailable,
    FieldStructureEngine,
    StructuredExtractResult,
)
from apps.extraction.credentials import engine_credential, require_engine_credential

logger = logging.getLogger(__name__)

ADAPTER_NAME = "ollama-structure"

# Cost: zero for local; for cloud, pricing is per-token but Ollama's API
# doesn't return a billable cost field. We keep cost_micros at 0 and rely
# on the diagnostics block (input/output tokens) for spend reconstruction
# later if we need it.
COST_MICROS = 0

# Defaults match the cloud catalog at the time of writing. Override per
# deployment via ``Engine.credentials`` (preferred) or env (dev fallback).
_DEFAULT_HOST_LOCAL = "http://host.docker.internal:11434"
_DEFAULT_MODEL = "gpt-oss:120b"

_HOST_FIELD = "host"
_API_KEY_FIELD = "api_key"
_MODEL_FIELD = "model"

_HOST_ENV_FALLBACK = "OLLAMA_HOST"
_API_KEY_ENV_FALLBACK = "OLLAMA_API_KEY"
_MODEL_ENV_FALLBACK = "OLLAMA_MODEL"

# 60s is comfortable for cloud models; local 8B models finish in 5-15s on a
# laptop, cloud frontier models in 5-30s. A frontier MoE doing structuring
# of a multi-page invoice can occasionally cross 30s, so we leave headroom.
_REQUEST_TIMEOUT_SECONDS = 60.0


def _resolve_config(*, engine_name: str) -> tuple[str, str | None, str]:
    """Return (host, api_key, model). ``api_key`` may be None for local."""
    host = engine_credential(
        engine_name=engine_name,
        key=_HOST_FIELD,
        env_fallback=_HOST_ENV_FALLBACK,
    ) or _DEFAULT_HOST_LOCAL
    api_key = engine_credential(
        engine_name=engine_name,
        key=_API_KEY_FIELD,
        env_fallback=_API_KEY_ENV_FALLBACK,
    )
    model = engine_credential(
        engine_name=engine_name,
        key=_MODEL_FIELD,
        env_fallback=_MODEL_ENV_FALLBACK,
    ) or _DEFAULT_MODEL
    # Strip a trailing slash so we can concatenate cleanly. The cloud sometimes
    # returns errors on a doubled slash.
    return host.rstrip("/"), api_key, model


def _parse_json_payload(text: str) -> dict[str, str]:
    """Strip code fences then JSON-load; flatten to ``{str: str}``."""
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
        elif isinstance(v, (dict, list)):
            # Nested structures aren't part of our schema; flatten to JSON
            # text so the caller can still see what the model returned and
            # the pipeline doesn't blow up.
            flat[str(k)] = json.dumps(v)
        else:
            flat[str(k)] = str(v)
    return flat


def _build_prompt(*, text: str, target_schema: list[str]) -> str:
    schema_list = "\n".join(f"- {f}" for f in target_schema)
    return (
        "You are structuring extracted text from a Malaysian invoice for "
        "LHDN MyInvois submission. Return a single JSON object whose keys "
        "are exactly the field names below and whose values are extracted "
        "strings. If a field is absent, use an empty string.\n\n"
        f"Fields:\n{schema_list}\n\n"
        f"Invoice text:\n---\n{text}\n---\n\n"
        "Respond with the JSON object only, no prose."
    )


class OllamaFieldStructureAdapter(FieldStructureEngine):
    """Structures raw text → LHDN fields via Ollama's chat API."""

    name = ADAPTER_NAME

    def structure_fields(
        self, *, text: str, target_schema: list[str]
    ) -> StructuredExtractResult:
        host, api_key, model = _resolve_config(engine_name=self.name)

        # Cloud requires Authorization; local doesn't. Treat the cloud host
        # as needing a key, and require it explicitly so a misconfigured
        # cloud Engine fails at the call site (clear inbox message) rather
        # than producing a 401 from the server.
        if "ollama.com" in host:
            api_key = require_engine_credential(
                engine_name=self.name,
                key=_API_KEY_FIELD,
                env_fallback=_API_KEY_ENV_FALLBACK,
            )

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": _build_prompt(text=text, target_schema=target_schema),
                }
            ],
            "stream": False,
            "format": "json",
        }

        try:
            with httpx.Client(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
                response = client.post(
                    f"{host}/api/chat",
                    headers=headers,
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise EngineUnavailable(
                f"Ollama request to {host}/api/chat failed: {exc}"
            ) from exc

        if response.status_code >= 400:
            # Don't include the response body in the exception — it can
            # echo our prompt back, which carries the invoice text and
            # would land in audit/inbox detail. Status code + reason is
            # enough for ops to debug from the access log.
            raise EngineUnavailable(
                f"Ollama returned HTTP {response.status_code} from {host}/api/chat"
            )

        try:
            envelope = response.json()
        except ValueError as exc:
            raise EngineUnavailable("Ollama response was not JSON") from exc

        message = envelope.get("message") or {}
        raw = str(message.get("content") or "")
        fields = _parse_json_payload(raw)

        # Per-field confidence: Ollama doesn't expose calibrated logprobs in
        # the chat API, so we use the same populated-as-0.85 / missing-as-0
        # heuristic the Claude adapter uses. Calibration tables land later
        # per ENGINE_REGISTRY.md.
        per_field_confidence = {
            f: (0.85 if fields.get(f) else 0.0) for f in target_schema
        }
        overall = sum(per_field_confidence.values()) / max(len(per_field_confidence), 1)

        return StructuredExtractResult(
            fields=fields,
            per_field_confidence=per_field_confidence,
            overall_confidence=overall,
            cost_micros=COST_MICROS,
            diagnostics={
                "model": model,
                "host": host,
                "done_reason": envelope.get("done_reason", ""),
                "input_tokens": envelope.get("prompt_eval_count", 0),
                "output_tokens": envelope.get("eval_count", 0),
                "total_duration_ns": envelope.get("total_duration", 0),
            },
        )
