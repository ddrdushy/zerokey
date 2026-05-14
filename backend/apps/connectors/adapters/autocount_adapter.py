"""AutoCount connector adapter (Slice 85 + PORTAL_PLAN Phase 2).

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

import csv
import io
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal, InvalidOperation

from apps.connectors.documents import ConnectorDocument, DocumentType
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


# Sales Invoice / Credit Note / Debit Note export — AutoCount issues
# all three with the same header set; the fetcher passes the
# document_type through. Verified against AutoCount Account 1.9 + 2.5.
AUTOCOUNT_DOCUMENT_MAPPING: dict[str, str] = {
    "Doc No": "external_ref",
    "Document No": "external_ref",
    "Invoice No": "external_ref",
    "Date": "issue_date",
    "Doc Date": "issue_date",
    "Due Date": "due_date",
    # Buyer block.
    "Debtor Code": "buyer_code",
    "Debtor Name": "buyer_legal_name",
    "Customer Name": "buyer_legal_name",
    "Tax Reg. No": "buyer_tin",
    "Buyer TIN": "buyer_tin",
    "BRN No": "buyer_registration_number",
    "Address 1": "buyer_address",
    "Country Code": "buyer_country_code",
    # Totals.
    "Sub Total": "subtotal",
    "Subtotal": "subtotal",
    "Tax Amount": "total_tax",
    "Tax Total": "total_tax",
    "Grand Total": "grand_total",
    "Total": "grand_total",
    "Currency Code": "currency_code",
    "Currency": "currency_code",
    # CN / DN reference back to the original invoice.
    "Ref Doc No": "references_invoice_number",
    "Ref Invoice No": "references_invoice_number",
    "Original Invoice": "references_invoice_number",
    # Payment.
    "Terms": "payment_terms_code",
    "Payment Terms": "payment_terms_code",
    "Our Reference": "payment_reference",
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
        if target not in {"customers", "items", "documents"}:
            raise ConnectorError(
                f"target must be 'customers', 'items' or 'documents', got {target!r}"
            )
        self._target = target
        self._documents_csv: bytes | None = None
        if target == "documents":
            self._documents_csv = csv_bytes
            self._inner = None  # type: ignore[assignment]
        else:
            column_mapping = (
                AUTOCOUNT_CUSTOMER_MAPPING if target == "customers" else AUTOCOUNT_ITEM_MAPPING
            )
            self._inner = CSVConnector(
                csv_bytes=csv_bytes,
                column_mapping=column_mapping,
                target=target,
            )

    def authenticate(self) -> None:
        # No auth — the export-and-upload is the trust boundary.
        return None

    def fetch_customers(self) -> Iterable[ConnectorRecord]:
        if self._inner is None:
            return iter([])
        return self._inner.fetch_customers()

    def fetch_items(self) -> Iterable[ConnectorRecord]:
        if self._inner is None:
            return iter([])
        return self._inner.fetch_items()

    def fetch_documents(
        self,
        *,
        document_type: DocumentType,
        after_external_ref: str = "",
    ) -> Iterable[ConnectorDocument]:
        """Yield Invoice / CN / DN rows from an AutoCount documents CSV.

        Mirrors the SQL Account adapter's shape — same dedup-by-
        external-ref strategy, same lenient-by-default row parsing.
        """
        if self._documents_csv is None:
            raise ConnectorError(
                "fetch_documents requires the adapter to have been constructed with "
                "target='documents'."
            )
        text = self._documents_csv.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        for raw_row in reader:
            normalised: dict[str, str] = {}
            for header, value in raw_row.items():
                if header is None:
                    continue
                col_key = (header or "").strip()
                target = AUTOCOUNT_DOCUMENT_MAPPING.get(col_key)
                if target is None:
                    continue
                normalised.setdefault(target, (value or "").strip())

            external_ref = normalised.get("external_ref") or ""
            if not external_ref:
                continue
            if after_external_ref and external_ref <= after_external_ref:
                continue

            try:
                issue_date = _parse_date(normalised.get("issue_date") or "")
            except ValueError:
                continue

            due_date_value = normalised.get("due_date") or ""
            due_date = None
            if due_date_value:
                try:
                    due_date = _parse_date(due_date_value)
                except ValueError:
                    due_date = None

            yield ConnectorDocument(
                external_ref=external_ref,
                document_type=document_type,
                invoice_number=external_ref,
                issue_date=issue_date,
                due_date=due_date,
                currency_code=(normalised.get("currency_code") or "MYR").upper()[:3],
                subtotal=_parse_decimal(normalised.get("subtotal") or "0"),
                total_tax=_parse_decimal(normalised.get("total_tax") or "0"),
                grand_total=_parse_decimal(normalised.get("grand_total") or "0"),
                buyer_legal_name=normalised.get("buyer_legal_name") or "",
                buyer_tin=normalised.get("buyer_tin") or "",
                buyer_registration_number=normalised.get("buyer_registration_number") or "",
                buyer_address=normalised.get("buyer_address") or "",
                buyer_country_code=(normalised.get("buyer_country_code") or "MY").upper()[:2],
                references_invoice_number=normalised.get("references_invoice_number") or "",
                payment_terms_code=normalised.get("payment_terms_code") or "",
                payment_reference=normalised.get("payment_reference") or "",
                raw_payload=normalised,
            )


# --- helpers (shape mirrors sql_account_adapter for consistency) ---------

_AUTOCOUNT_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y")


def _parse_date(value: str):
    if not value:
        raise ValueError("empty date")
    for fmt in _AUTOCOUNT_DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date format: {value!r}")


def _parse_decimal(value: str) -> Decimal:
    if not value:
        return Decimal("0")
    cleaned = value.replace(",", "").replace("RM", "").replace("MYR", "").strip()
    try:
        return Decimal(cleaned or "0")
    except InvalidOperation:
        return Decimal("0")
