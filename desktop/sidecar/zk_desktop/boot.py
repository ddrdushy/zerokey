"""Boot-time monkeypatches for the desktop sidecar.

We import the cloud's Django apps directly from ``backend/apps/`` so
the desktop and cloud share source. The cloud apps assume a few
things the desktop doesn't have:

  - A real ``apps.identity.tenancy.tenant_context`` that flips Postgres
    RLS session state. Desktop is single-tenant on SQLite — no RLS.
  - A real ``apps.identity.tenancy.super_admin_context`` that elevates
    a session to bypass RLS. Same — no RLS to bypass.
  - A ``apps.identity.tenancy.TenantContextMiddleware`` that resolves
    the active tenant from the request session. Desktop pins one
    tenant at boot from the license entitlement.

Rather than touching the cloud's source, we monkeypatch
``apps.identity.tenancy`` IN MEMORY before Django loads the apps. The
shim lives in ``zk_desktop.tenancy``.

Order matters: this module MUST be imported before Django's app
registry walks `INSTALLED_APPS` and before any view code resolves
``from apps.identity.tenancy import tenant_context``. The sidecar
settings module imports us at the top.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

LOG = logging.getLogger("zerokey.sidecar.boot")


def add_cloud_apps_to_sys_path() -> None:
    """Put ``backend/`` on sys.path so ``import apps.foo`` resolves to
    the cloud source tree.

    This is the shared-source pattern: desktop and cloud both load
    the same modules. Drift is impossible. In Phase 5 the
    PyInstaller build snapshots the cloud source into the bundle.
    """
    here = Path(__file__).resolve()
    # desktop/sidecar/zk_desktop/boot.py → ../../../ → repo root → backend/
    repo_root = here.parents[3]
    backend = repo_root / "backend"
    if not (backend / "apps").is_dir():
        LOG.warning(
            "zerokey.sidecar.boot: %s/apps not found — "
            "sidecar will only load the desktop's own modules",
            backend,
        )
        return
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))


def install_tenancy_shim() -> None:
    """Replace ``apps.identity.tenancy`` with the desktop's no-op shim.

    Done by injecting an entry into ``sys.modules`` keyed by the cloud
    module path; any subsequent ``from apps.identity.tenancy import X``
    resolves to our module. Idempotent.
    """
    from zk_desktop import tenancy as desktop_tenancy

    # If the cloud module has already been imported (unlikely this
    # early), we still wins because we overwrite the sys.modules entry.
    sys.modules["apps.identity.tenancy"] = desktop_tenancy
    LOG.info("zerokey.sidecar.boot: apps.identity.tenancy → zk_desktop.tenancy")


def boot() -> None:
    """One-call entrypoint — invoked from settings before INSTALLED_APPS."""
    add_cloud_apps_to_sys_path()
    install_tenancy_shim()
