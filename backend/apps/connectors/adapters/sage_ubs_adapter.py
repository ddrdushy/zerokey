"""Sage UBS connector adapter (Slice 98).

Sage UBS (formerly UBS Accounting) is the third leg of the Malaysian
SME accounting trio alongside AutoCount (Slice 85) and SQL Account.
Sage's market share is largest among the older / mid-market segment;
the import path here is the same: customer exports their reference
data to CSV, drops it on the connector, sync runs.

Why CSV
-------
Same logic as the other two adapters. Sage UBS's primary persistence
is a btrieve / DBASE-format database — the integration path is either
through Sage's own export tools (which produce CSV) or a paid Sage
"Connect" middleware, both of which terminate at flat files anyway.
The export-and-upload model dodges the licensing + middleware
ceremony.

Column mapping (verified against Sage UBS Accounting 9.9.x exports)
--------------------------------------------------------------------
Sage UBS uses its own header conventions that don't quite match the
LHDN-aware versions of AutoCount / SQL Account; in particular it
historically uses "Customer No" instead of "Account No" for the
debtor key, and "GST Reg No" left in legacy exports. We accept both
the LHDN-era and pre-LHDN headers so customers don't have to upgrade
their installation just to onboard.

Customers with field-customised installations should still use the
generic CSV connector + column-mapping wizard.
"""

from __future__ import annotations

from collections.abc import Iterable

from apps.connectors.sync_services import ConnectorRecord

from .base import BaseConnector, ConnectorError
from .csv_adapter import CSVConnector

# Sage UBS Customer Master export. Headers normalised at the
# CSVConnector layer (whitespace + case), so minor variants tolerate.
SAGE_UBS_CUSTOMER_MAPPING: dict[str, str] = {
    "Customer No": "source_record_id",
    "Customer Code": "source_record_id",
    "Account No": "source_record_id",
    "Customer Name": "legal_name",
    "Name": "legal_name",
    "Tax No": "tin",
    "TIN": "tin",
    "GST Reg No": "tin",  # legacy pre-LHDN field — many UBS installs still emit this
    "BRN": "registration_number",
    "Reg No": "registration_number",
    "Address 1": "address",
    "Telephone": "phone",
    "Phone": "phone",
    "Country": "country_code",
    "MSIC Code": "msic_code",
    "SST Reg No": "sst_number",
    "SST No": "sst_number",
}


# Sage UBS Stock / Inventory export. Sage's terminology uses "Stock"
# rather than "Item"; the column headers below cover both single-
# UOM and multi-UOM stock card exports.
SAGE_UBS_ITEM_MAPPING: dict[str, str] = {
    "Stock No": "source_record_id",
    "Stock Code": "source_record_id",
    "Item Code": "source_record_id",
    "Description": "canonical_name",
    "Stock Description": "canonical_name",
    "UOM": "default_unit_of_measurement",
    "Unit": "default_unit_of_measurement",
    "Standard Cost": "default_unit_price_excl_tax",
    "Cost": "default_unit_price_excl_tax",
    "Tax Code": "default_tax_type_code",
    "Tax Type": "default_tax_type_code",
    "Classification": "default_classification_code",
    "MSIC Code": "default_msic_code",
    "MSIC": "default_msic_code",
}


class SageUbsConnector(BaseConnector):
    """Sage UBS adapter — CSV-driven with a baked-in column mapping."""

    name = "sage_ubs"

    def __init__(
        self,
        *,
        csv_bytes: bytes,
        target: str = "customers",
    ) -> None:
        if target not in {"customers", "items"}:
            raise ConnectorError(f"target must be 'customers' or 'items', got {target!r}")
        column_mapping = (
            SAGE_UBS_CUSTOMER_MAPPING if target == "customers" else SAGE_UBS_ITEM_MAPPING
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
