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


def install_remote_signer_for_intermediary() -> None:
    """Wrap apps.submission.certificates.ensure_certificate so the
    intermediary branch returns a remote-signer proxy on the desktop.

    The cloud's ensure_certificate dispatches on Organization.signing_mode.
    For INTERMEDIARY it normally loads the platform-level private key
    from SystemSetting (cloud only) — which the desktop has no access
    to. We wrap the function so that, after the cloud's dispatch picks
    the intermediary branch, we substitute the private_key with our
    RemoteRsaSigner. The caller's downstream code (XAdES signing) calls
    ``.sign()`` and gets the cloud-signed bytes back transparently.

    Self-signed orgs are unaffected — those use a local cert on the
    desktop's own filesystem like before.
    """
    # Defer the imports until after sys.path is wired.
    from apps.submission import certificates as cloud_certificates
    from zk_desktop import remote_signer

    original = cloud_certificates.ensure_certificate

    def patched(*, organization_id):
        loaded = original(organization_id=organization_id)
        if loaded.kind != "intermediary":
            return loaded
        # Swap in the remote signer. dataclasses.replace() preserves
        # frozen-ness; we keep the cert + cert_pem so XAdES can still
        # build KeyInfo, but the private_key field becomes a proxy
        # that round-trips through the cloud.
        import dataclasses

        proxy = remote_signer.RemoteRsaSigner(cert_serial_hex=loaded.serial_hex)
        return dataclasses.replace(loaded, private_key=proxy)

    cloud_certificates.ensure_certificate = patched
    LOG.info(
        "zerokey.sidecar.boot: apps.submission.certificates.ensure_certificate "
        "patched → remote signer for intermediary orgs"
    )


def boot() -> None:
    """One-call entrypoint — invoked from settings before INSTALLED_APPS."""
    add_cloud_apps_to_sys_path()
    install_tenancy_shim()
    # The remote-signer patch runs lazily on first invocation because
    # it depends on the cloud submission module being importable,
    # which needs INSTALLED_APPS to be loaded first. We register it as
    # a post-app-ready hook instead — see zk_desktop.apps.SidecarConfig.
