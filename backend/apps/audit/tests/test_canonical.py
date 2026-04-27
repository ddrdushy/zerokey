"""Tests for the canonical JSON serializer.

These tests are byte-exact: the serializer's job is to produce reproducible
output, so the assertions are on literal bytes/strings, not structural
equivalence."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from apps.audit.canonical import FloatNotAllowedError, canonical_bytes, canonical_string


class TestCanonical:
    def test_sorts_object_keys_lexicographically(self) -> None:
        assert canonical_string({"b": 1, "a": 2}) == '{"a":2,"b":1}'

    def test_no_whitespace_between_tokens(self) -> None:
        assert canonical_string({"k": [1, 2, 3]}) == '{"k":[1,2,3]}'

    def test_nested_objects_are_sorted_recursively(self) -> None:
        out = canonical_string({"x": {"b": 1, "a": 2}, "y": [{"d": 1, "c": 2}]})
        assert out == '{"x":{"a":2,"b":1},"y":[{"c":2,"d":1}]}'

    def test_floats_are_rejected(self) -> None:
        with pytest.raises(FloatNotAllowedError):
            canonical_bytes({"amount": 12.5})

    def test_decimal_is_rendered_as_string(self) -> None:
        assert canonical_string({"amount": Decimal("1234.5600")}) == '{"amount":"1234.56"}'

    def test_uuid_is_rendered_as_canonical_string(self) -> None:
        u = UUID("11111111-2222-3333-4444-555555555555")
        assert canonical_string({"id": u}) == '{"id":"11111111-2222-3333-4444-555555555555"}'

    def test_unicode_is_emitted_unescaped(self) -> None:
        # We use ensure_ascii=False; UTF-8 bytes are emitted directly.
        assert canonical_bytes({"name": "Aisyah"}) == b'{"name":"Aisyah"}'
        assert canonical_bytes({"name": "Çarşı"}) == b'{"name":"\xc3\x87ar\xc5\x9f\xc4\xb1"}'

    def test_unknown_types_raise_typeerror(self) -> None:
        class Custom:
            pass

        with pytest.raises(TypeError):
            canonical_bytes({"x": Custom()})

    def test_byte_exactness_across_dict_orderings(self) -> None:
        a = {"a": 1, "b": 2, "c": 3}
        b = dict(reversed(list(a.items())))
        assert canonical_bytes(a) == canonical_bytes(b)
