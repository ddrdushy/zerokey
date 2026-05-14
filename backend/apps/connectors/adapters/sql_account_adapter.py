"""SQL Account connector adapter (Slice 98 + PORTAL_PLAN Phase 2).

SQL Account (Estream Software Sdn Bhd) is the second-most-popular
SME accounting package in the Malaysian market after AutoCount.
Like Slice 85's AutoCount adapter, this is intentionally CSV-driven
— SQL Account's *Debtor Maintenance*, *Stock Maintenance*, *Sales
Invoice*, *Credit Note* and *Debit Note* exports ship with stable
column headers, so a fixed mapping covers the common case and the
column-mapping wizard isn't needed for unmodified installations.

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

import csv
import io
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal, InvalidOperation

from apps.connectors.documents import ConnectorDocument, DocumentType
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


# Sales Invoice / Credit Note / Debit Note export — SQL Account's
# issued-document export. All three export types share the same
# header set (the only difference is "Doc No" prefix conventions:
# INV-, CN-, DN-); we use a single mapping for all three and the
# fetcher passes the document_type through.
SQL_ACCOUNT_DOCUMENT_MAPPING: dict[str, str] = {
    "Doc No": "external_ref",
    "Document No": "external_ref",
    "Invoice No": "external_ref",
    "Date": "issue_date",
    "Doc Date": "issue_date",
    "Due Date": "due_date",
    # Buyer / customer block.
    "Customer Code": "buyer_code",
    "Customer Name": "buyer_legal_name",
    "Buyer Name": "buyer_legal_name",
    "Customer TIN": "buyer_tin",
    "TIN": "buyer_tin",
    "Customer BRN": "buyer_registration_number",
    "BRN": "buyer_registration_number",
    "Customer Address": "buyer_address",
    "Address": "buyer_address",
    "Country": "buyer_country_code",
    # Totals.
    "Sub Total": "subtotal",
    "Subtotal": "subtotal",
    "Total Tax": "total_tax",
    "Tax": "total_tax",
    "Grand Total": "grand_total",
    "Total": "grand_total",
    "Currency": "currency_code",
    # For CN/DN.
    "Ref Invoice No": "references_invoice_number",
    "Original Invoice": "references_invoice_number",
    # Payment metadata.
    "Payment Terms": "payment_terms_code",
    "Payment Ref": "payment_reference",
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

    Targets:
      - ``customers`` / ``items``: reference-data sync (Slice 98).
      - ``documents``: invoice / CN / DN pull (PORTAL_PLAN Phase 2).
        Backed by the connector's own CSV parser rather than the
        master-data CSVConnector — issued documents have totals,
        line items and references that need typed parsing the
        reference-data path doesn't handle.
    """

    name = "sql_account"

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
            # Document target is parsed directly by this adapter — the
            # CSVConnector layer only handles master-data records.
            self._documents_csv = csv_bytes
            self._inner = None  # type: ignore[assignment]
        else:
            column_mapping = (
                SQL_ACCOUNT_CUSTOMER_MAPPING if target == "customers" else SQL_ACCOUNT_ITEM_MAPPING
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
        """Yield Invoice / CN / DN rows from a SQL Account documents CSV.

        Each row in the CSV represents one issued document. The
        ``Doc No`` column is the cursor; SQL Account exports are
        already ordered by document number so we yield in stream
        order and skip anything <= the after-ref.

        Rows that fail to parse (bad date, missing required field)
        are silently dropped — the pull service surfaces aggregate
        failure counts. We do not raise mid-stream because one
        malformed row should not stall the entire pull.
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
                target = SQL_ACCOUNT_DOCUMENT_MAPPING.get(col_key)
                if target is None:
                    continue
                # First mapping wins — header aliases collapse to the
                # same logical key, but we keep whichever came first.
                normalised.setdefault(target, (value or "").strip())

            external_ref = normalised.get("external_ref") or ""
            if not external_ref:
                continue
            if after_external_ref and external_ref <= after_external_ref:
                continue

            try:
                issue_date = _parse_date(normalised.get("issue_date") or "")
            except ValueError:
                continue  # bad date — drop row

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


# --- helpers ----------------------------------------------------------------


# Accepts the date formats SQL Account commonly emits. Adapters that
# need to grow this list add a new format here rather than
# branching at the call site.
_SQL_ACCOUNT_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y")


def _parse_date(value: str):
    if not value:
        raise ValueError("empty date")
    for fmt in _SQL_ACCOUNT_DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date format: {value!r}")


def _parse_decimal(value: str) -> Decimal:
    """SQL Account decimals are usually plain '1234.56'. Tolerate
    thousand-separators and trailing currency markers."""
    if not value:
        return Decimal("0")
    cleaned = value.replace(",", "").replace("RM", "").replace("MYR", "").strip()
    try:
        return Decimal(cleaned or "0")
    except InvalidOperation:
        return Decimal("0")
