"""Document-record shapes for the Phase 2 invoice-pull framework.

A connector adapter exposes ``fetch_documents(document_type, after=<cursor>)``
which yields ``ConnectorDocument`` instances. The pull service turns each
one into an ``IngestionJob`` + ``Invoice`` row using the same downstream
machinery the upload / email paths feed into.

The shape is deliberately flat. Adapters do whatever normalisation their
source needs (column-mapping, currency parsing, date parsing) before
yielding — the pull service should never need source-specific knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal


DocumentType = Literal["invoice", "credit_note", "debit_note"]


@dataclass(frozen=True)
class ConnectorLineItem:
    """One line on a connector-pulled document. All amounts are MYR
    (or the document's currency_code at the connector level — line
    items inherit)."""

    description: str
    quantity: Decimal = Decimal("1")
    unit_price: Decimal = Decimal("0")
    line_total: Decimal = Decimal("0")
    tax_rate: Decimal | None = None
    tax_amount: Decimal = Decimal("0")
    msic_code: str = ""
    item_classification_code: str = ""


@dataclass(frozen=True)
class ConnectorDocument:
    """A single Invoice / CN / DN pulled from an ERP connector.

    All fields are flat ZeroKey-native types. The adapter does the
    mapping work (column rename, currency parse, etc.) so the pull
    service can ingest without source-specific branching.

    ``external_ref`` is the stable id of the document in the source
    system. Used as the cursor value (the pull service tracks the
    highest external_ref seen per document type) and as the IngestionJob
    ``source_identifier`` for de-dup against re-deliveries.
    """

    # Required cursor + identification.
    external_ref: str
    document_type: DocumentType
    invoice_number: str

    # Dates.
    issue_date: date
    due_date: date | None = None

    # Currency + totals (top-level — the connector might also yield
    # line_items below, but most exports give the totals at the top
    # only and we accept either shape).
    currency_code: str = "MYR"
    subtotal: Decimal = Decimal("0")
    total_tax: Decimal = Decimal("0")
    grand_total: Decimal = Decimal("0")

    # Parties — connector-pulled documents typically already know
    # exactly who buyer/supplier are, so we don't need to AI-extract.
    supplier_legal_name: str = ""
    supplier_tin: str = ""
    supplier_registration_number: str = ""

    buyer_legal_name: str = ""
    buyer_tin: str = ""
    buyer_registration_number: str = ""
    buyer_address: str = ""
    buyer_country_code: str = "MY"

    # When this document is a CN/DN, the original invoice it amends.
    references_invoice_number: str = ""

    # Free-text payment terms / reference fields the adapter may or
    # may not populate.
    payment_terms_code: str = ""
    payment_reference: str = ""

    line_items: list[ConnectorLineItem] = field(default_factory=list)

    # Anything else the adapter wants to stash in raw form. Survives
    # to the IngestionJob.extracted_text field as a JSON blob for
    # debugging / re-extraction.
    raw_payload: dict = field(default_factory=dict)
