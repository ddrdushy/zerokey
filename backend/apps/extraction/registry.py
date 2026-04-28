"""In-process adapter registry.

The DB-backed ``Engine`` rows are the *contract* (registered, status,
cost). The actual code that runs is in this module. Each Engine row's
``name`` matches an adapter's ``name`` attribute.

Adapters are constructed lazily — instantiating an adapter is cheap, but
some (Claude) check the environment at __init__ time, and we want
``EngineUnavailable`` to surface from the call site that asked for it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .adapters.claude_adapter import (
    STRUCTURE_ADAPTER_NAME,
    VISION_ADAPTER_NAME,
    ClaudeFieldStructureAdapter,
    ClaudeVisionAdapter,
)
from .adapters.easyocr_adapter import ADAPTER_NAME as EASYOCR_ADAPTER_NAME
from .adapters.easyocr_adapter import EasyOCRAdapter
from .adapters.ollama_adapter import ADAPTER_NAME as OLLAMA_STRUCTURE_NAME
from .adapters.ollama_adapter import OllamaFieldStructureAdapter
from .adapters.pdfplumber_adapter import ADAPTER_NAME as PDFPLUMBER_ADAPTER_NAME
from .adapters.pdfplumber_adapter import PdfplumberAdapter

# adapter name → factory. Keep this list small; new adapters land here.
_ADAPTER_FACTORIES: dict[str, Callable[[], Any]] = {
    PDFPLUMBER_ADAPTER_NAME: PdfplumberAdapter,
    VISION_ADAPTER_NAME: ClaudeVisionAdapter,
    STRUCTURE_ADAPTER_NAME: ClaudeFieldStructureAdapter,
    OLLAMA_STRUCTURE_NAME: OllamaFieldStructureAdapter,
    EASYOCR_ADAPTER_NAME: EasyOCRAdapter,
}


def get_adapter(name: str) -> Any:
    """Return an instantiated adapter by registered name.

    Raises ``KeyError`` if the adapter isn't registered (configuration drift —
    Engine row exists but no code backs it).
    """
    factory = _ADAPTER_FACTORIES.get(name)
    if factory is None:
        raise KeyError(
            f"No adapter registered under {name!r}. Known adapters: {sorted(_ADAPTER_FACTORIES)}"
        )
    return factory()


def known_adapters() -> list[str]:
    return sorted(_ADAPTER_FACTORIES)
