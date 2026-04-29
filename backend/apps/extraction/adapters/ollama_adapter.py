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
from apps.extraction.prompts import build_field_structure_prompt

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
    host = (
        engine_credential(
            engine_name=engine_name,
            key=_HOST_FIELD,
            env_fallback=_HOST_ENV_FALLBACK,
        )
        or _DEFAULT_HOST_LOCAL
    )
    api_key = engine_credential(
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
    # Strip a trailing slash so we can concatenate cleanly. The cloud sometimes
    # returns errors on a doubled slash.
    return host.rstrip("/"), api_key, model


def _parse_json_payload(text: str) -> dict[str, Any]:
    """Strip code fences then JSON-load. Returns the dict as-is.

    Header fields come back as strings; ``line_items`` comes back as a
    list of dicts. The downstream materialiser
    (``submission.services._materialise_line_items``) handles both
    "raw is the list" and "raw is a JSON-encoded string" — keeping the
    list intact here avoids a needless string-round-trip on the happy
    path.
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


class OllamaFieldStructureAdapter(FieldStructureEngine):
    """Structures raw text → LHDN fields via Ollama's chat API."""

    name = ADAPTER_NAME

    def structure_fields(self, *, text: str, target_schema: list[str]) -> StructuredExtractResult:
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
                    "content": build_field_structure_prompt(text=text, target_schema=target_schema),
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
            raise EngineUnavailable(f"Ollama request to {host}/api/chat failed: {exc}") from exc

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
        raw_envelope = str(message.get("content") or "")
        parsed = _parse_json_payload(raw_envelope)

        # Flatten to ``dict[str, str]`` per the StructuredExtractResult
        # contract. ``line_items`` is the one structured key — it comes
        # back as a list of dicts; we JSON-encode it so the receiver
        # (``submission._materialise_line_items``) can parse it back. The
        # alternative — widening the contract to ``dict[str, Any]`` —
        # would force every consumer to type-check on every field; this
        # one indirection is cheaper.
        fields: dict[str, str] = {}
        for key, value in parsed.items():
            if value is None:
                fields[str(key)] = ""
            elif isinstance(value, (list, dict)):
                fields[str(key)] = json.dumps(value)
            else:
                fields[str(key)] = str(value)

        # Per-field confidence: 0.85 if the model populated the field with
        # something non-empty, 0.0 otherwise. For ``line_items`` "non-empty"
        # means the parsed list had at least one entry — a JSON string of
        # ``"[]"`` should NOT count as confident.
        def _is_populated(key: str) -> bool:
            value = parsed.get(key)
            if value is None or value == "":
                return False
            if isinstance(value, (list, dict)):
                return len(value) > 0
            return True

        per_field_confidence = {f: (0.85 if _is_populated(f) else 0.0) for f in target_schema}
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
