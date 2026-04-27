"""Canonical JSON serialization for audit-log content hashing.

The canonical form must be byte-identical for the same logical event so that
content hashes are reproducible by an independent verifier years later. The
rules from AUDIT_LOG_SPEC.md:

  - UTF-8 encoding.
  - Object keys sorted lexicographically (stdlib's ``sort_keys=True``).
  - No whitespace between tokens (``separators=(',', ':')``).
  - Booleans lowercase ``true`` / ``false``; null is ``null`` (stdlib defaults).
  - Numbers in their shortest unambiguous integer form.
  - **No floating-point**: monetary values are decimal strings, timestamps are
    ISO 8601 strings, other numerics are integers. We refuse to serialize
    ``float`` to make accidental float leakage a hard error.

Anything callers want to put in a payload that is not natively JSON-safe must
be coerced beforehand (e.g. UUID → string, Decimal → string, datetime →
ISO 8601 string). The serializer raises ``TypeError`` on unknown types rather
than silently coercing — better to fail loud than to corrupt the chain.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from uuid import UUID

JSONScalar = str | int | bool | None
JSONValue = JSONScalar | list[Any] | dict[str, Any]


class FloatNotAllowedError(TypeError):
    """Raised if a ``float`` reaches the canonical serializer.

    Floats are forbidden in audit payloads because their decimal representation
    is implementation-dependent. Canonical hashes must be reproducible.
    """


def _coerce(value: Any) -> JSONValue:
    """Recursively coerce a value into JSON-safe types per the canonical rules."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise FloatNotAllowedError(
            "Floats are not allowed in canonical payloads. Use Decimal-as-string "
            f"or int. Got: {value!r}"
        )
    if isinstance(value, Decimal):
        # Normalize trailing-zero artefacts and return as string.
        return format(value.normalize(), "f")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _coerce(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_coerce(v) for v in value]
    raise TypeError(
        f"Cannot canonicalize value of type {type(value).__name__}: {value!r}. "
        "Coerce to str/int/Decimal/UUID/dict/list before passing."
    )


def canonical_bytes(value: Any) -> bytes:
    """Return the canonical UTF-8 byte representation of ``value``."""
    coerced = _coerce(value)
    return json.dumps(
        coerced,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_string(value: Any) -> str:
    """Return the canonical string representation of ``value``."""
    return canonical_bytes(value).decode("utf-8")
