"""Tests for per-org integration credentials (Slice 57)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest
from django.test import Client

from apps.audit.models import AuditEvent
from apps.identity.integrations import (
    INTEGRATION_SCHEMAS,
    IntegrationConfigError,
    list_integrations_for_org,
    set_active_environment,
    upsert_credentials,
)
from apps.identity.integrations import test_connection as run_test_connection
from apps.identity.models import (
    Organization,
    OrganizationIntegration,
    OrganizationMembership,
    Role,
    User,
)


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org_owner(seeded) -> tuple[Organization, User]:
    org = Organization.objects.create(
        legal_name="Acme",
        tin="C10000000001",
        contact_email="o@acme.example",
    )
    user = User.objects.create_user(email="owner@acme.example", password="long-enough-password")
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name="owner")
    )
    return org, user


@pytest.fixture
def authed_owner(org_owner) -> tuple[Client, Organization, User]:
    org, user = org_owner
    client = Client()
    client.force_login(user)
    session = client.session
    session["organization_id"] = str(org.id)
    session.save()
    return client, org, user


# --- Schema sanity ---


def test_lhdn_in_schema_registry() -> None:
    keys = {s["key"] for s in INTEGRATION_SCHEMAS}
    assert "lhdn_myinvois" in keys


def test_lhdn_schema_has_required_fields() -> None:
    schema = next(s for s in INTEGRATION_SCHEMAS if s["key"] == "lhdn_myinvois")
    field_keys = {f["key"] for f in schema["fields"]}
    assert {"client_id", "client_secret", "base_url", "tin"} <= field_keys


# --- list_integrations_for_org ---


@pytest.mark.django_db
class TestListIntegrations:
    def test_no_rows_returns_default_shape(self, org_owner) -> None:
        org, _ = org_owner
        result = list_integrations_for_org(organization_id=org.id)
        # Even with no row, every registered integration appears so
        # the UI can render the empty form.
        assert any(r["integration_key"] == "lhdn_myinvois" for r in result)
        lhdn = next(r for r in result if r["integration_key"] == "lhdn_myinvois")
        assert lhdn["configured"] is False
        assert lhdn["active_environment"] == "sandbox"
        assert lhdn["sandbox"]["values"] == {}
        assert lhdn["sandbox"]["credential_present"] == {}


# --- upsert_credentials ---


@pytest.mark.django_db
class TestUpsertCredentials:
    def test_creates_row_with_defaults_seeded(self, org_owner) -> None:
        org, user = org_owner
        result = upsert_credentials(
            organization_id=org.id,
            integration_key="lhdn_myinvois",
            environment="sandbox",
            field_updates={
                "client_id": "abc",
                "client_secret": "xyz",
                "tin": "C9999999999",
            },
            actor_user_id=user.id,
        )
        assert result["sandbox"]["credential_present"]["client_id"] is True
        assert result["sandbox"]["credential_present"]["client_secret"] is True
        # Default sandbox base_url seeded — it's a config field so the
        # plaintext value is visible on the readout.
        assert result["sandbox"]["values"]["base_url"].startswith("https://preprod-api.myinvois")

    def test_credentials_encrypted_at_rest(self, org_owner) -> None:
        org, user = org_owner
        upsert_credentials(
            organization_id=org.id,
            integration_key="lhdn_myinvois",
            environment="sandbox",
            field_updates={"client_secret": "highly-distinctive-secret-xyz"},
            actor_user_id=user.id,
        )
        row = OrganizationIntegration.objects.get(
            organization_id=org.id, integration_key="lhdn_myinvois"
        )
        # Raw column read: value must NOT contain the plaintext.
        stored = row.sandbox_credentials["client_secret"]
        assert "highly-distinctive-secret-xyz" not in stored
        assert stored.startswith("enc1:")

    def test_audit_records_field_names_only(self, org_owner) -> None:
        org, user = org_owner
        upsert_credentials(
            organization_id=org.id,
            integration_key="lhdn_myinvois",
            environment="production",
            field_updates={"client_secret": "production-secret-aaa"},
            actor_user_id=user.id,
        )
        event = (
            AuditEvent.objects.filter(action_type="identity.integration.credentials_updated")
            .order_by("-sequence")
            .first()
        )
        assert event is not None
        assert event.payload["fields_changed"] == ["client_secret"]
        assert event.payload["environment"] == "production"
        # Literal secret value never enters the audit chain.
        assert "production-secret-aaa" not in json.dumps(event.payload)

    def test_unknown_field_rejected(self, org_owner) -> None:
        org, user = org_owner
        with pytest.raises(IntegrationConfigError, match="Unknown fields"):
            upsert_credentials(
                organization_id=org.id,
                integration_key="lhdn_myinvois",
                environment="sandbox",
                field_updates={"super_secret_master_key": "x"},
                actor_user_id=user.id,
            )

    def test_unknown_integration_rejected(self, org_owner) -> None:
        org, user = org_owner
        with pytest.raises(IntegrationConfigError, match="Unknown integration"):
            upsert_credentials(
                organization_id=org.id,
                integration_key="not_a_real_integration",
                environment="sandbox",
                field_updates={"x": "y"},
                actor_user_id=user.id,
            )

    def test_invalid_environment_rejected(self, org_owner) -> None:
        org, user = org_owner
        with pytest.raises(IntegrationConfigError, match="environment"):
            upsert_credentials(
                organization_id=org.id,
                integration_key="lhdn_myinvois",
                environment="staging",
                field_updates={"client_id": "x"},
                actor_user_id=user.id,
            )

    def test_empty_value_clears_key(self, org_owner) -> None:
        org, user = org_owner
        upsert_credentials(
            organization_id=org.id,
            integration_key="lhdn_myinvois",
            environment="sandbox",
            field_updates={"client_id": "to-be-cleared"},
            actor_user_id=user.id,
        )
        upsert_credentials(
            organization_id=org.id,
            integration_key="lhdn_myinvois",
            environment="sandbox",
            field_updates={"client_id": ""},
            actor_user_id=user.id,
        )
        result = list_integrations_for_org(organization_id=org.id)
        lhdn = next(r for r in result if r["integration_key"] == "lhdn_myinvois")
        assert lhdn["sandbox"]["credential_present"]["client_id"] is False


# --- set_active_environment ---


@pytest.mark.django_db
class TestSetActiveEnvironment:
    def test_flips_environment(self, org_owner) -> None:
        org, user = org_owner
        upsert_credentials(
            organization_id=org.id,
            integration_key="lhdn_myinvois",
            environment="sandbox",
            field_updates={"client_id": "x"},
            actor_user_id=user.id,
        )
        result = set_active_environment(
            organization_id=org.id,
            integration_key="lhdn_myinvois",
            environment="production",
            actor_user_id=user.id,
            reason="going live after pilot",
        )
        assert result["active_environment"] == "production"

    def test_audit_records_transition(self, org_owner) -> None:
        org, user = org_owner
        # Seed a row at the default (sandbox) by saving credentials.
        upsert_credentials(
            organization_id=org.id,
            integration_key="lhdn_myinvois",
            environment="sandbox",
            field_updates={"client_id": "abc"},
            actor_user_id=user.id,
        )
        # Now flip to production: this is the audited transition.
        set_active_environment(
            organization_id=org.id,
            integration_key="lhdn_myinvois",
            environment="production",
            actor_user_id=user.id,
            reason="going live",
        )
        event = (
            AuditEvent.objects.filter(action_type="identity.integration.environment_switched")
            .order_by("-sequence")
            .first()
        )
        assert event is not None
        assert event.payload["from_environment"] == "sandbox"
        assert event.payload["to_environment"] == "production"

    def test_no_op_skips_audit(self, org_owner) -> None:
        org, user = org_owner
        # Default is sandbox — re-setting to sandbox is a no-op.
        set_active_environment(
            organization_id=org.id,
            integration_key="lhdn_myinvois",
            environment="sandbox",
            actor_user_id=user.id,
        )
        # Now flip to production then back: should produce 2 events
        set_active_environment(
            organization_id=org.id,
            integration_key="lhdn_myinvois",
            environment="production",
            actor_user_id=user.id,
        )
        before = AuditEvent.objects.filter(
            action_type="identity.integration.environment_switched"
        ).count()
        # Idempotent re-set of production:
        set_active_environment(
            organization_id=org.id,
            integration_key="lhdn_myinvois",
            environment="production",
            actor_user_id=user.id,
        )
        after = AuditEvent.objects.filter(
            action_type="identity.integration.environment_switched"
        ).count()
        assert before == after


# --- test_connection ---


def _mock_head(status_code: int = 200) -> MagicMock:
    """Pre-Slice-58 helper, retained for compatibility."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    return resp


def _mock_oauth_response(status_code: int = 200, body: dict | None = None) -> MagicMock:
    """Slice 58: tester now hits /connect/token via httpx.post."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json = MagicMock(return_value=body or {"access_token": "test-token", "expires_in": 3600})
    return resp


@pytest.mark.django_db
class TestTestConnection:
    def _save_creds(self, org_owner) -> None:
        org, user = org_owner
        upsert_credentials(
            organization_id=org.id,
            integration_key="lhdn_myinvois",
            environment="sandbox",
            field_updates={
                "client_id": "abc",
                "client_secret": "xyz",
                "tin": "C9999999999",
                "base_url": "https://preprod-api.myinvois.hasil.gov.my",
            },
            actor_user_id=user.id,
        )

    def test_no_creds_yet_400(self, org_owner) -> None:
        org, user = org_owner
        with pytest.raises(IntegrationConfigError, match="No credentials"):
            run_test_connection(
                organization_id=org.id,
                integration_key="lhdn_myinvois",
                environment="sandbox",
                actor_user_id=user.id,
            )

    def test_connection_failure_returns_failure_outcome(self, org_owner) -> None:
        """Slice 58: tester now POSTs OAuth2 — connect-failure path."""
        org, user = org_owner
        upsert_credentials(
            organization_id=org.id,
            integration_key="lhdn_myinvois",
            environment="sandbox",
            field_updates={
                "client_id": "x",
                "client_secret": "y",
                "tin": "z",
                "base_url": "https://this-host-definitely-does-not-exist.zerokey.invalid",
            },
            actor_user_id=user.id,
        )
        with patch(
            "apps.identity.integrations.httpx.post",
            side_effect=httpx.ConnectError("DNS lookup failed"),
        ):
            outcome = run_test_connection(
                organization_id=org.id,
                integration_key="lhdn_myinvois",
                environment="sandbox",
                actor_user_id=user.id,
            )
        assert outcome.ok is False
        assert "ConnectError" in outcome.detail

    def test_success_records_outcome_on_row(self, org_owner) -> None:
        """Slice 58: 200 + access_token in body == success."""
        self._save_creds(org_owner)
        org, user = org_owner
        with patch(
            "apps.identity.integrations.httpx.post",
            return_value=_mock_oauth_response(200),
        ):
            outcome = run_test_connection(
                organization_id=org.id,
                integration_key="lhdn_myinvois",
                environment="sandbox",
                actor_user_id=user.id,
            )
        assert outcome.ok is True
        row = OrganizationIntegration.objects.get(
            organization_id=org.id, integration_key="lhdn_myinvois"
        )
        assert row.last_test_sandbox_ok is True
        assert row.last_test_sandbox_at is not None

    def test_oauth_invalid_client_is_failure(self, org_owner) -> None:
        """Slice 58: 401 with OAuth2 error_code surfaces in detail."""
        self._save_creds(org_owner)
        org, user = org_owner
        with patch(
            "apps.identity.integrations.httpx.post",
            return_value=_mock_oauth_response(401, {"error": "invalid_client"}),
        ):
            outcome = run_test_connection(
                organization_id=org.id,
                integration_key="lhdn_myinvois",
                environment="sandbox",
                actor_user_id=user.id,
            )
        assert outcome.ok is False
        assert "invalid_client" in outcome.detail

    def test_missing_credentials_warns(self, org_owner) -> None:
        """No HTTP call — credentials check fires first."""
        org, user = org_owner
        # Save only base_url, no client_id / client_secret.
        upsert_credentials(
            organization_id=org.id,
            integration_key="lhdn_myinvois",
            environment="sandbox",
            field_updates={"base_url": "https://preprod-api.myinvois.hasil.gov.my"},
            actor_user_id=user.id,
        )
        with patch("apps.identity.integrations.httpx.post") as posted:
            outcome = run_test_connection(
                organization_id=org.id,
                integration_key="lhdn_myinvois",
                environment="sandbox",
                actor_user_id=user.id,
            )
        assert outcome.ok is False
        assert "missing" in outcome.detail.lower()
        # Bail-out is local — no HTTP call is made when creds are missing.
        posted.assert_not_called()


# --- Endpoints ---


@pytest.mark.django_db
class TestEndpoints:
    def test_list_returns_lhdn_card(self, authed_owner) -> None:
        client, _, _ = authed_owner
        response = client.get("/api/v1/identity/organization/integrations/")
        assert response.status_code == 200
        results = response.json()["results"]
        assert any(r["integration_key"] == "lhdn_myinvois" for r in results)

    def test_non_admin_cannot_patch(self, seeded) -> None:
        org = Organization.objects.create(legal_name="X", tin="C10000000002", contact_email="o@x")
        viewer = User.objects.create_user(email="viewer@x", password="long-enough-password")
        OrganizationMembership.objects.create(
            user=viewer, organization=org, role=Role.objects.get(name="viewer")
        )
        client = Client()
        client.force_login(viewer)
        session = client.session
        session["organization_id"] = str(org.id)
        session.save()
        response = client.patch(
            "/api/v1/identity/organization/integrations/lhdn_myinvois/credentials/",
            data=json.dumps({"environment": "sandbox", "fields": {"client_id": "x"}}),
            content_type="application/json",
        )
        assert response.status_code == 403

    def test_owner_can_patch(self, authed_owner) -> None:
        client, _, _ = authed_owner
        response = client.patch(
            "/api/v1/identity/organization/integrations/lhdn_myinvois/credentials/",
            data=json.dumps(
                {
                    "environment": "sandbox",
                    "fields": {
                        "client_id": "abc",
                        "tin": "C9999999999",
                    },
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["sandbox"]["credential_present"]["client_id"] is True

    def test_switch_environment_endpoint(self, authed_owner) -> None:
        client, _, _ = authed_owner
        response = client.patch(
            "/api/v1/identity/organization/integrations/lhdn_myinvois/active-environment/",
            data=json.dumps({"environment": "production", "reason": "going live"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["active_environment"] == "production"

    def test_test_endpoint_invokes_tester(self, authed_owner) -> None:
        client, org, user = authed_owner
        upsert_credentials(
            organization_id=org.id,
            integration_key="lhdn_myinvois",
            environment="sandbox",
            field_updates={
                "client_id": "x",
                "client_secret": "y",
                "tin": "z",
                "base_url": "https://preprod-api.myinvois.hasil.gov.my",
            },
            actor_user_id=user.id,
        )
        with patch(
            "apps.identity.integrations.httpx.post",
            return_value=_mock_oauth_response(200),
        ):
            response = client.post(
                "/api/v1/identity/organization/integrations/lhdn_myinvois/test/",
                data=json.dumps({"environment": "sandbox"}),
                content_type="application/json",
            )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["duration_ms"] >= 0
