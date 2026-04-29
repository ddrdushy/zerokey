"""Tests for the IntegrationConfig model (Slice 73)."""

from __future__ import annotations

import pytest
from django.db import IntegrityError

from apps.connectors.models import IntegrationConfig
from apps.identity.models import Organization, Role


@pytest.fixture
def seeded(db) -> None:
    for name in ("owner", "admin", "approver", "submitter", "viewer"):
        Role.objects.get_or_create(name=name)


@pytest.fixture
def org(seeded) -> Organization:
    return Organization.objects.create(
        legal_name="Connector Test Sdn Bhd",
        tin="C9999999999",
        contact_email="ops@connectors.example",
    )


@pytest.mark.django_db
class TestIntegrationConfigShape:
    def test_create_minimal(self, org) -> None:
        config = IntegrationConfig.objects.create(
            organization=org,
            connector_type=IntegrationConfig.ConnectorType.CSV,
        )
        assert config.id is not None
        assert config.sync_cadence == IntegrationConfig.SyncCadence.MANUAL
        assert config.auto_apply is False
        assert config.last_sync_status == IntegrationConfig.LastSyncStatus.NEVER
        assert config.is_active is True

    def test_unique_per_org_and_type_when_active(self, org) -> None:
        IntegrationConfig.objects.create(
            organization=org,
            connector_type=IntegrationConfig.ConnectorType.XERO,
        )
        # Same org + same type = collision while both rows are active.
        with pytest.raises(IntegrityError):
            IntegrationConfig.objects.create(
                organization=org,
                connector_type=IntegrationConfig.ConnectorType.XERO,
            )

    def test_soft_delete_releases_uniqueness(self, org) -> None:
        from django.utils import timezone

        first = IntegrationConfig.objects.create(
            organization=org,
            connector_type=IntegrationConfig.ConnectorType.XERO,
        )
        # Soft-delete the first row + create a fresh one. Customer
        # disconnected Xero, then re-connected later — must work.
        first.deleted_at = timezone.now()
        first.save()
        replacement = IntegrationConfig.objects.create(
            organization=org,
            connector_type=IntegrationConfig.ConnectorType.XERO,
        )
        assert replacement.id != first.id
        assert first.is_active is False
        assert replacement.is_active is True

    def test_credentials_default_empty_dict(self, org) -> None:
        config = IntegrationConfig.objects.create(
            organization=org,
            connector_type=IntegrationConfig.ConnectorType.QUICKBOOKS,
        )
        assert config.credentials == {}

    def test_all_connector_types_addressable(self, org) -> None:
        # Every enum value must persist + round-trip cleanly. Catches
        # a drift between the doc + the model when the enum is
        # extended later.
        types = [
            IntegrationConfig.ConnectorType.CSV,
            IntegrationConfig.ConnectorType.SQL_ACCOUNTING,
            IntegrationConfig.ConnectorType.AUTOCOUNT,
            IntegrationConfig.ConnectorType.XERO,
            IntegrationConfig.ConnectorType.QUICKBOOKS,
            IntegrationConfig.ConnectorType.SHOPIFY,
            IntegrationConfig.ConnectorType.WOOCOMMERCE,
        ]
        # Create one of each and read back.
        for t in types:
            IntegrationConfig.objects.create(organization=org, connector_type=t)
        assert IntegrationConfig.objects.filter(organization=org).count() == len(types)
