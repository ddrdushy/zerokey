"""LHDN MyInvois JSON document builder.

LHDN supports two document formats — UBL XML (Slice 58) and UBL
JSON. The JSON variant is *equivalent* to the XML one; same UBL 2.1
shape, just expressed in JSON's verbose-but-explicit "underscore-key"
encoding.

We build JSON for the live submission path because:

  - LHDN's sandbox is most thoroughly tested against the JSON path
    (their published examples + Postman collections all use JSON).
  - No XML-DSig wrapping ceremony for v1.0 documents (signing is
    optional in the v1.0 schema).
  - Easier to diff against LHDN's error responses ("missing field
    X at path Y") because JSON paths map 1:1.

UBL JSON shape:

  {
    "_D": "<Invoice namespace>",  # default namespace
    "_A": "<cac namespace>",      # aggregate components
    "_B": "<cbc namespace>",      # basic components
    "Invoice": [{
      "ID": [{"_": "INV-001"}],
      "IssueDate": [{"_": "2026-04-29"}],
      ...
    }]
  }

Every leaf is wrapped in ``[{"_": value}]`` because UBL elements
can repeat. Attributes ride alongside ``_``: e.g.
``[{"_": 100.00, "currencyID": "MYR"}]``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .models import Invoice, LineItem


# LHDN-required namespace identifiers (per their published JSON
# samples).
NS_INVOICE = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
NS_AGG = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
NS_BASIC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"

INVOICE_TYPE_VERSION = "1.0"  # v1.0 = signing-optional

# Maps our internal ``Invoice.InvoiceType`` enum values to LHDN's
# document-type codes (per LHDN MyInvois SDK § Document Types).
LHDN_TYPE_CODES: dict[str, str] = {
    "standard": "01",                    # Invoice
    "credit_note": "02",                 # Credit Note
    "debit_note": "03",                  # Debit Note
    "refund_note": "04",                 # Refund Note
    "self_billed_invoice": "11",         # Self-Billed Invoice
    "self_billed_credit_note": "12",     # Self-Billed Credit Note
    "self_billed_debit_note": "13",      # Self-Billed Debit Note
    "self_billed_refund_note": "14",     # Self-Billed Refund Note
    # Legacy alias from before the split — treat as Self-Billed Invoice.
    "self_billed": "11",
}

# Type codes that REQUIRE a BillingReference to the original
# Invoice's UUID. CN/DN/RN are amendment documents — LHDN refuses
# them without a link to what they're amending.
TYPES_REQUIRING_BILLING_REFERENCE: frozenset[str] = frozenset(
    {"02", "03", "04", "12", "13", "14"}
)


def _v(value: Any) -> dict[str, Any]:
    """Wrap a leaf value in UBL JSON shape: ``{"_": value}``."""
    return {"_": value}


def _amount(value: Decimal | float | int | None, currency: str) -> dict:
    """``{"_": 100.00, "currencyID": "MYR"}`` typed-amount."""
    if value is None:
        n = 0.0
    elif isinstance(value, Decimal):
        n = float(value)
    else:
        n = float(value)
    return {"_": n, "currencyID": currency or "MYR"}


def _identifier(scheme: str, value: str) -> dict:
    return {
        "ID": [
            {"_": value, "schemeID": scheme}
        ],
    }


def _build_party(
    *,
    legal_name: str,
    tin: str,
    registration_number: str,
    sst_number: str,
    msic_code: str,
    industry_classification_name: str,
    address: str,
    city: str = "Kuala Lumpur",
    postal_zone: str = "50000",
    state_code: str = "14",  # 14 = W.P. Kuala Lumpur
    country_code: str = "MYS",
    contact_phone: str = "",
    contact_email: str = "",
) -> dict:
    """Build one Party block.

    LHDN requires:
      - PartyIdentification: TIN (mandatory) + BRN + SST + TTX
        (each marked NA if not applicable — they MUST appear).
      - PostalAddress with CityName + PostalZone +
        CountrySubentityCode + AddressLine + Country.
      - PartyLegalEntity.RegistrationName.
      - Contact (optional but commonly present).
    """
    party: dict[str, Any] = {
        "PartyIdentification": [
            _identifier("TIN", tin or "EI00000000010"),
            _identifier("BRN", registration_number or "NA"),
            _identifier("SST", sst_number or "NA"),
            _identifier("TTX", "NA"),
        ],
        "PostalAddress": [
            {
                "CityName": [_v(city)],
                "PostalZone": [_v(postal_zone)],
                "CountrySubentityCode": [_v(state_code)],
                "AddressLine": [
                    {"Line": [_v(address[:50])]},
                    {"Line": [_v(address[50:100] if len(address) > 50 else "")]},
                    {"Line": [_v(address[100:150] if len(address) > 100 else "")]},
                ],
                "Country": [
                    {
                        "IdentificationCode": [
                            {
                                "_": country_code,
                                "listID": "ISO3166-1",
                                "listAgencyID": "6",
                            }
                        ]
                    }
                ],
            }
        ],
        "PartyLegalEntity": [
            {"RegistrationName": [_v(legal_name)]}
        ],
    }
    if msic_code:
        party["IndustryClassificationCode"] = [
            {
                "_": msic_code,
                "name": industry_classification_name or "Service activities",
            }
        ]
    if contact_phone or contact_email:
        contact: dict[str, list] = {}
        if contact_phone:
            contact["Telephone"] = [_v(contact_phone)]
        if contact_email:
            contact["ElectronicMail"] = [_v(contact_email)]
        party["Contact"] = [contact]
    return {"Party": [party]}


def build_invoice_json(invoice: Invoice) -> dict:
    """Build LHDN MyInvois JSON for one Invoice row.

    Document type is read from ``invoice.invoice_type``. Types
    requiring a billing reference (CN/DN/RN — both regular + self-
    billed) emit a ``BillingReference`` block pointing back at the
    original invoice's LHDN UUID + internal-id.

    Returns a dict ready to ``json.dumps`` + base64 + submit.
    """
    currency = invoice.currency_code or "MYR"

    # Resolve LHDN type code from our enum. Default to 01 (Invoice)
    # for unknown values so the legacy STANDARD path keeps working.
    type_code = LHDN_TYPE_CODES.get(invoice.invoice_type, "01")

    # Header.
    inv_body: dict[str, Any] = {
        "ID": [_v(invoice.invoice_number or str(invoice.id))],
        "IssueDate": [
            _v(invoice.issue_date.isoformat() if invoice.issue_date else "")
        ],
        "IssueTime": [_v("00:00:00Z")],
        "InvoiceTypeCode": [
            {"_": type_code, "listVersionID": INVOICE_TYPE_VERSION}
        ],
        "DocumentCurrencyCode": [_v(currency)],
        "TaxCurrencyCode": [_v(currency)],
    }
    if invoice.due_date:
        inv_body["DueDate"] = [_v(invoice.due_date.isoformat())]

    # BillingReference for amendment documents. Per LHDN SDK §
    # "Credit/Debit Note Reference", the block sits at document
    # level + carries the original invoice's UUID + internal-id.
    if type_code in TYPES_REQUIRING_BILLING_REFERENCE:
        original_uuid = (invoice.original_invoice_uuid or "").strip()
        original_id = (
            invoice.original_invoice_internal_id or invoice.invoice_number or ""
        ).strip()
        inv_body["BillingReference"] = [
            {
                "InvoiceDocumentReference": [
                    {
                        "ID": [_v(original_id or "NA")],
                        "UUID": [_v(original_uuid or "NA")],
                    }
                ]
            }
        ]
        # Adjustment reason — surfaces in MyInvois as the "why".
        if invoice.adjustment_reason:
            inv_body["Note"] = [_v(invoice.adjustment_reason[:300])]

    # Parties. Supplier address parsed roughly; LHDN cares more about
    # presence than perfection on the AddressLine slots.
    inv_body["AccountingSupplierParty"] = [
        _build_party(
            legal_name=invoice.supplier_legal_name or "Supplier",
            tin=invoice.supplier_tin,
            registration_number=invoice.supplier_registration_number,
            sst_number=invoice.supplier_sst_number,
            msic_code=invoice.supplier_msic_code or "62010",
            industry_classification_name="Computer programming activities",
            address=invoice.supplier_address or "Unknown address",
            contact_phone=invoice.supplier_phone,
            contact_email=getattr(
                invoice.organization, "contact_email", ""
            ) or "",
        )
    ]
    inv_body["AccountingCustomerParty"] = [
        _build_party(
            legal_name=invoice.buyer_legal_name or "Buyer",
            tin=invoice.buyer_tin or "EI00000000020",
            registration_number=invoice.buyer_registration_number,
            sst_number=invoice.buyer_sst_number,
            msic_code="",  # Customer MSIC not required.
            industry_classification_name="",
            address=invoice.buyer_address or "Unknown address",
            country_code=_country_iso3(invoice.buyer_country_code) or "MYS",
            contact_phone=invoice.buyer_phone,
        )
    ]

    # Payment means (optional but commonly required for non-cash).
    # We don't track this on the invoice yet — skip.

    # Tax totals.
    if invoice.total_tax is not None:
        inv_body["TaxTotal"] = [
            {
                "TaxAmount": [_amount(invoice.total_tax, currency)],
                "TaxSubtotal": [
                    {
                        "TaxableAmount": [
                            _amount(invoice.subtotal or Decimal("0"), currency)
                        ],
                        "TaxAmount": [_amount(invoice.total_tax, currency)],
                        "TaxCategory": [
                            {
                                "ID": [_v("01")],
                                "TaxScheme": [
                                    {
                                        "ID": [
                                            {
                                                "_": "OTH",
                                                "schemeID": "UN/ECE 5153",
                                                "schemeAgencyID": "6",
                                            }
                                        ]
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]

    # Monetary totals.
    inv_body["LegalMonetaryTotal"] = [
        {
            "LineExtensionAmount": [
                _amount(invoice.subtotal or Decimal("0"), currency)
            ],
            "TaxExclusiveAmount": [
                _amount(invoice.subtotal or Decimal("0"), currency)
            ],
            "TaxInclusiveAmount": [
                _amount(invoice.grand_total or Decimal("0"), currency)
            ],
            "PayableAmount": [
                _amount(invoice.grand_total or Decimal("0"), currency)
            ],
        }
    ]

    # Line items.
    inv_body["InvoiceLine"] = [
        _build_invoice_line(line, currency)
        for line in invoice.line_items.all().order_by("line_number")
    ]

    return {
        "_D": NS_INVOICE,
        "_A": NS_AGG,
        "_B": NS_BASIC,
        "Invoice": [inv_body],
    }


def _build_invoice_line(line: LineItem, currency: str) -> dict:
    item: dict[str, Any] = {
        "Description": [_v(line.description or "Item")],
    }
    if line.classification_code:
        item["CommodityClassification"] = [
            {
                "ItemClassificationCode": [
                    {"_": line.classification_code, "listID": "CLASS"}
                ]
            }
        ]
    line_obj: dict[str, Any] = {
        "ID": [_v(str(line.line_number))],
        "InvoicedQuantity": [
            {
                "_": float(line.quantity or 0),
                "unitCode": line.unit_of_measurement or "C62",
            }
        ],
        "LineExtensionAmount": [
            _amount(line.line_subtotal_excl_tax or Decimal("0"), currency)
        ],
        "Item": [item],
        "Price": [
            {
                "PriceAmount": [
                    _amount(line.unit_price_excl_tax or Decimal("0"), currency)
                ]
            }
        ],
        "ItemPriceExtension": [
            {
                "Amount": [
                    _amount(line.line_subtotal_excl_tax or Decimal("0"), currency)
                ]
            }
        ],
    }
    if line.tax_amount is not None:
        line_obj["TaxTotal"] = [
            {
                "TaxAmount": [_amount(line.tax_amount, currency)],
                "TaxSubtotal": [
                    {
                        "TaxableAmount": [
                            _amount(
                                line.line_subtotal_excl_tax or Decimal("0"),
                                currency,
                            )
                        ],
                        "TaxAmount": [_amount(line.tax_amount, currency)],
                        "TaxCategory": [
                            {
                                "ID": [_v(line.tax_type_code or "01")],
                                "TaxScheme": [
                                    {
                                        "ID": [
                                            {
                                                "_": "OTH",
                                                "schemeID": "UN/ECE 5153",
                                                "schemeAgencyID": "6",
                                            }
                                        ]
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    return line_obj


# --- Helpers ----------------------------------------------------------------


# ISO 3166-1 alpha-2 → alpha-3 for the few countries Malaysian invoices
# typically reference. LHDN expects alpha-3 in their JSON; if we
# stored alpha-2, we map. Otherwise pass through.
_ALPHA2_TO_ALPHA3 = {
    "MY": "MYS",
    "SG": "SGP",
    "ID": "IDN",
    "TH": "THA",
    "VN": "VNM",
    "PH": "PHL",
    "KH": "KHM",
    "BN": "BRN",
    "LA": "LAO",
    "MM": "MMR",
    "CN": "CHN",
    "HK": "HKG",
    "JP": "JPN",
    "KR": "KOR",
    "TW": "TWN",
    "IN": "IND",
    "AU": "AUS",
    "US": "USA",
    "GB": "GBR",
    "DE": "DEU",
    "FR": "FRA",
}


def _country_iso3(code: str) -> str:
    if not code:
        return ""
    code = code.strip().upper()
    if len(code) == 3:
        return code
    return _ALPHA2_TO_ALPHA3.get(code, "")
