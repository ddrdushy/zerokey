"""UBL 2.1 invoice XML generator (Slice 58).

LHDN MyInvois accepts e-invoices in two formats: UBL 2.1 (XML) and
JSON. We use UBL because that's the canonical structure LHDN
publishes its schema against, and the validation rules in
LHDN_INTEGRATION.md map most cleanly onto it.

This module produces the *unsigned* XML. The signing step
(``apps.submission.xml_signature``) wraps the result in an
enveloped XML-DSig signature.

Scope today (Slice 58 v1):

  - Header fields: invoice_number, issue_date, due_date,
    currency_code.
  - Supplier party block (TIN, name, address).
  - Buyer party block (TIN, name, address).
  - Line items with quantity / unit price / tax / total.
  - Tax totals + monetary totals.

Deferred (out of scope for v1):

  - Credit / debit notes (different DocumentType codes).
  - Foreign-currency exchange rate elements.
  - Allowance / charge codes beyond the simple discount.
  - Consolidated B2C invoices (one XML, many implicit lines).
  - Pre-payment notes.

The XML is built with ``xml.etree.ElementTree`` from the stdlib —
no lxml dependency. ``ElementTree.canonicalize()`` (added in
Python 3.8) handles the C14N step the signature requires.
"""

from __future__ import annotations

from decimal import Decimal
from xml.etree import ElementTree as ET

from .models import Invoice, LineItem

# UBL namespace constants. We attach these as default xmlns
# declarations on the root so child elements come out unprefixed
# (matching LHDN's published example XML).
NS_INVOICE = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
NS_CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
NS_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"

# UBL conformance + customization identifiers — the values LHDN
# expects on Malaysian e-invoices. If LHDN updates these (rare;
# usually a new MyInvois release), they're a one-line change here.
LHDN_CUSTOMIZATION_ID = "urn:oasis:names:specification:ubl:dsig:enveloped:xades"
LHDN_PROFILE_ID = "urn:www.cenbii.eu:profile:bii05:ver2.0"

# Document type code 01 = Standard Invoice. Other codes (02 credit
# note, 03 debit note, etc.) come in later slices.
DEFAULT_DOCUMENT_TYPE_CODE = "01"
DEFAULT_DOCUMENT_TYPE_VERSION = "1.0"


def build_invoice_xml(invoice: Invoice) -> bytes:
    """Build a canonicalized UBL 2.1 invoice XML for one Invoice row.

    Returns UTF-8 bytes. The output is canonicalised
    (``ElementTree.canonicalize``) so the digest computed by the
    signature module matches what LHDN sees.
    """
    ET.register_namespace("", NS_INVOICE)
    ET.register_namespace("cac", NS_CAC)
    ET.register_namespace("cbc", NS_CBC)

    root = ET.Element(f"{{{NS_INVOICE}}}Invoice")
    _cbc(root, "CustomizationID", LHDN_CUSTOMIZATION_ID)
    _cbc(root, "ProfileID", LHDN_PROFILE_ID)
    _cbc(root, "ID", invoice.invoice_number or str(invoice.id))
    _cbc(
        root,
        "IssueDate",
        invoice.issue_date.isoformat() if invoice.issue_date else "",
    )
    _cbc(
        root,
        "IssueTime",
        # LHDN expects an HH:MM:SS — we don't track issue time on the
        # Invoice today, so use midnight. A future slice may add it.
        "00:00:00Z",
    )
    _cbc(root, "InvoiceTypeCode", DEFAULT_DOCUMENT_TYPE_CODE)
    _cbc(root, "DocumentCurrencyCode", invoice.currency_code or "MYR")
    if invoice.due_date:
        _cbc(root, "DueDate", invoice.due_date.isoformat())

    # --- Parties ---------------------------------------------------------

    _build_party(
        root,
        tag="AccountingSupplierParty",
        legal_name=invoice.supplier_legal_name,
        tin=invoice.supplier_tin,
        registration_number=invoice.supplier_registration_number,
        msic_code=invoice.supplier_msic_code,
        address=invoice.supplier_address,
        sst_number=invoice.supplier_sst_number,
        country_code="MY",
    )
    _build_party(
        root,
        tag="AccountingCustomerParty",
        legal_name=invoice.buyer_legal_name,
        tin=invoice.buyer_tin,
        registration_number=invoice.buyer_registration_number,
        msic_code="",
        address=invoice.buyer_address,
        sst_number=invoice.buyer_sst_number,
        country_code=invoice.buyer_country_code or "MY",
    )

    # --- Tax totals ------------------------------------------------------

    if invoice.total_tax is not None:
        tax_total = _cac(root, "TaxTotal")
        _cbc_amount(tax_total, "TaxAmount", invoice.total_tax, invoice.currency_code)

    # --- Monetary totals -------------------------------------------------

    legal_total = _cac(root, "LegalMonetaryTotal")
    if invoice.subtotal is not None:
        _cbc_amount(legal_total, "LineExtensionAmount", invoice.subtotal, invoice.currency_code)
        _cbc_amount(legal_total, "TaxExclusiveAmount", invoice.subtotal, invoice.currency_code)
    if invoice.grand_total is not None:
        _cbc_amount(legal_total, "TaxInclusiveAmount", invoice.grand_total, invoice.currency_code)
        _cbc_amount(legal_total, "PayableAmount", invoice.grand_total, invoice.currency_code)

    # --- Line items ------------------------------------------------------

    for line in invoice.line_items.all().order_by("line_number"):
        _build_invoice_line(root, line, invoice.currency_code)

    # Canonicalise so the digest the signer computes is stable.
    raw = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    canonical = ET.canonicalize(raw, with_comments=False).encode("utf-8")
    return canonical


# --- Helper builders --------------------------------------------------------


def _cbc(parent: ET.Element, tag: str, value: str) -> ET.Element:
    """Append a cbc:<tag>value</tag> child."""
    el = ET.SubElement(parent, f"{{{NS_CBC}}}{tag}")
    el.text = "" if value is None else str(value)
    return el


def _cac(parent: ET.Element, tag: str) -> ET.Element:
    """Append an empty cac:<tag/> container child."""
    return ET.SubElement(parent, f"{{{NS_CAC}}}{tag}")


def _cbc_amount(
    parent: ET.Element, tag: str, value: Decimal | float | int, currency: str
) -> ET.Element:
    """Append a cbc:<tag currencyID="MYR">12.34</tag> typed-amount child."""
    el = ET.SubElement(parent, f"{{{NS_CBC}}}{tag}")
    el.set("currencyID", currency or "MYR")
    if isinstance(value, Decimal):
        el.text = f"{value:.2f}"
    else:
        el.text = f"{Decimal(str(value)):.2f}"
    return el


def _build_party(
    parent: ET.Element,
    *,
    tag: str,
    legal_name: str,
    tin: str,
    registration_number: str,
    msic_code: str,
    address: str,
    sst_number: str,
    country_code: str,
) -> None:
    party_wrap = _cac(parent, tag)
    party = _cac(party_wrap, "Party")

    # PartyIdentification carries TIN + (optional) BRN + MSIC + SST.
    # Schemes match LHDN's published examples.
    _party_identifier(party, scheme="TIN", value=tin)
    if registration_number:
        _party_identifier(party, scheme="BRN", value=registration_number)
    if sst_number:
        _party_identifier(party, scheme="SST", value=sst_number)
    if msic_code:
        _party_identifier(party, scheme="MSIC", value=msic_code)

    # PartyLegalEntity → RegistrationName carries the canonical name.
    legal_entity = _cac(party, "PartyLegalEntity")
    _cbc(legal_entity, "RegistrationName", legal_name or "")

    # PostalAddress is required for LHDN even if empty — line-1 +
    # country are the bare minimum. We pack the whole stored address
    # into AddressLine.Line for v1; future slices parse it into
    # StreetName / CityName / PostalZone properly.
    postal = _cac(party, "PostalAddress")
    address_line = _cac(postal, "AddressLine")
    _cbc(address_line, "Line", address or "")
    country = _cac(postal, "Country")
    _cbc(country, "IdentificationCode", country_code or "MY")


def _party_identifier(party: ET.Element, *, scheme: str, value: str) -> None:
    pi = _cac(party, "PartyIdentification")
    el = _cbc(pi, "ID", value or "")
    el.set("schemeID", scheme)


def _build_invoice_line(parent: ET.Element, line: LineItem, currency: str) -> None:
    line_el = _cac(parent, "InvoiceLine")
    _cbc(line_el, "ID", str(line.line_number))
    _cbc_amount(
        line_el,
        "InvoicedQuantity",
        line.quantity if line.quantity is not None else Decimal("0"),
        currency,
    )
    _cbc_amount(
        line_el,
        "LineExtensionAmount",
        line.line_subtotal_excl_tax if line.line_subtotal_excl_tax is not None else Decimal("0"),
        currency,
    )

    if line.tax_amount is not None:
        tax_total = _cac(line_el, "TaxTotal")
        _cbc_amount(tax_total, "TaxAmount", line.tax_amount, currency)
        if line.tax_type_code:
            tax_subtotal = _cac(tax_total, "TaxSubtotal")
            _cbc_amount(tax_subtotal, "TaxAmount", line.tax_amount, currency)
            tax_category = _cac(tax_subtotal, "TaxCategory")
            _cbc(tax_category, "ID", line.tax_type_code)
            if line.tax_rate is not None:
                _cbc(tax_category, "Percent", f"{line.tax_rate}")

    item = _cac(line_el, "Item")
    _cbc(item, "Description", line.description or "")
    if line.classification_code:
        commodity = _cac(item, "CommodityClassification")
        ic = _cbc(commodity, "ItemClassificationCode", line.classification_code)
        ic.set("listID", "CLASS")

    price = _cac(line_el, "Price")
    _cbc_amount(
        price,
        "PriceAmount",
        line.unit_price_excl_tax if line.unit_price_excl_tax is not None else Decimal("0"),
        currency,
    )
