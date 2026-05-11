"""Shared prompt construction for FieldStructure / VisionExtract adapters.

Why this isn't inlined in each adapter: the prompt is a *contract* between
the structuring service and the adapters. The service decides which
fields it wants; the adapter decides how to ask the model. Keeping them
in sync requires that both sides agree on what each field means — and
particularly that ``line_items`` is a JSON array of objects with its
own sub-schema, not a string.

The original adapters (Slice 12 + 29) treated every schema entry as
"return a string". For flat header fields that worked. For
``line_items`` it didn't — the model returned an empty string because
the prompt told it to. This module replaces those ad-hoc prompts with
a single builder that special-cases the structured key.

If we add a second structured key in future (e.g. ``allowances``,
``discount_breakdown``), it lands here as another branch alongside
``line_items``. Adapters stay unchanged.

Field-specific hints (Slice 110)
--------------------------------
LHDN MyInvois e-invoice PDFs lay out the supplier and buyer blocks
with TWO adjacent identifier columns: an "ID Type/Number" column
(holding the Malaysian BRN — 12 digits starting with the year of
incorporation) and a "TIN" column (holding the LHDN TIN — letter-
prefixed: ``C`` for corporate, ``IG``/``OG`` for individual). Before
this slice the prompt asked the model for ``supplier_tin`` and
``buyer_tin`` without describing the value pattern; on the tabular
layout the model would default to the first numeric field it saw
under the supplier block, which is the BRN. The result: every LHDN-
format invoice came back with the BRN sitting in the TIN field, and
the user (who knew the validation rule expected a ``C`` prefix)
would manually add it — producing a non-existent TIN like
``C201601011111`` (BRN with C prepended). The fix is to give the
model the value pattern, and to keep the BRN separately on
``supplier_registration_number`` / ``buyer_registration_number``
where it belongs.
"""

from __future__ import annotations

# Sub-schema for each entry inside the ``line_items`` array. Mirrors the
# fields ``apps.submission.services._materialise_line_items`` reads off
# each parsed line. Cross-context import would be cleaner, but the
# extraction app must not import submission models — services-only is
# the rule, and this is a documentation contract, not a model relation.
_LINE_ITEM_FIELDS = [
    (
        "description",
        # The duplication clause is non-obvious but load-bearing: when the
        # model is parsing a table where the column header AND the row's
        # own description both contain the same noun phrase (e.g.
        # "Dependent Pass" as a section header above a row labeled
        # "Dependent Pass Fees to Mdec"), it tends to concatenate them
        # and produce "Dependent Pass Dependent Pass Fees to Mdec". Same
        # for embedding the qty / unit price into the description text.
        "free-text description of the item, exactly as written for that "
        "row. Do NOT repeat section headers or prepend the column "
        "header to the row text. Do NOT include quantity, unit price, "
        "or totals — those go in their own keys.",
    ),
    ("quantity", 'decimal as string, e.g. "2.000"'),
    ("unit_of_measurement", "e.g. EA, KG, HOUR; empty if unspecified"),
    ("unit_price_excl_tax", "decimal as string, before tax"),
    ("line_subtotal_excl_tax", "quantity * unit_price_excl_tax"),
    ("tax_type_code", "LHDN tax type code, e.g. 01 for SST; empty if not stated"),
    ("tax_rate", 'percentage as string, e.g. "6" for 6%'),
    ("tax_amount", "decimal as string"),
    ("line_total_incl_tax", "subtotal + tax_amount"),
    ("classification_code", "LHDN classification code; empty if absent"),
]

# Name of the structured (array) key inside the FieldStructure schema.
# Kept in this module rather than imported from submission to preserve
# the bounded-context boundary; if these ever drift the
# ``test_prompt_includes_line_items_shape`` test catches it.
LINE_ITEMS_KEY = "line_items"


# Field-specific hints (Slice 110). One entry per flat field where the
# generic "extract verbatim" instruction has proven insufficient — most
# commonly because the LHDN-format e-invoice lays out adjacent
# look-alike values that the model conflates without explicit pattern
# guidance. Keys missing from this map fall through to the bare
# instruction; the prompt stays short for the easy fields.
_FIELD_HINTS: dict[str, str] = {
    "supplier_tin": (
        "the LHDN tax identifier of the supplier — corporate TIN "
        '"C" + 11 digits (e.g. C11189700090), or individual TIN '
        '"IG"/"OG" + 11 digits. Do NOT use the business registration '
        "number (BRN): if you see two adjacent identifier columns "
        "labelled \"ID Type/Number\" and \"TIN\", the TIN is the one "
        "that begins with a letter. Empty if the document doesn't "
        "carry one."
    ),
    "buyer_tin": (
        "the LHDN tax identifier of the buyer — same shape as "
        "supplier_tin (corporate \"C\" + 11 digits, or individual "
        '"IG"/"OG" + 11 digits). NOT the BRN. Empty if absent.'
    ),
    "supplier_registration_number": (
        "Malaysian Business Registration Number (BRN) of the supplier "
        "— 12 digits, typically starting with the year of "
        'incorporation (e.g. 200201008429). This is the value in the '
        '"ID Type/Number" column, NOT the TIN column.'
    ),
    "buyer_registration_number": (
        "Malaysian BRN of the buyer — 12 digits. Same rules as "
        "supplier_registration_number. NOT the TIN."
    ),
    "issue_date": (
        "the date the supplier issued the invoice. On LHDN-format "
        "e-invoices this is labelled \"Issuance Date\" or "
        '"Issue Date". Return ISO 8601 (YYYY-MM-DD); strip any '
        "time-of-day component."
    ),
    "due_date": (
        "the payment due date, ISO 8601 (YYYY-MM-DD). When the "
        "document says \"e-Invoice Type: Paid Invoice\" (or is marked "
        "Valid + has a Submission Date in the past), the invoice was "
        "settled at issuance — default due_date to the issue_date in "
        "that case. A service period like \"(13/05/2026 - 12/05/2029)\" "
        "in a line description is the service window, NOT the due "
        "date. Empty only if the document has no payment timing at all."
    ),
    "currency_code": (
        "ISO 4217 3-letter currency code (e.g. MYR, USD, SGD). "
        "Malaysian invoices default to MYR; never use \"RM\" — that's "
        "the symbol, not the code."
    ),
    "supplier_id_type": (
        "the LHDN secondary-ID scheme for the supplier. One of: "
        '"BRN" (Malaysian corporates — registration number), "NRIC" '
        '(Malaysian individuals — citizen ID), "PASSPORT" (foreigners), '
        '"ARMY" (military ID). For a Malaysian Sdn Bhd / Bhd, this is '
        'always "BRN". Empty only if the document has no identifier at '
        "all."
    ),
    "supplier_id_value": (
        "the value matching supplier_id_type — the 12-digit BRN, the "
        "NRIC number, the passport number, etc. For a BRN this is the "
        "same 12-digit number that goes in supplier_registration_number "
        "(populate both). NOT the TIN."
    ),
    "buyer_id_type": (
        "the LHDN secondary-ID scheme for the buyer. Same allowed "
        'values as supplier_id_type ("BRN" / "NRIC" / "PASSPORT" / '
        '"ARMY"). Look at the buyer block of the document, not the '
        "supplier block."
    ),
    "buyer_id_value": (
        "the value matching buyer_id_type — the buyer's BRN, NRIC, or "
        "passport number. For a BRN this is the same 12-digit number "
        "that goes in buyer_registration_number (populate both). NOT "
        "the TIN."
    ),
    "supplier_msic_code": (
        "Malaysian Standard Industrial Classification code of the "
        "supplier — EXACTLY 5 numeric digits (e.g. 63111). Only fill "
        "if the document explicitly labels a field as \"MSIC\" or "
        "\"MSIC Code\". Do NOT use SST registration numbers (which "
        "contain letters and dashes like W10-1808-31031530), tax "
        "registration numbers, or any value that contains anything "
        "other than 5 digits. Empty if no explicit MSIC label exists."
    ),
    "buyer_msic_code": (
        "MSIC code of the buyer — same rules as supplier_msic_code "
        "(exactly 5 numeric digits, only if explicitly labelled "
        "\"MSIC\" under the BUYER block). The buyer block on most "
        "LHDN-format invoices does NOT carry an MSIC code; if you "
        "only see SST or contact numbers under the buyer, leave this "
        "empty rather than guessing."
    ),
    "buyer_country_code": (
        "ISO 3166-1 alpha-2 country code of the buyer (e.g. MY, SG, "
        "US). Default to MY if the buyer address ends in a Malaysian "
        "state."
    ),
}


def build_field_structure_prompt(*, text: str, target_schema: list[str]) -> str:
    """Build the full FieldStructure prompt for an Ollama / Claude / etc.

    The model is asked to return a single JSON object whose keys match
    the target schema. Most keys map to a string value; ``line_items``
    maps to an array of objects whose shape is documented inline so the
    model has the schema in-context (rather than relying on the receiver
    parsing a free-form list).

    A model that doesn't follow JSON output format strictly still has
    a fighting chance because the receiver (``_parse_json_payload``)
    strips code fences and the caller's JSON-mode flag is independent.
    The prompt is the *intent* signal; the wire-level enforcement is
    Ollama's ``format: "json"`` parameter (or the equivalent for other
    providers).
    """
    has_line_items = LINE_ITEMS_KEY in target_schema
    flat_fields = [f for f in target_schema if f != LINE_ITEMS_KEY]

    parts: list[str] = []
    parts.append(
        "You are structuring extracted text from a Malaysian invoice for "
        "LHDN MyInvois submission. Return a single JSON object whose keys "
        "are exactly the field names below. Do not invent extra keys."
    )

    if flat_fields:
        # Slice 110 — emit a hint per field where one is registered.
        # Fields without a hint render as a bare bullet so the prompt
        # stays tight for the easy ones (totals, addresses, etc.).
        flat_listing = "\n".join(
            f"  - {f}: {_FIELD_HINTS[f]}" if f in _FIELD_HINTS else f"  - {f}"
            for f in flat_fields
        )
        parts.append(
            "Header fields — each value is a string extracted verbatim from "
            "the document. Use an empty string for fields not present in the "
            "text. Do NOT guess. Field-specific notes are inline where the "
            f"LHDN format needs disambiguation:\n{flat_listing}"
        )

    if has_line_items:
        line_listing = "\n".join(f"    - {name}: {desc}" for name, desc in _LINE_ITEM_FIELDS)
        parts.append(
            f'"{LINE_ITEMS_KEY}" — a JSON ARRAY of line item objects. Each '
            "line item is one billable row from the invoice. If the document "
            "lists no line items, return an empty array. Each object has the "
            f"following keys (use empty string for absent fields):\n{line_listing}"
        )

    parts.append(f"Invoice text:\n---\n{text}\n---")
    parts.append("Respond with the JSON object only, no prose, no code fences.")

    return "\n\n".join(parts)
