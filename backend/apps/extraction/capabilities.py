"""Pluggable capability interfaces for the engine registry.

Per ARCHITECTURE.md and ENGINE_REGISTRY.md, every interaction with an OCR
engine or LLM goes through a small set of capability interfaces. Adapters
implement them; the router picks one per job.

Phase 2 ships three capabilities:

  - ``TextExtract``     — raw text from a document (native PDF / scanned PDF / image)
  - ``VisionExtract``   — structured fields directly from an image
  - ``FieldStructure``  — structured fields from raw text + a target schema

``Embed`` and ``Classify`` are documented in the spec but defer to a later
slice; they are not required for the upload → extraction → review path.

Confidence handling
-------------------
Each engine returns a normalized ``confidence`` value in [0.0, 1.0]. Per the
spec, vendor confidences are not directly comparable; per-engine calibration
is offline work and recalibrates the curve weekly. For Phase 2 we trust the
adapter's reported confidence; calibration tables land later.

Per-engine cost
---------------
Every call returns a ``cost_micros`` integer (USD micros) so the EngineCall
row can attribute spend per Invoice. Zero is a valid value (in-process
engines like pdfplumber).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TextExtractResult:
    """Output of TextExtract: a flat string + per-page confidence."""

    text: str
    confidence: float
    page_count: int = 1
    cost_micros: int = 0
    # Vendor-native diagnostics (not part of the audit-log content hash).
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StructuredExtractResult:
    """Output of VisionExtract or FieldStructure: a flat dict of fields.

    ``fields`` is a dict of ``{lhdn_field_code: value_string}``. ``per_field_confidence``
    is a parallel dict in [0.0, 1.0]. Subsequent slices map this onto the
    Invoice / LineItem entities.
    """

    fields: dict[str, str]
    per_field_confidence: dict[str, float]
    overall_confidence: float
    cost_micros: int = 0
    diagnostics: dict[str, Any] = field(default_factory=dict)


class EngineUnavailable(Exception):
    """Raised by an adapter when its dependencies (API key, library) are missing."""


class TextExtractEngine(ABC):
    """Capability: extract raw text from a document."""

    name: str  # adapter id, used to look up the Engine row.

    @abstractmethod
    def extract_text(self, *, body: bytes, mime_type: str) -> TextExtractResult: ...


class VisionExtractEngine(ABC):
    """Capability: extract structured fields from an image without going through text."""

    name: str

    @abstractmethod
    def extract_vision(
        self, *, body: bytes, mime_type: str, target_schema: list[str]
    ) -> StructuredExtractResult: ...


class FieldStructureEngine(ABC):
    """Capability: structure raw text into a target schema."""

    name: str

    @abstractmethod
    def structure_fields(
        self, *, text: str, target_schema: list[str]
    ) -> StructuredExtractResult: ...
