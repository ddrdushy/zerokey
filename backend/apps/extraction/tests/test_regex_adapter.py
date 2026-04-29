"""Tests for the regex floor structurer (Slice 54 OCR-only lane)."""

from __future__ import annotations

import json

import pytest

from apps.extraction.adapters.regex_adapter import RegexFloorStructurer


@pytest.fixture
def structurer() -> RegexFloorStructurer:
    return RegexFloorStructurer()


@pytest.fixture
def target_schema() -> list[str]:
    return [
        "invoice_number",
        "issue_date",
        "due_date",
        "currency_code",
        "supplier_legal_name",
        "supplier_tin",
        "supplier_sst_number",
        "buyer_legal_name",
        "buyer_tin",
        "total_amount",
        "subtotal_amount",
        "tax_amount",
        "line_items",
    ]


CLEAN_INVOICE_TEXT = """
Invoice No: INV-2026-0042
Invoice Date: 15/04/2026
Due Date: 15/05/2026

Supplier: Acme Trading Sdn Bhd
TIN: C1234567890
SST No: W10-1234-1234567

Buyer: Globex Berhad
Buyer TIN: C9999999999

Item                 Qty    Unit       Total
Widget A              5      10.00      50.00
Widget B              3      15.50      46.50

Sub-total: RM 96.50
SST 8%: RM 7.72
Total: RM 104.22

Currency: MYR
"""


def test_extracts_invoice_number(structurer, target_schema) -> None:
    result = structurer.structure_fields(text=CLEAN_INVOICE_TEXT, target_schema=target_schema)
    assert result.fields.get("invoice_number") == "INV-2026-0042"


def test_extracts_dates(structurer, target_schema) -> None:
    result = structurer.structure_fields(text=CLEAN_INVOICE_TEXT, target_schema=target_schema)
    assert result.fields.get("issue_date") == "15/04/2026"
    assert result.fields.get("due_date") == "15/05/2026"


def test_extracts_total_with_thousand_separator(structurer, target_schema) -> None:
    text = "Grand Total: RM 1,234.56\n"
    result = structurer.structure_fields(text=text, target_schema=target_schema)
    assert result.fields.get("total_amount") == "1234.56"


def test_extracts_supplier_tin(structurer, target_schema) -> None:
    result = structurer.structure_fields(text=CLEAN_INVOICE_TEXT, target_schema=target_schema)
    assert result.fields.get("supplier_tin") == "C1234567890"


def test_extracts_currency(structurer, target_schema) -> None:
    result = structurer.structure_fields(text=CLEAN_INVOICE_TEXT, target_schema=target_schema)
    assert result.fields.get("currency_code") == "MYR"


def test_line_items_returned_as_json_string(structurer, target_schema) -> None:
    result = structurer.structure_fields(text=CLEAN_INVOICE_TEXT, target_schema=target_schema)
    raw = result.fields.get("line_items")
    assert raw is not None
    parsed = json.loads(raw)
    assert isinstance(parsed, list)
    assert len(parsed) >= 1
    assert "description" in parsed[0]
    assert "quantity" in parsed[0]
    assert "line_total" in parsed[0]


def test_no_match_yields_empty_result(structurer, target_schema) -> None:
    """Random non-invoice text must not crash + must return a valid result."""
    result = structurer.structure_fields(
        text="this is just some unrelated paragraph", target_schema=target_schema
    )
    assert result.fields == {}
    assert result.overall_confidence == 0.0
    assert result.cost_micros == 0


def test_zero_cost(structurer, target_schema) -> None:
    """OCR-only lane is the cost-saver lane — cost must be 0."""
    result = structurer.structure_fields(text=CLEAN_INVOICE_TEXT, target_schema=target_schema)
    assert result.cost_micros == 0


def test_per_field_confidence_populated(structurer, target_schema) -> None:
    result = structurer.structure_fields(text=CLEAN_INVOICE_TEXT, target_schema=target_schema)
    for k in result.fields:
        # Every field in the output must have a confidence score.
        assert k in result.per_field_confidence
        assert 0.0 < result.per_field_confidence[k] <= 1.0


def test_overall_confidence_scales_with_coverage(structurer, target_schema) -> None:
    """Few hits = low overall; many hits = high overall."""
    sparse = "Date: 01/01/2026\n"
    dense = CLEAN_INVOICE_TEXT
    sparse_result = structurer.structure_fields(text=sparse, target_schema=target_schema)
    dense_result = structurer.structure_fields(text=dense, target_schema=target_schema)
    assert dense_result.overall_confidence > sparse_result.overall_confidence
