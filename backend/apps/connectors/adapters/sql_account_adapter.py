"""SQL Account connector adapter (Slice 98).

SQL Account (Estream Software Sdn Bhd) is the second-most-popular
SME accounting package in the Malaysian market after AutoCount.
Like Slice 85's AutoCount adapter, this is intentionally CSV-driven
— SQL Account's *Debtor Maintenance* and *Stock Maintenance* exports
ship with stable column headers, so a fixed mapping covers the
common case and the column-mapping wizard isn't needed for
unmodified installations.

Why CSV first
-------------
Same trade-off as AutoCount (Slice 85):
  - SQL Account's primary integration path is ODBC against an MSSQL
    backend, which means a Windows host + DSN + port-open ceremony.
  - The *File → Export → CSV* gesture is one-click and works the
    same across SQL Account 700 / 800 / 900 / Cloud versions.

When a customer asks for always-on sync we add a sidecar-agent path
on top — same upserts, just delivered by a daemon on their LAN.

Column mapping (verified against SQL Account 800 + Cloud exports)
-----------------------------------------------------------------
SQL Account's exports use the same column header style as the UI.
Header normalisation (whitespace + case) happens at the CSVConnector
layer, so minor wording drift (e.g. trailing colons) tolerates fine.

Customers with customised installations should drop to the generic
CSV connector + the column-mapping wizard.
"""

from __future__ import annotations

from collections.abc import Iterable

from apps.connectors.sync_services import ConnectorRecord

from .base import BaseConnector, ConnectorError
from .csv_adapter import CSVConnector

# Debtor Maintenance export — SQL Account's customer/buyer reference
# data. Headers below match the unmodified SQL Account export; the
# alternates handle the rename in 900+ ("Company" → "Company Name").
SQL_ACCOUNT_CUSTOMER_MAPPING: dict[str, str] = {
    "Code": "source_record_id",
    "Account No": "source_record_id",
    "Company Name": "legal_name",
    "Company": "legal_name",
    # SQL Account splits the registration block across "TIN", "BRN"
    # and "SST Reg. No" since the LHDN-mandated 2024 update.
    "TIN": "tin",
    "Tax Reg No": "tin",
    "BRN": "registration_number",
    "SSM No": "registration_number",
    "Address 1": "address",
    "Phone": "phone",
    "Phone 1": "phone",
    "Country": "country_code",
    "MSIC": "msic_code",
    "MSIC Code": "msic_code",
    "SST Reg. No": "sst_number",
    "SST No": "sst_number",
}


# Stock Maintenance export — SQL Account's products/items reference
# data.
SQL_ACCOUNT_ITEM_MAPPING: dict[str, str] = {
    "Code": "source_record_id",
    "Item Code": "source_record_id",
    "Description": "canonical_name",
    "Description 1": "canonical_name",
    "UOM": "default_unit_of_measurement",
    "Base UOM": "default_unit_of_measurement",
    "Cost Price": "default_unit_price_excl_tax",
    "Standard Cost": "default_unit_price_excl_tax",
    "Tax Code": "default_tax_type_code",
    "Output Tax": "default_tax_type_code",
    "Classification Code": "default_classification_code",
    "Classification": "default_classification_code",
    "MSIC": "default_msic_code",
    "MSIC Code": "default_msic_code",
}


class SqlAccountConnector(BaseConnector):
    """SQL Account adapter — CSV-driven with a baked-in column mapping.

    Wraps ``CSVConnector`` so the propose / apply / conflict
    plumbing is identical to a generic CSV upload. Customer
    experience: they upload an SQL Account export *as-is* without
    the column-mapping wizard.
    """

    name = "sql_account"

    def __init__(
        self,
        *,
        csv_bytes: bytes,
        target: str = "customers",
    ) -> None:
        if target not in {"customers", "items"}:
            raise ConnectorError(f"target must be 'customers' or 'items', got {target!r}")
        column_mapping = (
            SQL_ACCOUNT_CUSTOMER_MAPPING if target == "customers" else SQL_ACCOUNT_ITEM_MAPPING
        )
        self._inner = CSVConnector(
            csv_bytes=csv_bytes,
            column_mapping=column_mapping,
            target=target,
        )
        self._target = target

    def authenticate(self) -> None:
        # No auth — the export-and-upload is the trust boundary.
        return None

    def fetch_customers(self) -> Iterable[ConnectorRecord]:
        return self._inner.fetch_customers()

    def fetch_items(self) -> Iterable[ConnectorRecord]:
        return self._inner.fetch_items()
