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
