"""Tests for the shared FieldStructure prompt builder.

The prompt is a contract between the structuring service (which decides
the schema) and the adapters (which talk to a model). Particularly: the
prompt must teach models that ``line_items`` is a JSON array of objects
with a documented sub-schema, not a single string. The original prompt
told models "all values are strings" which produced an empty string for
``line_items`` on every real invoice.

These tests pin down the contract without coupling to exact wording so
prompt-engineering iterations don't require lockstep test churn.
"""

from __future__ import annotations

from apps.extraction.prompts import LINE_ITEMS_KEY, build_field_structure_prompt


def test_prompt_lists_each_flat_field() -> None:
    schema = ["invoice_number", "issue_date", "currency_code"]
    prompt = build_field_structure_prompt(text="some invoice text", target_schema=schema)
    for field in schema:
        assert field in prompt
    assert "some invoice text" in prompt


def test_prompt_describes_line_items_as_json_array() -> None:
    schema = ["invoice_number", LINE_ITEMS_KEY]
    prompt = build_field_structure_prompt(text="ignored", target_schema=schema)
    # The line items section must announce its array nature so the model
    # doesn't return an empty string for the whole structured key.
    assert "JSON ARRAY" in prompt or "json array" in prompt.lower()
    # At least one of the documented sub-fields appears so the model has
    # the schema in-context.
    assert "description" in prompt
    assert "quantity" in prompt
    assert "tax_rate" in prompt


def test_prompt_omits_line_items_section_when_not_in_schema() -> None:
    # A future caller asking for headers only shouldn't see the array
    # section. Keeps the prompt focused.
    schema = ["invoice_number", "issue_date"]
    prompt = build_field_structure_prompt(text="ignored", target_schema=schema)
    assert "JSON ARRAY" not in prompt
    assert "line_items" not in prompt


def test_prompt_includes_only_jsons_not_prose_directive() -> None:
    # Without "no prose / code fences", smaller models often wrap output
    # in ```json fences or add commentary. The receiver strips fences
    # defensively but the prompt should still ask for clean output.
    prompt = build_field_structure_prompt(text="x", target_schema=["invoice_number"])
    assert "JSON" in prompt or "json" in prompt
    assert "prose" in prompt.lower() or "code fence" in prompt.lower()


# Slice 110 — LHDN-format hints for the fields the structurer keeps
# confusing on tabular layouts.


def test_supplier_tin_hint_distinguishes_tin_from_brn() -> None:
    # Without this hint the model picks the BRN out of the first
    # "ID Type/Number" column. The hint must call out the C/IG/OG
    # prefix and explicitly exclude the BRN.
    prompt = build_field_structure_prompt(
        text="x", target_schema=["supplier_tin", "buyer_tin"]
    )
    assert '"C"' in prompt
    assert "IG" in prompt and "OG" in prompt
    # BRN is the wrong answer on the same layout — the hint must
    # name it explicitly so the model doesn't fall back to it.
    assert "BRN" in prompt or "business registration" in prompt.lower()


def test_registration_number_hint_separates_from_tin() -> None:
    prompt = build_field_structure_prompt(
        text="x",
        target_schema=["supplier_registration_number", "buyer_registration_number"],
    )
    assert "BRN" in prompt
    # Must clarify it's NOT the TIN — otherwise the model can still
    # cross-wire the values.
    assert "NOT the TIN" in prompt


def test_issue_date_hint_calls_out_iso_format() -> None:
    prompt = build_field_structure_prompt(text="x", target_schema=["issue_date"])
    assert "YYYY-MM-DD" in prompt
    # On LHDN-format invoices the label is "Issuance Date", not
    # "Invoice Date" — the hint should mention it.
    assert "Issuance Date" in prompt or "issuance date" in prompt.lower()


def test_currency_hint_blocks_rm_symbol() -> None:
    # "RM" is the Malaysian symbol; the field expects ISO 4217.
    # The hint must call this out explicitly.
    prompt = build_field_structure_prompt(text="x", target_schema=["currency_code"])
    assert "MYR" in prompt
    assert "ISO 4217" in prompt or "iso 4217" in prompt.lower()


def test_id_type_hint_lists_allowed_values() -> None:
    # The structurer must pick from PARTY_ID_TYPES — anything else
    # is rejected by EDITABLE_HEADER_FIELDS' allowlist. Hint must
    # name BRN / NRIC / PASSPORT / ARMY so the model has the set.
    prompt = build_field_structure_prompt(
        text="x", target_schema=["supplier_id_type", "buyer_id_type"]
    )
    for v in ("BRN", "NRIC", "PASSPORT", "ARMY"):
        assert v in prompt


def test_id_value_hint_mentions_brn_for_corporates_and_excludes_tin() -> None:
    prompt = build_field_structure_prompt(
        text="x", target_schema=["supplier_id_value", "buyer_id_value"]
    )
    # Must clarify that for corporates this duplicates the
    # registration_number, so the model knows both fields get the
    # same value rather than guessing.
    assert "supplier_registration_number" in prompt or "buyer_registration_number" in prompt
    # Must explicitly exclude TIN — same reason as the registration
    # number hint.
    assert "NOT the TIN" in prompt


def test_msic_hint_blocks_sst_registration_numbers() -> None:
    # Real failure mode (Slice 111 follow-up): structurer grabbed
    # "W10-1808" from the buyer's SST registration number and put it
    # in buyer_msic_code. The hint must explicitly reject that shape.
    prompt = build_field_structure_prompt(
        text="x", target_schema=["supplier_msic_code", "buyer_msic_code"]
    )
    # Calls out the exact failure pattern.
    assert "SST" in prompt
    # And the format constraint.
    assert "5 numeric digits" in prompt or "5 digits" in prompt
    # And tells the model to leave the buyer side empty when the
    # block doesn't carry an explicit MSIC label.
    assert "leave this" in prompt or "empty" in prompt.lower()


def test_hintless_fields_render_as_bare_bullets() -> None:
    # Most fields don't have a hint registered — they should render
    # as a plain bullet without empty colon noise.
    prompt = build_field_structure_prompt(
        text="x", target_schema=["payment_reference", "subtotal"]
    )
    assert "payment_reference" in prompt
    # No ``payment_reference:`` since no hint is registered.
    assert "payment_reference: " not in prompt
    assert "subtotal: " not in prompt
