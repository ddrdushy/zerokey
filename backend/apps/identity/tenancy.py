"""Tenant context plumbing.

The contract between application and database for multi-tenancy:

  1. At the start of every authenticated request, ``TenantContextMiddleware``
     reads the user's active organization from their session and issues
     ``SET LOCAL app.current_tenant_id = '<uuid>'`` on the connection.
  2. RLS policies on every tenant-scoped table filter rows where
     ``organization_id = current_setting('app.current_tenant_id')::uuid``.
  3. The application also filters by ``organization_id`` in service code as
     belt-and-suspenders. Either layer alone catches a leak.

Super-admin access uses a different variable, ``app.is_super_admin``, which is
set only inside an explicit elevation context that is fully audit-logged. See
SECURITY.md.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterator
from typing import Any

from django.db import connection
from django.http import HttpRequest, HttpResponse

# Postgres session variables we own. Both are reset at the end of each request.
TENANT_VAR = "app.current_tenant_id"
SUPER_ADMIN_VAR = "app.is_super_admin"


def set_tenant(tenant_id: uuid.UUID | str | None) -> None:
    """Set the tenant variable on the current DB connection.

    No-op on non-PostgreSQL backends (RLS is a Postgres feature; tests using
    SQLite-in-memory rely on application-layer filtering only).
    """
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        if tenant_id is None:
            cursor.execute(f"RESET {TENANT_VAR};")
        else:
            cursor.execute(f"SET {TENANT_VAR} = %s;", [str(tenant_id)])


def clear_tenant() -> None:
    """Reset both session variables. Always safe to call."""
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute(f"RESET {TENANT_VAR};")
        cursor.execute(f"RESET {SUPER_ADMIN_VAR};")


@contextlib.contextmanager
def tenant_context(tenant_id: uuid.UUID | str) -> Iterator[None]:
    """Run a block with a specific tenant set; restore previous state on exit."""
    set_tenant(tenant_id)
    try:
        yield
    finally:
        clear_tenant()


@contextlib.contextmanager
def super_admin_context(reason: str) -> Iterator[None]:
    """Elevate to super-admin for one block. Bypasses RLS via the SUPER_ADMIN_VAR.

    The ``reason`` is required and recorded in the audit log by the calling
    service. This function intentionally does no audit logging itself — that is
    the caller's responsibility, so the reason cannot be omitted.

    Save+restore the prior tenant variable. Without this, exiting the
    elevation block was clearing the connection's regular tenant_id (set
    by ``TenantContextMiddleware``) and subsequent reads in the same
    request returned zero rows under RLS. Bug surfaced when Slice 45
    added a customer-side service that did access-check (which elevates
    briefly) and then ran a tenant-scoped query right after.
    """
    if not reason:
        raise ValueError("super_admin_context requires a non-empty reason.")
    prior_tenant: str | None = None
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            # ``current_setting(name, true)`` returns NULL when the GUC has
            # never been SET on the session — required for worker contexts
            # where this elevation is the FIRST tenancy call on a fresh
            # connection. ``SHOW`` raises ``unrecognized configuration
            # parameter`` in that case, which broke the extraction worker.
            cursor.execute("SELECT current_setting(%s, true);", [TENANT_VAR])
            row = cursor.fetchone()
            value = row[0] if row else ""
            prior_tenant = value or None
            cursor.execute(f"SET {SUPER_ADMIN_VAR} = 'on';")
    try:
        yield
    finally:
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute(f"RESET {SUPER_ADMIN_VAR};")
            # Restore the regular tenant the middleware set, if any.
            set_tenant(prior_tenant)


class TenantContextMiddleware:
    """Set the tenant variable for every authenticated request.

    The user's active organization is held on the session under ``organization_id``;
    it is established at login time (the user picks an org if they have multiple
    memberships) and may be switched mid-session via a dedicated endpoint.

    Anonymous requests pass through with no tenant set; queries against tenant-scoped
    tables under RLS will return zero rows.
    """

    def __init__(self, get_response: Any) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        organization_id = self._resolve_tenant(request)
        if organization_id is not None:
            set_tenant(organization_id)
        try:
            response = self.get_response(request)
        finally:
            clear_tenant()
        return response

    @staticmethod
    def _resolve_tenant(request: HttpRequest) -> str | None:
        # Prefer the explicit session value; fall back to None for anonymous traffic.
        session = getattr(request, "session", None)
        if session is None:
            return None
        return session.get("organization_id")
