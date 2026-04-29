"""Connector adapter registry."""

from __future__ import annotations

from apps.connectors.models import IntegrationConfig

from .autocount_adapter import AutoCountConnector
from .base import BaseConnector, ConnectorError
from .csv_adapter import CSVConnector

__all__ = [
    "AutoCountConnector",
    "BaseConnector",
    "CSVConnector",
    "ConnectorError",
    "get_adapter_class",
]


def get_adapter_class(connector_type: str) -> type[BaseConnector]:
    """Dispatch table — connector_type → adapter class.

    Concrete adapters land in this map as they ship (Slice 77 =
    CSV; Slice 85 = AutoCount). Unknown types raise so
    ``IntegrationConfig`` rows that reference an unimplemented
    connector fail explicitly rather than silently producing
    empty proposals.
    """
    table: dict[str, type[BaseConnector]] = {
        IntegrationConfig.ConnectorType.CSV: CSVConnector,
        IntegrationConfig.ConnectorType.AUTOCOUNT: AutoCountConnector,
    }
    klass = table.get(connector_type)
    if klass is None:
        raise ConnectorError(
            f"No adapter registered for connector_type={connector_type!r}. "
            f"Available: {sorted(table.keys())}"
        )
    return klass
