"""CSV connector adapter (Slice 77).

The first concrete connector — universal escape hatch + the
test fixture for the propose / apply / conflict flows. Zero
auth (the upload is the authentication boundary). Ships first
so customers without an accounting system on the connector
list have a way to onboard their reference data.

Input: a CSV byte string + a ``column_mapping`` dict that maps
source CSV column headers to ZeroKey master field names. The
mapping is supplied by the operator at upload time via the
import wizard:

    column_mapping = {
        "Company Name": "legal_name",
        "Tax ID":       "tin",
        "Reg No":       "registration_number",
        "Phone":        "phone",
        ...
    }

Unmapped columns are dropped silently — common when a source
CSV has dozens of columns we don't care about.

Encoding: tries UTF-8, falls back to UTF-8 with BOM stripped,
falls back to latin-1 (which can't fail). Customers exporting
from Excel sometimes get UTF-8-with-BOM or Windows-1252; we
shouldn't bounce them at the door.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable

from apps.connectors.sync_services import ConnectorRecord

from .base import BaseConnector, ConnectorError


class CSVConnector(BaseConnector):
    """Parses an uploaded CSV against an operator-supplied column map."""

    name = "csv"

    def __init__(
        self,
        *,
        csv_bytes: bytes,
        column_mapping: dict[str, str],
        target: str = "customers",
    ) -> None:
        if target not in {"customers", "items"}:
            raise ConnectorError(
                f"target must be 'customers' or 'items', got {target!r}"
            )
        if not csv_bytes:
            raise ConnectorError("CSV upload is empty.")
        if not column_mapping:
            raise ConnectorError(
                "column_mapping is empty — at least one source-to-master "
                "field mapping is required."
            )
        self._csv_bytes = csv_bytes
        self._column_mapping = column_mapping
        self._target = target

    # --- BaseConnector interface --------------------------------------------

    def authenticate(self) -> None:
        # CSV upload is the auth. No-op.
        return None

    def fetch_customers(self) -> Iterable[ConnectorRecord]:
        if self._target != "customers":
            return iter([])
        return self._iterate_records()

    def fetch_items(self) -> Iterable[ConnectorRecord]:
        if self._target != "items":
            return iter([])
        return self._iterate_records()

    # --- internals ----------------------------------------------------------

    def _iterate_records(self) -> Iterable[ConnectorRecord]:
        text = _decode_csv(self._csv_bytes)
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise ConnectorError(
                "CSV has no header row — first line must contain "
                "column names."
            )
        # Normalise mapping keys to handle minor whitespace
        # variations between the wizard's preview + the actual
        # parsed header.
        mapping = {
            (k or "").strip(): v for k, v in self._column_mapping.items()
        }
        for index, raw in enumerate(reader, start=1):
            mapped: dict[str, str] = {}
            for src_col, target_field in mapping.items():
                value = (raw.get(src_col) or "").strip()
                if value:
                    mapped[target_field] = value
            if not mapped:
                # Empty row in the export — skip silently rather
                # than create an empty proposal entry.
                continue
            # Use either an explicit row id (if the source CSV
            # has one mapped to "source_record_id") or the row
            # number as a fallback. The id is what shows up in
            # provenance.source_record_id post-apply.
            source_id = mapped.pop("source_record_id", "") or f"row_{index}"
            yield ConnectorRecord(
                source_record_id=source_id,
                fields=mapped,
            )


def _decode_csv(csv_bytes: bytes) -> str:
    """Best-effort CSV decode.

    Excel exports vary; we accept UTF-8, UTF-8-with-BOM, and
    Windows-1252 (commonly mis-labelled as latin-1). The fallback
    chain prevents a customer from being unable to onboard
    because their CSV has a stray non-UTF-8 byte.
    """
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return csv_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    # latin-1 can't fail, but be explicit so the type checker is
    # happy.
    return csv_bytes.decode("latin-1", errors="replace")
