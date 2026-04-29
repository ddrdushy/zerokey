"""Tests for the SystemSetting resolver and upsert service.

The resolver is the seam every platform-wide integration (LHDN, Stripe)
goes through, replacing direct ``os.environ`` reads inside adapters. The
contract that must hold:

  - DB takes precedence over env (so super-admin edits beat the .env file).
  - Empty DB values fall through to env (so clearing a field via the UI
    does not silently leave the system unconfigured).
  - Missing-everywhere returns ``None`` for ``system_setting`` and raises
    ``SettingNotConfigured`` for ``require_system_setting``.
  - ``upsert_system_setting`` writes an audit event whose payload lists
    affected key names but never the values themselves.
"""

from __future__ import annotations

import pytest

from apps.administration.models import SystemSetting
from apps.administration.services import (
    SettingNotConfigured,
    require_system_setting,
    system_setting,
    upsert_system_setting,
)
from apps.audit.models import AuditEvent


@pytest.mark.django_db
class TestSystemSettingResolver:
    def test_db_value_takes_precedence_over_env(self, monkeypatch) -> None:
        SystemSetting.objects.create(namespace="lhdn", values={"client_id": "from-db"})
        monkeypatch.setenv("LHDN_CLIENT_ID", "from-env")

        assert (
            system_setting(namespace="lhdn", key="client_id", env_fallback="LHDN_CLIENT_ID")
            == "from-db"
        )

    def test_falls_back_to_env_when_db_row_missing(self, monkeypatch) -> None:
        monkeypatch.setenv("LHDN_CLIENT_ID", "from-env")
        assert (
            system_setting(namespace="lhdn", key="client_id", env_fallback="LHDN_CLIENT_ID")
            == "from-env"
        )

    def test_falls_back_to_env_when_db_value_is_empty_string(self, monkeypatch) -> None:
        # Editor cleared the field — should not be treated as "configured".
        SystemSetting.objects.create(namespace="lhdn", values={"client_id": ""})
        monkeypatch.setenv("LHDN_CLIENT_ID", "from-env")

        assert (
            system_setting(namespace="lhdn", key="client_id", env_fallback="LHDN_CLIENT_ID")
            == "from-env"
        )

    def test_returns_default_when_neither_db_nor_env_has_value(self, monkeypatch) -> None:
        monkeypatch.delenv("LHDN_CLIENT_ID", raising=False)
        assert (
            system_setting(
                namespace="lhdn",
                key="client_id",
                env_fallback="LHDN_CLIENT_ID",
                default="anonymous",
            )
            == "anonymous"
        )

    def test_returns_none_when_nothing_resolves(self, monkeypatch) -> None:
        monkeypatch.delenv("LHDN_CLIENT_ID", raising=False)
        assert system_setting(namespace="lhdn", key="client_id") is None

    def test_require_raises_when_not_configured_anywhere(self, monkeypatch) -> None:
        monkeypatch.delenv("LHDN_CLIENT_ID", raising=False)
        with pytest.raises(SettingNotConfigured, match=r"lhdn\.client_id"):
            require_system_setting(
                namespace="lhdn", key="client_id", env_fallback="LHDN_CLIENT_ID"
            )


@pytest.mark.django_db
class TestUpsertSystemSetting:
    def test_create_then_update_keeps_one_row(self) -> None:
        upsert_system_setting(
            namespace="lhdn",
            values={"client_id": "first", "client_secret": "first-secret"},
        )
        upsert_system_setting(
            namespace="lhdn",
            values={"client_id": "second", "client_secret": "second-secret"},
        )

        rows = SystemSetting.objects.filter(namespace="lhdn")
        assert rows.count() == 1
        # Slice 55: values are encrypted at rest. Decrypt to compare.
        from apps.administration.crypto import decrypt_dict_values

        assert decrypt_dict_values(rows.first().values) == {
            "client_id": "second",
            "client_secret": "second-secret",
        }

    def test_upsert_emits_audit_event_with_keys_but_not_values(self) -> None:
        upsert_system_setting(
            namespace="stripe",
            values={"secret_key": "sk_test_super_secret", "webhook_secret": "whsec_xyz"},
        )

        event = AuditEvent.objects.get(action_type="administration.system_setting.updated")
        assert event.payload["namespace"] == "stripe"
        assert sorted(event.payload["keys"]) == ["secret_key", "webhook_secret"]
        # Values must NEVER enter the audit log.
        serialized = str(event.payload)
        assert "sk_test_super_secret" not in serialized
        assert "whsec_xyz" not in serialized
