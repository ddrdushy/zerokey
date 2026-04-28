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
"""

from __future__ import annotations

# Sub-schema for each entry inside the ``line_items`` array. Mirrors the
# fields ``apps.submission.services._materialise_line_items`` reads off
# each parsed line. Cross-context import would be cleaner, but the
# extraction app must not import submission models — services-only is
# the rule, and this is a documentation contract, not a model relation.
_LINE_ITEM_FIELDS = [
    ("description", "free-text description of the item"),
    ("quantity", "decimal as string, e.g. \"2.000\""),
    ("unit_of_measurement", "e.g. EA, KG, HOUR; empty if unspecified"),
    ("unit_price_excl_tax", "decimal as string, before tax"),
    ("line_subtotal_excl_tax", "quantity * unit_price_excl_tax"),
    ("tax_type_code", "LHDN tax type code, e.g. 01 for SST; empty if not stated"),
    ("tax_rate", "percentage as string, e.g. \"6\" for 6%"),
    ("tax_amount", "decimal as string"),
    ("line_total_incl_tax", "subtotal + tax_amount"),
    ("classification_code", "LHDN classification code; empty if absent"),
]

# Name of the structured (array) key inside the FieldStructure schema.
# Kept in this module rather than imported from submission to preserve
# the bounded-context boundary; if these ever drift the
# ``test_prompt_includes_line_items_shape`` test catches it.
LINE_ITEMS_KEY = "line_items"


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
        flat_listing = "\n".join(f"  - {f}" for f in flat_fields)
        parts.append(
            "Header fields — each value is a string extracted verbatim from "
            "the document. Use an empty string for fields not present in the "
            f"text. Do NOT guess.\n{flat_listing}"
        )

    if has_line_items:
        line_listing = "\n".join(
            f"    - {name}: {desc}" for name, desc in _LINE_ITEM_FIELDS
        )
        parts.append(
            f"\"{LINE_ITEMS_KEY}\" — a JSON ARRAY of line item objects. Each "
            "line item is one billable row from the invoice. If the document "
            "lists no line items, return an empty array. Each object has the "
            f"following keys (use empty string for absent fields):\n{line_listing}"
        )

    parts.append(f"Invoice text:\n---\n{text}\n---")
    parts.append("Respond with the JSON object only, no prose, no code fences.")

    return "\n\n".join(parts)
