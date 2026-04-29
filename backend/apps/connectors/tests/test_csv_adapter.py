"""Tests for the CSV connector adapter (Slice 77)."""

from __future__ import annotations

import pytest

from apps.connectors.adapters import CSVConnector, ConnectorError, get_adapter_class
from apps.connectors.models import IntegrationConfig


CSV_BASIC = b"""Company Name,Tax ID,Address
Acme Sdn Bhd,C9999999999,Level 5 KL
Globex Bhd,C8888888888,Level 10 PJ
"""

CSV_WITH_BOM = b"\xef\xbb\xbfCompany Name,Tax ID\nAcme,C9999999999\n"

CSV_WITH_BLANK_ROW = b"""Company Name,Tax ID
Acme,C9999999999
,
Globex,C8888888888
"""

MAPPING_CUSTOMERS = {
    "Company Name": "legal_name",
    "Tax ID": "tin",
    "Address": "address",
}


class TestCSVAdapterShape:
    def test_basic_parse_yields_records(self) -> None:
        adapter = CSVConnector(
            csv_bytes=CSV_BASIC, column_mapping=MAPPING_CUSTOMERS
        )
        records = list(adapter.fetch_customers())
        assert len(records) == 2
        first = records[0]
        assert first.fields["legal_name"] == "Acme Sdn Bhd"
        assert first.fields["tin"] == "C9999999999"
        assert first.fields["address"] == "Level 5 KL"

    def test_unmapped_columns_dropped_silently(self) -> None:
        # Source CSV has 3 columns; we only map 2.
        partial_mapping = {
            "Company Name": "legal_name",
            "Tax ID": "tin",
        }
        adapter = CSVConnector(
            csv_bytes=CSV_BASIC, column_mapping=partial_mapping
        )
        records = list(adapter.fetch_customers())
        # Address dropped; legal_name + tin retained.
        assert "address" not in records[0].fields
        assert records[0].fields["legal_name"] == "Acme Sdn Bhd"

    def test_handles_utf8_bom(self) -> None:
        adapter = CSVConnector(
            csv_bytes=CSV_WITH_BOM,
            column_mapping={"Company Name": "legal_name", "Tax ID": "tin"},
        )
        records = list(adapter.fetch_customers())
        assert records[0].fields["legal_name"] == "Acme"

    def test_skips_blank_rows(self) -> None:
        adapter = CSVConnector(
            csv_bytes=CSV_WITH_BLANK_ROW,
            column_mapping={"Company Name": "legal_name", "Tax ID": "tin"},
        )
        records = list(adapter.fetch_customers())
        # 3 data rows, 1 entirely blank — dropped.
        assert len(records) == 2

    def test_target_items_returns_empty_for_customers_call(self) -> None:
        adapter = CSVConnector(
            csv_bytes=CSV_BASIC,
            column_mapping=MAPPING_CUSTOMERS,
            target="items",
        )
        # When target is items, the customers iterator is empty.
        assert list(adapter.fetch_customers()) == []
        # And items iterator pulls from the same CSV.
        assert len(list(adapter.fetch_items())) == 2

    def test_authenticate_is_noop(self) -> None:
        adapter = CSVConnector(
            csv_bytes=CSV_BASIC, column_mapping=MAPPING_CUSTOMERS
        )
        # No exception.
        adapter.authenticate()

    def test_empty_csv_rejected(self) -> None:
        with pytest.raises(ConnectorError, match="empty"):
            CSVConnector(csv_bytes=b"", column_mapping=MAPPING_CUSTOMERS)

    def test_empty_mapping_rejected(self) -> None:
        with pytest.raises(ConnectorError, match="column_mapping"):
            CSVConnector(csv_bytes=CSV_BASIC, column_mapping={})

    def test_invalid_target_rejected(self) -> None:
        with pytest.raises(ConnectorError, match="target"):
            CSVConnector(
                csv_bytes=CSV_BASIC,
                column_mapping=MAPPING_CUSTOMERS,
                target="something_else",
            )

    def test_blank_csv_yields_no_records(self) -> None:
        # A CSV with just blank lines + no header doesn't crash —
        # it just yields zero records. The propose path then
        # produces a no-op proposal which is safe.
        adapter = CSVConnector(
            csv_bytes=b"\n\n",
            column_mapping=MAPPING_CUSTOMERS,
        )
        assert list(adapter.fetch_customers()) == []

    def test_explicit_source_record_id_column(self) -> None:
        csv_with_id = (
            b"row_id,Company Name\n"
            b"DEBT-1,Acme\n"
            b"DEBT-2,Globex\n"
        )
        adapter = CSVConnector(
            csv_bytes=csv_with_id,
            column_mapping={
                "row_id": "source_record_id",
                "Company Name": "legal_name",
            },
        )
        records = list(adapter.fetch_customers())
        assert records[0].source_record_id == "DEBT-1"
        assert records[1].source_record_id == "DEBT-2"


class TestRegistry:
    def test_csv_dispatched(self) -> None:
        klass = get_adapter_class(IntegrationConfig.ConnectorType.CSV)
        assert klass is CSVConnector

    def test_unknown_connector_raises(self) -> None:
        with pytest.raises(ConnectorError, match="No adapter"):
            get_adapter_class("not_a_real_connector")
