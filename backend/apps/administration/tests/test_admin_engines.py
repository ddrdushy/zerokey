"""Tests for the platform-staff engine credentials surface (Slice 36)."""

from __future__ import annotations

import json

import pytest
from django.test import Client

from apps.audit.models import AuditEvent
from apps.extraction.models import Engine
from apps.identity.models import Role, User


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def staff_user(seeded) -> User:
    return User.objects.create_user(
        email="staff@symprio.com", password="x", is_staff=True
    )


@pytest.fixture
def some_engines(db) -> list[Engine]:
    """Seeded engines exist via the data migration; we patch credentials."""
    e1, _ = Engine.objects.update_or_create(
        name="anthropic-claude-sonnet-structure",
        defaults={
            "vendor": "anthropic",
            "capability": "field_structure",
            "model_identifier": "claude-sonnet-4-6",
            "credentials": {"api_key": "sk-secret"},
            "cost_per_call_micros": 4_000,
            "description": "Anthropic structure",
            "status": "active",
        },
    )
    e2, _ = Engine.objects.update_or_create(
        name="ollama-structure",
        defaults={
            "vendor": "ollama",
            "capability": "field_structure",
            "model_identifier": "gpt-oss:120b",
            "credentials": {
                "api_key": "ollama-secret",
                "host": "https://ollama.com",
                "model": "gpt-oss:120b",
            },
            "status": "active",
        },
    )
    return [e1, e2]


@pytest.mark.django_db
class TestAdminListEngines:
    def test_unauthenticated_rejected(self, some_engines) -> None:
        response = Client().get("/api/v1/admin/engines/")
        assert response.status_code in (401, 403)

    def test_customer_403(self, some_engines, seeded) -> None:
        user = User.objects.create_user(email="cust@x", password="x")
        client = Client()
        client.force_login(user)
        response = client.get("/api/v1/admin/engines/")
        assert response.status_code == 403

    def test_staff_lists_engines_with_redacted_credentials(
        self, staff_user, some_engines
    ) -> None:
        client = Client()
        client.force_login(staff_user)
        response = client.get("/api/v1/admin/engines/")
        assert response.status_code == 200
        results = response.json()["results"]
        names = {e["name"] for e in results}
        assert "anthropic-claude-sonnet-structure" in names
        assert "ollama-structure" in names

        # credential_keys is a {key: bool} map — values are NEVER returned.
        ollama = next(e for e in results if e["name"] == "ollama-structure")
        assert ollama["credential_keys"] == {
            "api_key": True,
            "host": True,
            "model": True,
        }
        # Make sure plaintext credentials don't slip through anywhere.
        body_text = json.dumps(results)
        assert "ollama-secret" not in body_text
        assert "sk-secret" not in body_text


@pytest.mark.django_db
class TestAdminUpdateEngine:
    def test_update_status(self, staff_user, some_engines) -> None:
        engine = some_engines[1]
        client = Client()
        client.force_login(staff_user)
        response = client.patch(
            f"/api/v1/admin/engines/{engine.id}/",
            data={"fields": {"status": "degraded"}},
            content_type="application/json",
        )
        assert response.status_code == 200
        engine.refresh_from_db()
        assert engine.status == "degraded"

        # Audit event records the change with field name only — no values.
        event = (
            AuditEvent.objects.filter(action_type="admin.engine_updated")
            .order_by("-sequence")
            .first()
        )
        assert event.payload["fields_changed"] == ["status"]
        assert event.payload["engine_name"] == engine.name

    def test_update_credentials_set_new_key(
        self, staff_user, some_engines
    ) -> None:
        engine = some_engines[0]  # Anthropic, only api_key set today
        client = Client()
        client.force_login(staff_user)
        response = client.patch(
            f"/api/v1/admin/engines/{engine.id}/",
            data={"credentials": {"api_key": "sk-rotated"}},
            content_type="application/json",
        )
        assert response.status_code == 200
        engine.refresh_from_db()
        # Slice 55: credentials are encrypted at rest.
        from apps.administration.crypto import decrypt_value

        assert decrypt_value(engine.credentials["api_key"]) == "sk-rotated"

        # Audit lists the credential key NAME, not the value.
        event = (
            AuditEvent.objects.filter(action_type="admin.engine_updated")
            .order_by("-sequence")
            .first()
        )
        assert event.payload["credential_keys_changed"] == ["api_key"]
        # PII-clean: the rotated value never appears in the audit payload.
        assert "sk-rotated" not in json.dumps(event.payload)

    def test_clear_credential_with_empty_string(
        self, staff_user, some_engines
    ) -> None:
        engine = some_engines[1]  # Ollama, has 3 credentials
        client = Client()
        client.force_login(staff_user)
        response = client.patch(
            f"/api/v1/admin/engines/{engine.id}/",
            data={"credentials": {"host": ""}},
            content_type="application/json",
        )
        assert response.status_code == 200
        engine.refresh_from_db()
        assert "host" not in engine.credentials
        # Other keys untouched. (Slice 55: stored ciphertext.)
        from apps.administration.crypto import decrypt_value

        assert decrypt_value(engine.credentials["api_key"]) == "ollama-secret"
        assert decrypt_value(engine.credentials["model"]) == "gpt-oss:120b"

    def test_reject_non_editable_field(self, staff_user, some_engines) -> None:
        engine = some_engines[0]
        client = Client()
        client.force_login(staff_user)
        response = client.patch(
            f"/api/v1/admin/engines/{engine.id}/",
            data={"fields": {"name": "renamed-engine"}},
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "name" in response.json()["detail"]

    def test_reject_invalid_status(self, staff_user, some_engines) -> None:
        engine = some_engines[0]
        client = Client()
        client.force_login(staff_user)
        response = client.patch(
            f"/api/v1/admin/engines/{engine.id}/",
            data={"fields": {"status": "garbage"}},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_unknown_engine_returns_404(self, staff_user) -> None:
        client = Client()
        client.force_login(staff_user)
        response = client.patch(
            "/api/v1/admin/engines/00000000-0000-0000-0000-000000000000/",
            data={"fields": {"status": "active"}},
            content_type="application/json",
        )
        assert response.status_code == 404

    def test_no_op_does_not_create_audit_event(
        self, staff_user, some_engines
    ) -> None:
        engine = some_engines[0]
        client = Client()
        client.force_login(staff_user)
        before = AuditEvent.objects.filter(
            action_type="admin.engine_updated"
        ).count()
        # Send the SAME api_key value already on the engine.
        response = client.patch(
            f"/api/v1/admin/engines/{engine.id}/",
            data={"credentials": {"api_key": "sk-secret"}},
            content_type="application/json",
        )
        assert response.status_code == 200
        after = AuditEvent.objects.filter(
            action_type="admin.engine_updated"
        ).count()
        assert before == after  # no-op produced no audit row

    def test_customer_cannot_update(self, some_engines, seeded) -> None:
        engine = some_engines[0]
        user = User.objects.create_user(email="cust@x", password="x")
        client = Client()
        client.force_login(user)
        response = client.patch(
            f"/api/v1/admin/engines/{engine.id}/",
            data={"fields": {"status": "degraded"}},
            content_type="application/json",
        )
        assert response.status_code == 403
        engine.refresh_from_db()
        # And the field didn't change.
        assert engine.status == "active"
