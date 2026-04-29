"""AutoCount connector adapter (Slice 85).

AutoCount is the dominant SME accounting package in the Malaysian
market — desktop-first, ODBC primary, with a CSV export path
that's universal across versions. ZeroKey's AutoCount connector
is intentionally CSV-driven: it accepts the standard AutoCount
*Debtor List* / *Stock Item Maintenance* CSV exports and applies
a fixed column mapping that matches the column headers AutoCount
uses out of the box. The customer doesn't have to do the column-
mapping wizard the generic CSV connector requires.

Why CSV instead of ODBC for v1
-----------------------------

The ODBC path requires:
  - The customer to install the AutoCount ODBC driver (32-bit DSN
    on a Windows host) + open the SQL Server port to ZeroKey,
    *or* run a sidecar agent on their LAN.
  - A version negotiation matrix per AutoCount edition (Account
    1.x / 1.8 / 1.9 / 2.x / 2.5 / 5.x …).

The export-CSV-and-upload path needs neither — and AutoCount's
"Export to CSV" is a one-click gesture from the standard list
views. Customers who want the always-on path can still do it
later via the SQL_ACCOUNTING connector type (Phase 4).

Column mapping
--------------

AutoCount's CSV column headers are standardised across versions
for the two reference-data exports we care about. The mappings
below match the *unmodified* headers; we normalise whitespace +
case at the CSVConnector layer so light wording drift doesn't
break onboarding.

If a customer's installation has been customised (renamed
columns, removed columns, custom fields) they should fall back
to the generic CSV connector + the column-mapping wizard.
"""

from __future__ import annotations

from collections.abc import Iterable

from apps.connectors.sync_services import ConnectorRecord

from .base import BaseConnector, ConnectorError
from .csv_adapter import CSVConnector

# Debtor List — the standard AutoCount customer/buyer export.
# Source columns are the headers the AutoCount UI emits when an
# operator uses File → Export → CSV on the Debtor Maintenance
# screen.
AUTOCOUNT_CUSTOMER_MAPPING: dict[str, str] = {
    "Account No": "source_record_id",
    "Company Name": "legal_name",
    # AutoCount uses "Tax Reg. No" or "GST Tax Reg. No" depending
    # on the edition — both versions of the header map to TIN.
    "Tax Reg. No": "tin",
    "GST Tax Reg. No": "tin",
    "BRN No": "registration_number",
    "Business Reg. No": "registration_number",
    "Address 1": "address",
    "Phone 1": "phone",
    "Country Code": "country_code",
    "MSIC Code": "msic_code",
    "SST Reg. No": "sst_number",
}


# Stock Item Maintenance — AutoCount's items/products export.
AUTOCOUNT_ITEM_MAPPING: dict[str, str] = {
    "Item Code": "source_record_id",
    "Description": "canonical_name",
    "UOM": "default_unit_of_measurement",
    "Standard Cost": "default_unit_price_excl_tax",
    "Tax Code": "default_tax_type_code",
    "Classification": "default_classification_code",
    "MSIC Code": "default_msic_code",
}


class AutoCountConnector(BaseConnector):
    """AutoCount adapter — CSV-driven with a baked-in column mapping.

    Wraps ``CSVConnector`` so the propose / apply / conflict
    plumbing is identical to a generic CSV upload. The only
    difference is the customer-visible UX: they upload an
    AutoCount export *as-is* without the column-mapping wizard.
    """

    name = "autocount"

    def __init__(
        self,
        *,
        csv_bytes: bytes,
        target: str = "customers",
    ) -> None:
        if target not in {"customers", "items"}:
            raise ConnectorError(f"target must be 'customers' or 'items', got {target!r}")
        column_mapping = (
            AUTOCOUNT_CUSTOMER_MAPPING if target == "customers" else AUTOCOUNT_ITEM_MAPPING
        )
        # Reuse the CSV adapter wholesale — encoding fallback,
        # whitespace normalisation, empty-row skipping, etc.
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
