"""Tests for the Ollama FieldStructure adapter (Slice 29).

Covers:
  - Local config path (no api_key, default host) — request fires without
    an Authorization header; valid response parses into fields.
  - Cloud config path (api_key set, host = ollama.com) — request fires
    with the Authorization header; valid JSON response parses cleanly.
  - Cloud + missing api_key → ``EngineUnavailable`` raised at the call
    site rather than letting the cloud server return a 401.
  - HTTP errors (5xx, connection failure) → ``EngineUnavailable``; the
    adapter never echoes the response body into the exception (which
    would leak prompt-embedded invoice text into audit / inbox).
  - Malformed JSON in the model output → falls through to empty fields,
    confidence 0 — the ``_sync_validation_inbox`` hook handles the
    "structuring skipped" inbox row when the pipeline retries elsewhere.
  - per-engine credentials beat env fallback; env fallback used when
    credentials are absent.
  - The diagnostics block carries the model + token counts (so the
    engine-activity page surfaces them without a separate fetch).
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from apps.extraction.adapters.ollama_adapter import (
    ADAPTER_NAME,
    OllamaFieldStructureAdapter,
)
from apps.extraction.capabilities import EngineUnavailable
from apps.extraction.models import Engine

SCHEMA = ["invoice_number", "issue_date", "supplier_legal_name", "currency_code"]


@pytest.fixture
def engine(db) -> Engine:
    """Engine row matching the seeded ollama-structure migration."""
    engine, _ = Engine.objects.update_or_create(
        name=ADAPTER_NAME,
        defaults={
            "vendor": "ollama",
            "capability": "field_structure",
            "model_identifier": "configurable",
        },
    )
    return engine


def _ollama_response(content: str, **extras) -> httpx.Response:
    """Build a mocked Ollama /api/chat response envelope."""
    body = {
        "model": "test-model",
        "message": {"role": "assistant", "content": content},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 42,
        "eval_count": 17,
        "total_duration": 1_234_000_000,
    }
    body.update(extras)
    return httpx.Response(200, json=body)


@pytest.mark.django_db
class TestLocalPath:
    def test_local_no_api_key_omits_auth_header(self, engine, monkeypatch) -> None:
        # No api_key, default host. The request should fire without an
        # Authorization header — local Ollama treats Bearer tokens as a
        # protocol error.
        monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
        engine.credentials = {
            "host": "http://host.docker.internal:11434",
            "model": "gpt-oss:20b",
        }
        engine.save(update_fields=["credentials"])

        captured: dict = {}

        def fake_post(self, url, *, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return _ollama_response('{"invoice_number": "INV-001", "issue_date": "2025-04-28"}')

        adapter = OllamaFieldStructureAdapter()
        with patch.object(httpx.Client, "post", fake_post):
            result = adapter.structure_fields(text="hello world", target_schema=SCHEMA)

        assert captured["url"] == "http://host.docker.internal:11434/api/chat"
        assert "Authorization" not in captured["headers"]
        assert captured["json"]["model"] == "gpt-oss:20b"
        assert captured["json"]["format"] == "json"
        assert captured["json"]["stream"] is False

        assert result.fields["invoice_number"] == "INV-001"
        assert result.per_field_confidence["invoice_number"] == 0.85
        # Missing fields get 0.0 confidence so downstream code can tell them
        # apart from extracted-but-empty.
        assert result.per_field_confidence["currency_code"] == 0.0
        assert 0 < result.overall_confidence < 1


@pytest.mark.django_db
class TestCloudPath:
    def test_cloud_with_api_key_sends_authorization_header(self, engine) -> None:
        engine.credentials = {
            "host": "https://ollama.com",
            "api_key": "test-key-abc",
            "model": "gemini-3-flash-preview",
        }
        engine.save(update_fields=["credentials"])

        captured: dict = {}

        def fake_post(self, url, *, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            return _ollama_response('{"invoice_number": "C-99"}')

        adapter = OllamaFieldStructureAdapter()
        with patch.object(httpx.Client, "post", fake_post):
            result = adapter.structure_fields(text="hi", target_schema=SCHEMA)

        assert captured["url"] == "https://ollama.com/api/chat"
        assert captured["headers"]["Authorization"] == "Bearer test-key-abc"
        assert result.fields["invoice_number"] == "C-99"
        # Diagnostics carry the model + token counts so the engine-activity
        # page can render them without an extra fetch.
        assert result.diagnostics["model"] == "gemini-3-flash-preview"
        assert result.diagnostics["input_tokens"] == 42
        assert result.diagnostics["output_tokens"] == 17

    def test_cloud_missing_api_key_raises_engine_unavailable(self, engine, monkeypatch) -> None:
        monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
        engine.credentials = {"host": "https://ollama.com", "model": "gpt-oss:120b"}
        engine.save(update_fields=["credentials"])

        adapter = OllamaFieldStructureAdapter()
        with pytest.raises(EngineUnavailable, match="api_key"):
            adapter.structure_fields(text="hi", target_schema=SCHEMA)


@pytest.mark.django_db
class TestErrorPaths:
    def test_http_5xx_raises_engine_unavailable_without_body(self, engine) -> None:
        engine.credentials = {"host": "http://localhost:11434"}
        engine.save(update_fields=["credentials"])

        # The 502 body might echo back parts of our prompt — the invoice
        # text. The adapter must NOT include the body in the exception
        # message (it would leak into audit/inbox detail).
        sensitive_body = "internal error: prompt was 'INVOICE 12345 amount 999...'"

        def fake_post(self, url, *, headers, json):
            return httpx.Response(502, text=sensitive_body)

        adapter = OllamaFieldStructureAdapter()
        with patch.object(httpx.Client, "post", fake_post):
            with pytest.raises(EngineUnavailable) as exc:
                adapter.structure_fields(text="hi", target_schema=SCHEMA)
        assert "502" in str(exc.value)
        assert "INVOICE" not in str(exc.value)
        assert "amount" not in str(exc.value)

    def test_connection_error_raises_engine_unavailable(self, engine) -> None:
        engine.credentials = {"host": "http://localhost:11434"}
        engine.save(update_fields=["credentials"])

        def fake_post(self, url, *, headers, json):
            raise httpx.ConnectError("Connection refused")

        adapter = OllamaFieldStructureAdapter()
        with patch.object(httpx.Client, "post", fake_post):
            with pytest.raises(EngineUnavailable, match="Connection refused"):
                adapter.structure_fields(text="hi", target_schema=SCHEMA)

    def test_malformed_json_falls_through_to_empty_fields(self, engine) -> None:
        engine.credentials = {"host": "http://localhost:11434"}
        engine.save(update_fields=["credentials"])

        def fake_post(self, url, *, headers, json):
            return _ollama_response("this is not JSON at all")

        adapter = OllamaFieldStructureAdapter()
        with patch.object(httpx.Client, "post", fake_post):
            result = adapter.structure_fields(text="hi", target_schema=SCHEMA)

        # No fields populated, no crash — the validation rules will then
        # fire required-field issues and the inbox lifecycle handles the
        # "this needs a human" message.
        assert result.fields == {}
        assert result.overall_confidence == 0.0

    def test_json_with_code_fences_is_stripped(self, engine) -> None:
        engine.credentials = {"host": "http://localhost:11434"}
        engine.save(update_fields=["credentials"])

        # Some models wrap JSON in ```json fences even when format=json
        # was requested. Strip defensively.
        fenced = '```json\n{"invoice_number": "INV-7"}\n```'

        def fake_post(self, url, *, headers, json):
            return _ollama_response(fenced)

        adapter = OllamaFieldStructureAdapter()
        with patch.object(httpx.Client, "post", fake_post):
            result = adapter.structure_fields(text="hi", target_schema=SCHEMA)

        assert result.fields["invoice_number"] == "INV-7"


@pytest.mark.django_db
class TestCredentialResolution:
    def test_engine_credentials_beat_env_fallback(self, engine, monkeypatch) -> None:
        engine.credentials = {
            "host": "http://localhost:11434",
            "model": "from-db",
        }
        engine.save(update_fields=["credentials"])
        monkeypatch.setenv("OLLAMA_MODEL", "from-env")

        captured: dict = {}

        def fake_post(self, url, *, headers, json):
            captured["json"] = json
            return _ollama_response('{"invoice_number": "x"}')

        adapter = OllamaFieldStructureAdapter()
        with patch.object(httpx.Client, "post", fake_post):
            adapter.structure_fields(text="hi", target_schema=SCHEMA)

        assert captured["json"]["model"] == "from-db"

    def test_env_fallback_used_when_credentials_blank(self, engine, monkeypatch) -> None:
        engine.credentials = {}
        engine.save(update_fields=["credentials"])
        monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
        monkeypatch.setenv("OLLAMA_MODEL", "env-model")

        captured: dict = {}

        def fake_post(self, url, *, headers, json):
            captured["url"] = url
            captured["json"] = json
            return _ollama_response('{"invoice_number": "y"}')

        adapter = OllamaFieldStructureAdapter()
        with patch.object(httpx.Client, "post", fake_post):
            adapter.structure_fields(text="hi", target_schema=SCHEMA)

        assert captured["url"] == "http://localhost:11434/api/chat"
        assert captured["json"]["model"] == "env-model"
