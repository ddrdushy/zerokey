"""Sage UBS connector adapter (Slice 98 + PORTAL_PLAN Phase 2).

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

import csv
import io
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal, InvalidOperation

from apps.connectors.documents import ConnectorDocument, DocumentType
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


# Sage UBS Sales Invoice / Credit Note / Debit Note export. The headers
# below cover both legacy 9.x and newer LHDN-aware exports; first match
# wins so installations on either side resolve to the same logical
# fields.
SAGE_UBS_DOCUMENT_MAPPING: dict[str, str] = {
    "Doc No": "external_ref",
    "Invoice No": "external_ref",
    "Document No": "external_ref",
    "Date": "issue_date",
    "Invoice Date": "issue_date",
    "Doc Date": "issue_date",
    "Due Date": "due_date",
    # Buyer / customer block.
    "Customer No": "buyer_code",
    "Customer Code": "buyer_code",
    "Customer Name": "buyer_legal_name",
    "Name": "buyer_legal_name",
    "Tax No": "buyer_tin",
    "TIN": "buyer_tin",
    "BRN": "buyer_registration_number",
    "Reg No": "buyer_registration_number",
    "Address 1": "buyer_address",
    "Country": "buyer_country_code",
    # Totals.
    "Sub Total": "subtotal",
    "Subtotal": "subtotal",
    "Tax Amount": "total_tax",
    "Total Tax": "total_tax",
    "Grand Total": "grand_total",
    "Total": "grand_total",
    "Currency": "currency_code",
    "Currency Code": "currency_code",
    # CN / DN reference.
    "Ref Invoice": "references_invoice_number",
    "Reference Invoice": "references_invoice_number",
    "Original Invoice": "references_invoice_number",
    # Payment.
    "Terms": "payment_terms_code",
    "Our Ref": "payment_reference",
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
                SAGE_UBS_CUSTOMER_MAPPING if target == "customers" else SAGE_UBS_ITEM_MAPPING
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
        """Yield Invoice / CN / DN rows from a Sage UBS documents CSV.

        Mirrors AutoCount / SQL Account in shape — same dedup-by-
        external-ref + tolerant-row-parsing strategy. Lenient on the
        legacy header drift so older UBS installs onboard without an
        upgrade.
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
                target = SAGE_UBS_DOCUMENT_MAPPING.get(col_key)
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


# --- helpers (shape mirrors sql_account / autocount for consistency) ----

_SAGE_UBS_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y")


def _parse_date(value: str):
    if not value:
        raise ValueError("empty date")
    for fmt in _SAGE_UBS_DATE_FORMATS:
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
