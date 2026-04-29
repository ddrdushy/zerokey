"""Tests for the per-engine credential resolver.

Mirrors the SystemSetting resolver contract but keyed off ``Engine.credentials``
instead of ``SystemSetting.values``. The intent: adapters call
``engine_credential`` instead of ``os.environ.get`` so the super-admin can
rotate vendor keys from the operations console without a redeploy. The env
var stays as a bootstrap fallback.
"""

from __future__ import annotations

import pytest

from apps.extraction.capabilities import EngineUnavailable
from apps.extraction.credentials import engine_credential, require_engine_credential
from apps.extraction.models import Engine


@pytest.fixture
def vision_engine(db) -> Engine:
    engine, _ = Engine.objects.update_or_create(
        name="anthropic-claude-sonnet-vision",
        defaults={"vendor": "anthropic", "capability": "vision_extract"},
    )
    return engine


@pytest.mark.django_db
class TestEngineCredentialResolver:
    def test_db_value_takes_precedence_over_env(self, vision_engine, monkeypatch) -> None:
        vision_engine.credentials = {"api_key": "from-db"}
        vision_engine.save(update_fields=["credentials"])
        monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")

        value = engine_credential(
            engine_name=vision_engine.name,
            key="api_key",
            env_fallback="ANTHROPIC_API_KEY",
        )
        assert value == "from-db"

    def test_falls_back_to_env_when_engine_row_has_no_credential(
        self, vision_engine, monkeypatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
        value = engine_credential(
            engine_name=vision_engine.name,
            key="api_key",
            env_fallback="ANTHROPIC_API_KEY",
        )
        assert value == "from-env"

    def test_empty_db_value_falls_through_to_env(self, vision_engine, monkeypatch) -> None:
        # Super-admin cleared the field — not "configured", fall through.
        vision_engine.credentials = {"api_key": ""}
        vision_engine.save(update_fields=["credentials"])
        monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")

        value = engine_credential(
            engine_name=vision_engine.name,
            key="api_key",
            env_fallback="ANTHROPIC_API_KEY",
        )
        assert value == "from-env"

    def test_falls_back_to_env_when_engine_row_missing(self, db, monkeypatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
        # No matching Engine row — resolver still finds the env value.
        value = engine_credential(
            engine_name="never-registered",
            key="api_key",
            env_fallback="ANTHROPIC_API_KEY",
        )
        assert value == "from-env"

    def test_returns_none_when_nothing_resolves(self, vision_engine, monkeypatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert (
            engine_credential(
                engine_name=vision_engine.name,
                key="api_key",
                env_fallback="ANTHROPIC_API_KEY",
            )
            is None
        )

    def test_require_raises_engine_unavailable_when_unconfigured(
        self, vision_engine, monkeypatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(EngineUnavailable, match="api_key"):
            require_engine_credential(
                engine_name=vision_engine.name,
                key="api_key",
                env_fallback="ANTHROPIC_API_KEY",
            )

    def test_per_engine_credentials_are_isolated(self, db, monkeypatch) -> None:
        """Two adapter rows on the same vendor can carry different keys.

        ENGINE_REGISTRY.md anticipates customers maintaining separate
        Anthropic accounts per use case (vision vs structure). The
        resolver must look up by exact engine name, not vendor.
        """
        Engine.objects.update_or_create(
            name="anthropic-claude-sonnet-vision",
            defaults={
                "vendor": "anthropic",
                "capability": "vision_extract",
                "credentials": {"api_key": "vision-key"},
            },
        )
        Engine.objects.update_or_create(
            name="anthropic-claude-sonnet-structure",
            defaults={
                "vendor": "anthropic",
                "capability": "field_structure",
                "credentials": {"api_key": "structure-key"},
            },
        )
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        assert (
            engine_credential(engine_name="anthropic-claude-sonnet-vision", key="api_key")
            == "vision-key"
        )
        assert (
            engine_credential(engine_name="anthropic-claude-sonnet-structure", key="api_key")
            == "structure-key"
        )


@pytest.mark.django_db
class TestClaudeAdapterReadsResolver:
    """The Claude adapter reads via the resolver, not directly from os.environ.

    A regression here would mean rotating a key in the DB has no effect
    until restart, defeating the point of moving credentials to the DB.
    """

    def test_adapter_picks_db_credential_over_env(self, vision_engine, monkeypatch) -> None:
        from apps.extraction.adapters.claude_adapter import _client

        vision_engine.credentials = {"api_key": "from-db"}
        vision_engine.save(update_fields=["credentials"])
        monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")

        # We don't actually want to instantiate Anthropic — patch it out
        # and capture the api_key passed in.
        captured: dict[str, str] = {}

        class _StubAnthropic:
            def __init__(self, api_key: str) -> None:
                captured["api_key"] = api_key

        monkeypatch.setattr(
            "apps.extraction.adapters.claude_adapter.Anthropic",
            _StubAnthropic,
            raising=False,
        )
        # The adapter uses a deferred import; patch that path too.
        import sys

        sys.modules.setdefault("anthropic", type(sys)("anthropic")).Anthropic = _StubAnthropic  # type: ignore[attr-defined]

        _client(engine_name=vision_engine.name)
        assert captured["api_key"] == "from-db"

    def test_adapter_raises_engine_unavailable_when_unconfigured(
        self, vision_engine, monkeypatch
    ) -> None:
        from apps.extraction.adapters.claude_adapter import _client

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(EngineUnavailable):
            _client(engine_name=vision_engine.name)
