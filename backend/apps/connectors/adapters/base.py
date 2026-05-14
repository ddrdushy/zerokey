"""Base interface for reference-data connector adapters (Slice 77).

Each concrete connector (CSV / AutoCount / Xero / etc.) is a
subclass that implements ``fetch_customers`` + ``fetch_items``.
The orchestration layer (``apps.connectors.sync_services``)
calls into this interface — adapters never call back into
sync_services to keep the dependency direction clean.

PORTAL_PLAN Phase 2 extends the contract with ``fetch_documents``
for pulling Invoices / CNs / DNs into the ingestion pipeline. The
default is a no-op so existing master-data-only adapters keep
working unchanged.

The base class enforces the connector record shape so a
mismatched fetcher fails at the type boundary rather than
silently producing malformed sync proposals.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from apps.connectors.documents import ConnectorDocument, DocumentType
from apps.connectors.sync_services import ConnectorRecord


class ConnectorError(Exception):
    """Raised by a connector when fetch fails."""


class BaseConnector(ABC):
    """Abstract base for any connector adapter.

    Concrete adapters live in ``apps.connectors.adapters.{name}``
    and are dispatched in ``connectors.dispatch.get_adapter`` by
    ``IntegrationConfig.connector_type``.
    """

    #: Unique key for the adapter, matching IntegrationConfig.ConnectorType.
    name: str = ""

    @abstractmethod
    def authenticate(self) -> None:
        """Verify the connector can talk to its source.

        For CSV this is a no-op (the upload is the auth). For OAuth
        connectors this exchanges the refresh token. Raises
        ``ConnectorError`` on failure with a customer-readable
        message.
        """

    @abstractmethod
    def fetch_customers(self) -> Iterable[ConnectorRecord]:
        """Yield connector records for the customers/debtors set."""

    def fetch_items(self) -> Iterable[ConnectorRecord]:
        """Yield connector records for the items/products set.

        Default implementation: empty. Connectors that don't expose
        an item catalog (CSV uploads with only a customers column
        set, B2C-heavy e-commerce platforms) leave this as no-op.
        """
        return iter([])

    def health_check(self) -> dict:
        """Return a small status dict for the operator UI.

        Default implementation calls authenticate() + reports OK.
        Concrete adapters override when the source exposes a
        cheaper liveness probe.
        """
        try:
            self.authenticate()
            return {"ok": True, "detail": "connector reachable"}
        except ConnectorError as exc:
            return {"ok": False, "detail": str(exc)}

    def fetch_documents(
        self, *, document_type: DocumentType, after_external_ref: str = ""
    ) -> Iterable[ConnectorDocument]:
        """Yield Invoice / CN / DN documents issued after the cursor.

        PORTAL_PLAN Phase 2 — the pull service walks this stream and
        materialises each yielded document into the ingestion pipeline.

        ``after_external_ref`` is the highest ``external_ref`` the pull
        service has already ingested. Adapters must yield in ascending
        order of their internal ref so the cursor advances
        monotonically. Implementations that have no ordering surface
        (a single CSV upload) yield every document each call — the
        pull service de-dups via the cursor.

        Default implementation: empty. Connectors that don't expose
        invoice documents (e.g. master-data-only CSV uploads) leave
        this as a no-op.
        """
        return iter([])
