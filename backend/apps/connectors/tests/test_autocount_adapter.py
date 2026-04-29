"""Tests for the AutoCount connector adapter (Slice 85)."""

from __future__ import annotations

import json

import pytest

from apps.connectors.adapters import AutoCountConnector, ConnectorError
from apps.connectors.adapters.autocount_adapter import (
    AUTOCOUNT_CUSTOMER_MAPPING,
    AUTOCOUNT_ITEM_MAPPING,
)
from apps.connectors.models import IntegrationConfig
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
        legal_name="Acme",
        tin="C1234567890",
        contact_email="o@a.example",
    )


# =============================================================================
# Adapter — column mapping + record yield
# =============================================================================


class TestAutoCountAdapter:
    def test_customer_export_yields_records(self) -> None:
        # Standard AutoCount Debtor List CSV (column headers as
        # produced by the AutoCount UI's "Export to CSV" gesture).
        csv_bytes = (
            b"Account No,Company Name,Tax Reg. No,BRN No,Address 1,Phone 1,Country Code\n"
            b"300-A001,Acme Buyer Sdn Bhd,C20000000001,200101012345,Level 5 KL Sentral,03-1234 5678,MY\n"
            b"300-A002,Globex Bhd,C30000000002,200201023456,Tower X PJ,03-9876 5432,MY\n"
        )
        adapter = AutoCountConnector(csv_bytes=csv_bytes, target="customers")
        records = list(adapter.fetch_customers())
        assert len(records) == 2

        first = records[0]
        # Account No is the source_record_id (AutoCount's primary key).
        assert first.source_record_id == "300-A001"
        assert first.fields["legal_name"] == "Acme Buyer Sdn Bhd"
        assert first.fields["tin"] == "C20000000001"
        assert first.fields["registration_number"] == "200101012345"
        assert first.fields["address"] == "Level 5 KL Sentral"
        assert first.fields["phone"] == "03-1234 5678"
        assert first.fields["country_code"] == "MY"

    def test_gst_tax_reg_no_alias_maps_to_tin(self) -> None:
        # Older AutoCount editions emit "GST Tax Reg. No" instead of
        # "Tax Reg. No"; both must land on the TIN field.
        csv_bytes = b"Account No,Company Name,GST Tax Reg. No\n300-A003,Legacy Co,C40000000003\n"
        adapter = AutoCountConnector(csv_bytes=csv_bytes, target="customers")
        records = list(adapter.fetch_customers())
        assert records[0].fields["tin"] == "C40000000003"

    def test_item_export_yields_records(self) -> None:
        csv_bytes = (
            b"Item Code,Description,UOM,Standard Cost,Tax Code,MSIC Code\n"
            b"WIDGET-A,Widget Type A,UNIT,12.50,06,25920\n"
            b"WIDGET-B,Widget Type B,UNIT,15.00,06,25920\n"
        )
        adapter = AutoCountConnector(csv_bytes=csv_bytes, target="items")
        records = list(adapter.fetch_items())
        assert len(records) == 2

        first = records[0]
        assert first.source_record_id == "WIDGET-A"
        assert first.fields["canonical_name"] == "Widget Type A"
        assert first.fields["default_unit_of_measurement"] == "UNIT"
        assert first.fields["default_unit_price_excl_tax"] == "12.50"
        assert first.fields["default_tax_type_code"] == "06"
        assert first.fields["default_msic_code"] == "25920"

    def test_unknown_columns_dropped_silently(self) -> None:
        # Customer's installation has extra custom columns — the
        # mapping ignores them rather than failing onboarding.
        csv_bytes = (
            b"Account No,Company Name,CustomNote,InternalRef\n300-A100,Some Co,private note,XR-99\n"
        )
        adapter = AutoCountConnector(csv_bytes=csv_bytes, target="customers")
        records = list(adapter.fetch_customers())
        assert records[0].source_record_id == "300-A100"
        assert records[0].fields == {"legal_name": "Some Co"}

    def test_target_must_be_customers_or_items(self) -> None:
        with pytest.raises(ConnectorError, match="target must be"):
            AutoCountConnector(csv_bytes=b"Account No\n300-A1\n", target="ledger")

    def test_empty_csv_rejected(self) -> None:
        with pytest.raises(ConnectorError, match="empty"):
            AutoCountConnector(csv_bytes=b"", target="customers")

    def test_blank_rows_skipped(self) -> None:
        csv_bytes = (
            b"Account No,Company Name\n"
            b"300-A1,Co A\n"
            b",\n"  # blank row
            b"300-A2,Co B\n"
        )
        adapter = AutoCountConnector(csv_bytes=csv_bytes, target="customers")
        records = list(adapter.fetch_customers())
        assert [r.source_record_id for r in records] == ["300-A1", "300-A2"]

    def test_mapping_constants_are_disjoint_per_target(self) -> None:
        # Customer + item mappings target distinct master fields —
        # if they overlapped, swapping target would silently
        # produce malformed records.
        cust_targets = set(AUTOCOUNT_CUSTOMER_MAPPING.values()) - {"source_record_id"}
        item_targets = set(AUTOCOUNT_ITEM_MAPPING.values()) - {"source_record_id"}
        assert cust_targets.isdisjoint(item_targets)

    def test_authenticate_is_no_op(self) -> None:
        # AutoCount adapter has no auth handshake.
        adapter = AutoCountConnector(
            csv_bytes=b"Account No,Company Name\n300-A1,Co\n", target="customers"
        )
        adapter.authenticate()  # must not raise


# =============================================================================
# Endpoint — POST /sync-autocount/
# =============================================================================


@pytest.fixture
def org_owner(org, seeded):
    user = User.objects.create_user(email="o@a.example", password="long-enough-password")
    OrganizationMembership.objects.create(
        user=user, organization=org, role=Role.objects.get(name="owner")
    )
    return org, user


@pytest.fixture
def autocount_config(org) -> IntegrationConfig:
    return IntegrationConfig.objects.create(
        organization=org,
        connector_type=IntegrationConfig.ConnectorType.AUTOCOUNT,
    )


@pytest.fixture
def csv_config(org) -> IntegrationConfig:
    return IntegrationConfig.objects.create(
        organization=org,
        connector_type=IntegrationConfig.ConnectorType.CSV,
    )


@pytest.mark.django_db
class TestAutoCountEndpoint:
    def test_owner_uploads_and_proposal_created(self, org_owner, autocount_config) -> None:
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import Client

        org, user = org_owner
        client = Client()
        client.force_login(user)
        session = client.session
        session["organization_id"] = str(org.id)
        session.save()

        csv_bytes = (
            b"Account No,Company Name,Tax Reg. No\n300-A001,Acme Buyer Sdn Bhd,C20000000001\n"
        )
        upload = SimpleUploadedFile("debtor_list.csv", csv_bytes, content_type="text/csv")
        response = client.post(
            f"/api/v1/connectors/configs/{autocount_config.id}/sync-autocount/",
            data={"file": upload, "target": "customers"},
        )
        assert response.status_code == 201
        body = response.json()
        # The sync proposal carries a diff describing the proposed
        # changes. Existence + a non-empty entry for the customer
        # we uploaded is the contract.
        assert "diff" in body
        diff_str = json.dumps(body["diff"])
        assert "300-A001" in diff_str or "Acme Buyer Sdn Bhd" in diff_str

    def test_endpoint_rejects_non_autocount_config(self, org_owner, csv_config) -> None:
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import Client

        org, user = org_owner
        client = Client()
        client.force_login(user)
        session = client.session
        session["organization_id"] = str(org.id)
        session.save()

        upload = SimpleUploadedFile(
            "x.csv", b"Account No,Company Name\n300-A1,Co\n", content_type="text/csv"
        )
        response = client.post(
            f"/api/v1/connectors/configs/{csv_config.id}/sync-autocount/",
            data={"file": upload},
        )
        assert response.status_code == 400
        assert "AutoCount" in response.json()["detail"]

    def test_endpoint_requires_file(self, org_owner, autocount_config) -> None:
        from django.test import Client

        org, user = org_owner
        client = Client()
        client.force_login(user)
        session = client.session
        session["organization_id"] = str(org.id)
        session.save()

        response = client.post(
            f"/api/v1/connectors/configs/{autocount_config.id}/sync-autocount/",
            data={"target": "customers"},
        )
        assert response.status_code == 400


# =============================================================================
# Adapter is registered in the dispatch table
# =============================================================================


def test_dispatch_table_resolves_autocount() -> None:
    # The propose-sync orchestrator dispatches by connector_type;
    # the adapter must be in the registry for AUTOCOUNT to ever
    # work end-to-end.
    from apps.connectors.adapters import get_adapter_class

    klass = get_adapter_class(IntegrationConfig.ConnectorType.AUTOCOUNT)
    assert klass is AutoCountConnector
