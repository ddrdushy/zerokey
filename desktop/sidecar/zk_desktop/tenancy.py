"""Single-tenant shim for the desktop sidecar.

The cloud backend treats every customer-scoped row as multi-tenant
under Postgres RLS, mediated by ``apps.identity.tenancy.tenant_context``
and a ``super_admin_context`` for cross-tenant elevated reads. On the
desktop there's exactly one tenant per install — no need for RLS, no
need for context-switching.

When Phase 3 moves the cloud tenant apps into the sidecar, we need to
keep their code unchanged. So the apps still call::

    with tenant_context(organization_id):
        ...

and on the desktop the call resolves to a no-op shim that just sets a
thread-local for any code that introspects "the current org". The
``organization_id`` is also pinned at boot to the one org this install
owns (the one matched to the activated license TIN).

This file holds:
  - ``DESKTOP_ORG_ID`` — the pinned id, set at sidecar boot from the
    entitlement.
  - ``tenant_context`` / ``super_admin_context`` — no-op
    context managers matching the cloud's API surface.
  - ``current_tenant_id`` — equivalent to the cloud helper of the
    same name.

Phase 3 wires this into the moved apps either by:
  (a) replacing the cloud imports at sidecar bootstrap (monkeypatch
      ``apps.identity.tenancy`` to point at this module), or
  (b) introducing an indirection layer in the apps themselves.

Option (a) keeps the diff to the moved apps zero. We do that here.
"""

from __future__ import annotations

import contextlib
import threading
import uuid
from collections.abc import Generator

_state = threading.local()


def set_desktop_org_id(org_id: uuid.UUID | str | None) -> None:
    """Pin the org id for the lifetime of the sidecar process.

    Called once at sidecar boot, after the entitlement is verified and
    the local org is resolved (or created on first run). All
    subsequent ``tenant_context`` calls inherit this default.
    """
    _state.org_id = str(org_id) if org_id else None


def current_tenant_id() -> str | None:
    """Return the current org id — either the active context's
    override, or the pinned desktop id."""
    return getattr(_state, "active_org_id", None) or getattr(_state, "org_id", None)


@contextlib.contextmanager
def tenant_context(organization_id: uuid.UUID | str | None) -> Generator[None, None, None]:
    """No-op shim matching the cloud's ``tenant_context`` API.

    Stores the requested org id on a thread-local so reads from
    ``current_tenant_id()`` work, then restores the prior value on
    exit. Does NOT touch any database session state — there's no RLS
    to set on SQLite.
    """
    previous = getattr(_state, "active_org_id", None)
    _state.active_org_id = str(organization_id) if organization_id else None
    try:
        yield
    finally:
        _state.active_org_id = previous


@contextlib.contextmanager
def super_admin_context(reason: str = "") -> Generator[None, None, None]:
    """No-op shim matching ``super_admin_context`` from the cloud.

    On the cloud this elevates the Postgres session to bypass RLS so
    cross-tenant queries succeed. On the desktop there's no RLS to
    bypass — single tenant per install. ``reason`` is accepted and
    ignored so cloud code doesn't need to change.
    """
    yield


class TenantContextMiddleware:
    """No-op Django middleware mirroring the cloud's middleware shape.

    Phase 3 wires this in when we move the cloud apps over; for now it
    exists so a future ``MIDDLEWARE`` list including
    ``zk_desktop.tenancy.TenantContextMiddleware`` doesn't blow up.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Bind the pinned desktop org to any request that flows
        # through. Authenticated user → assume the one tenant.
        with tenant_context(current_tenant_id()):
            return self.get_response(request)
