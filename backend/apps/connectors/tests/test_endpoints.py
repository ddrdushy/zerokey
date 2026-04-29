"""Endpoint tests for the connectors API surface (Slice 77)."""

from __future__ import annotations

import json
import uuid
from io import BytesIO

import pytest
from django.test import Client

from apps.connectors.models import (
    IntegrationConfig,
    MasterFieldConflict,
    MasterFieldLock,
    MasterType,
    SyncProposal,
)
from apps.enrichment.models import CustomerMaster
from apps.identity.models import (
    Organization,
    OrganizationMembership,
    Role,
    User,
)


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org(seeded) -> Organization:
    return Organization.objects.create(
        legal_name="Endpoint Test Sdn Bhd",
        tin="C5555555555",
        contact_email="ops@endpoint.example",
    )


@pytest.fixture
def owner_session(org) -> tuple[Client, User]:
    user = User.objects.create_user(
        email="owner@endpoint.example", password="long-enough-password"
    )
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name="owner")
    )
    client = Client()
    client.force_login(user)
    session = client.session
    session["organization_id"] = str(org.id)
    session.save()
    return client, user


@pytest.fixture
def viewer_session(org) -> tuple[Client, User]:
    user = User.objects.create_user(
        email="viewer@endpoint.example", password="long-enough-password"
    )
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name="viewer")
    )
    client = Client()
    client.force_login(user)
    session = client.session
    session["organization_id"] = str(org.id)
    session.save()
    return client, user


CSV_FIXTURE = b"""Company Name,Tax ID,Address
Acme Sdn Bhd,C9999999999,Level 5 KL
Globex Bhd,C8888888888,Level 10 PJ
"""

MAPPING = {
    "Company Name": "legal_name",
    "Tax ID": "tin",
    "Address": "address",
}


# =============================================================================
# Configs
# =============================================================================


@pytest.mark.django_db
class TestConfigs:
    def test_create_config(self, owner_session) -> None:
        client, _ = owner_session
        response = client.post(
            "/api/v1/connectors/configs/",
            data=json.dumps({"connector_type": "csv"}),
            content_type="application/json",
        )
        assert response.status_code == 201
        body = response.json()
        assert body["connector_type"] == "csv"
        assert body["is_active"] is True

    def test_viewer_cannot_create(self, viewer_session) -> None:
        client, _ = viewer_session
        response = client.post(
            "/api/v1/connectors/configs/",
            data=json.dumps({"connector_type": "csv"}),
            content_type="application/json",
        )
        assert response.status_code == 403

    def test_create_returns_existing_when_active(
        self, owner_session
    ) -> None:
        client, _ = owner_session
        first = client.post(
            "/api/v1/connectors/configs/",
            data=json.dumps({"connector_type": "csv"}),
            content_type="application/json",
        )
        second = client.post(
            "/api/v1/connectors/configs/",
            data=json.dumps({"connector_type": "csv"}),
            content_type="application/json",
        )
        # Returns existing — same id.
        assert first.json()["id"] == second.json()["id"]

    def test_unknown_connector_type_400(self, owner_session) -> None:
        client, _ = owner_session
        response = client.post(
            "/api/v1/connectors/configs/",
            data=json.dumps({"connector_type": "fake_connector"}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_list_configs(self, org, owner_session) -> None:
        IntegrationConfig.objects.create(
            organization=org,
            connector_type=IntegrationConfig.ConnectorType.CSV,
        )
        IntegrationConfig.objects.create(
            organization=org,
            connector_type=IntegrationConfig.ConnectorType.XERO,
        )
        client, _ = owner_session
        response = client.get("/api/v1/connectors/configs/")
        assert response.status_code == 200
        results = response.json()["results"]
        assert len(results) == 2

    def test_delete_config_soft_deletes(self, org, owner_session) -> None:
        config = IntegrationConfig.objects.create(
            organization=org,
            connector_type=IntegrationConfig.ConnectorType.CSV,
        )
        client, _ = owner_session
        response = client.delete(
            f"/api/v1/connectors/configs/{config.id}/"
        )
        assert response.status_code == 200
        config.refresh_from_db()
        assert config.deleted_at is not None


# =============================================================================
# CSV upload + propose
# =============================================================================


@pytest.mark.django_db
class TestSyncCsv:
    def test_upload_creates_proposal(self, org, owner_session) -> None:
        config = IntegrationConfig.objects.create(
            organization=org,
            connector_type=IntegrationConfig.ConnectorType.CSV,
        )
        client, _ = owner_session
        response = client.post(
            f"/api/v1/connectors/configs/{config.id}/sync-csv/",
            data={
                "file": BytesIO(CSV_FIXTURE),
                "column_mapping": json.dumps(MAPPING),
            },
        )
        assert response.status_code == 201, response.json()
        body = response.json()
        assert body["status"] == "proposed"
        assert len(body["diff"]["customers"]["would_add"]) == 2

    def test_upload_against_non_csv_connector_400(
        self, org, owner_session
    ) -> None:
        config = IntegrationConfig.objects.create(
            organization=org,
            connector_type=IntegrationConfig.ConnectorType.XERO,
        )
        client, _ = owner_session
        response = client.post(
            f"/api/v1/connectors/configs/{config.id}/sync-csv/",
            data={
                "file": BytesIO(CSV_FIXTURE),
                "column_mapping": json.dumps(MAPPING),
            },
        )
        assert response.status_code == 400

    def test_missing_file_400(self, org, owner_session) -> None:
        config = IntegrationConfig.objects.create(
            organization=org,
            connector_type=IntegrationConfig.ConnectorType.CSV,
        )
        client, _ = owner_session
        response = client.post(
            f"/api/v1/connectors/configs/{config.id}/sync-csv/",
            data={"column_mapping": json.dumps(MAPPING)},
        )
        assert response.status_code == 400

    def test_invalid_column_mapping_json_400(self, org, owner_session) -> None:
        config = IntegrationConfig.objects.create(
            organization=org,
            connector_type=IntegrationConfig.ConnectorType.CSV,
        )
        client, _ = owner_session
        response = client.post(
            f"/api/v1/connectors/configs/{config.id}/sync-csv/",
            data={
                "file": BytesIO(CSV_FIXTURE),
                "column_mapping": "{not valid json",
            },
        )
        assert response.status_code == 400


# =============================================================================
# Apply / Revert
# =============================================================================


@pytest.mark.django_db
class TestApplyRevert:
    def _propose(self, org, owner_session) -> SyncProposal:
        config = IntegrationConfig.objects.create(
            organization=org,
            connector_type=IntegrationConfig.ConnectorType.CSV,
        )
        client, _ = owner_session
        response = client.post(
            f"/api/v1/connectors/configs/{config.id}/sync-csv/",
            data={
                "file": BytesIO(CSV_FIXTURE),
                "column_mapping": json.dumps(MAPPING),
            },
        )
        assert response.status_code == 201
        return SyncProposal.objects.get(id=response.json()["id"])

    def test_apply_creates_masters(self, org, owner_session) -> None:
        proposal = self._propose(org, owner_session)
        client, _ = owner_session
        response = client.post(
            f"/api/v1/connectors/proposals/{proposal.id}/apply/"
        )
        assert response.status_code == 200
        assert response.json()["status"] == "applied"
        # Two customer masters now exist.
        assert CustomerMaster.objects.filter(organization=org).count() == 2

    def test_revert_undoes(self, org, owner_session) -> None:
        proposal = self._propose(org, owner_session)
        client, _ = owner_session
        client.post(f"/api/v1/connectors/proposals/{proposal.id}/apply/")
        response = client.post(
            f"/api/v1/connectors/proposals/{proposal.id}/revert/",
            data=json.dumps({"reason": "operator error"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["status"] == "reverted"
        assert CustomerMaster.objects.filter(organization=org).count() == 0

    def test_viewer_cannot_apply(
        self, org, owner_session, viewer_session
    ) -> None:
        proposal = self._propose(org, owner_session)
        client, _ = viewer_session
        response = client.post(
            f"/api/v1/connectors/proposals/{proposal.id}/apply/"
        )
        assert response.status_code == 403


# =============================================================================
# Conflict queue
# =============================================================================


@pytest.mark.django_db
class TestConflicts:
    def test_list_default_open_only(self, org, owner_session) -> None:
        # Pre-stage a master + a sync that conflicts.
        config = IntegrationConfig.objects.create(
            organization=org,
            connector_type=IntegrationConfig.ConnectorType.CSV,
        )
        CustomerMaster.objects.create(
            organization=org,
            legal_name="Acme Sdn Bhd",  # match CSV's value exactly
            tin="C9999999999",
            address="Old address",
            field_provenance={
                "legal_name": {"source": "extracted"},
                "tin": {"source": "extracted"},
                "address": {"source": "manual"},
            },
        )
        client, _ = owner_session
        client.post(
            f"/api/v1/connectors/configs/{config.id}/sync-csv/",
            data={
                "file": BytesIO(CSV_FIXTURE),
                "column_mapping": json.dumps(MAPPING),
            },
        )
        response = client.get("/api/v1/connectors/conflicts/")
        assert response.status_code == 200
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["field_name"] == "address"
        assert results[0]["is_open"] is True

    def test_resolve_take_incoming(self, org, owner_session) -> None:
        config = IntegrationConfig.objects.create(
            organization=org,
            connector_type=IntegrationConfig.ConnectorType.CSV,
        )
        master = CustomerMaster.objects.create(
            organization=org,
            legal_name="Acme",
            tin="C9999999999",
            address="Old address",
            field_provenance={
                "legal_name": {"source": "extracted"},
                "tin": {"source": "extracted"},
                "address": {"source": "manual"},
            },
        )
        client, _ = owner_session
        client.post(
            f"/api/v1/connectors/configs/{config.id}/sync-csv/",
            data={
                "file": BytesIO(CSV_FIXTURE),
                "column_mapping": json.dumps(MAPPING),
            },
        )
        # Filter by field_name — ``.first()`` is non-deterministic
        # when the CSV creates multiple conflicts on the same row
        # (legal_name "Acme" vs "Acme Sdn Bhd" + address).
        conflict = MasterFieldConflict.objects.filter(
            field_name="address"
        ).first()
        response = client.post(
            f"/api/v1/connectors/conflicts/{conflict.id}/resolve/",
            data=json.dumps({"resolution": "take_incoming"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        master.refresh_from_db()
        assert master.address == "Level 5 KL"


# =============================================================================
# Locks
# =============================================================================


@pytest.mark.django_db
class TestLocks:
    def test_lock_field(self, org, owner_session) -> None:
        client, _ = owner_session
        master_id = str(uuid.uuid4())
        response = client.post(
            "/api/v1/connectors/locks/",
            data=json.dumps(
                {
                    "master_type": "customer",
                    "master_id": master_id,
                    "field_name": "tin",
                    "reason": "LHDN-verified",
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 201
        assert MasterFieldLock.objects.filter(master_id=master_id).exists()

    def test_unlock_field(self, org, owner_session) -> None:
        master_id = uuid.uuid4()
        MasterFieldLock.objects.create(
            organization=org,
            master_type=MasterType.CUSTOMER,
            master_id=master_id,
            field_name="tin",
            locked_by_user_id=uuid.uuid4(),
        )
        client, _ = owner_session
        response = client.post(
            "/api/v1/connectors/locks/unlock/",
            data=json.dumps(
                {
                    "master_type": "customer",
                    "master_id": str(master_id),
                    "field_name": "tin",
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["removed"] is True

    def test_viewer_cannot_lock(self, viewer_session) -> None:
        client, _ = viewer_session
        response = client.post(
            "/api/v1/connectors/locks/",
            data=json.dumps(
                {
                    "master_type": "customer",
                    "master_id": str(uuid.uuid4()),
                    "field_name": "tin",
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 403
