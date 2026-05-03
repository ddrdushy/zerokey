"""Project-level middleware.

Slice 104 — request-id and observability plumbing per
``API_DESIGN.md`` ("Every response carries an ``X-Request-Id`` header
that customers and operators can quote to correlate") and
``OPERATIONS.md`` ("Logs include the request ID, the user ID, the
tenant ID …").

The middleware:

  * Accepts an inbound ``X-Request-Id`` if present (trusted upstream
    edge proxy may set one). Otherwise mints a UUID4.
  * Stores the value on ``request.request_id`` so views + serializers
    can quote it (the error envelope does this).
  * Echoes it on the response.
  * Pushes it onto a ``contextvars.ContextVar`` so any log line
    emitted during request handling can pull it without the caller
    threading it through. Celery tasks inherit the same var when the
    parent enqueues with the supplied header (see
    ``zerokey.celery``).
"""

from __future__ import annotations

import contextvars
import logging
import re
import uuid
from typing import Any, Callable

from django.http import HttpRequest, HttpResponse

# Public so other modules (logging filter, exception handler, Celery
# task base) can read the active request id without a request handle.
_request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

# Loose acceptance pattern — accept any printable ASCII up to 64 chars.
# Reject anything longer or anything with control chars to keep log
# lines safe.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,64}$")


def get_request_id() -> str | None:
    """Return the request id active on the current contextvar (or None)."""
    return _request_id_var.get()


def set_request_id(value: str | None) -> contextvars.Token[str | None]:
    """Push a request id onto the contextvar; return the reset token."""
    return _request_id_var.set(value)


class RequestIdMiddleware:
    """Mint / echo an ``X-Request-Id`` header on every request.

    Order in MIDDLEWARE: install BEFORE any middleware that might log
    (so logs already see the id) but AFTER ``SecurityMiddleware``.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        incoming = request.META.get("HTTP_X_REQUEST_ID", "")
        request_id = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        request.request_id = request_id  # type: ignore[attr-defined]
        token = _request_id_var.set(request_id)
        try:
            response = self.get_response(request)
        finally:
            _request_id_var.reset(token)
        response["X-Request-Id"] = request_id
        return response


class RequestIdLogFilter(logging.Filter):
    """Inject ``request_id`` into every log record so JSON logs carry it."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_var.get() or "-"
        return True
