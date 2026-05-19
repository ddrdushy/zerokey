"""Sidecar entrypoint — what Electron's main process actually spawns.

Boots the Django WSGI app under ``wsgiref`` listening on the port the
parent process picked. Single-threaded is fine for now (one user per
install, very low concurrency). Phase 5 swaps this for waitress to
get a thread pool when we package.

Why wsgiref instead of gunicorn / uvicorn:
  - One file, no extra deps, ships cleanly inside PyInstaller.
  - We don't need socket-leveling features in a single-tenant local
    server bound to 127.0.0.1.

Phase 3 will switch the bound apps to the real tenant Django apps;
this entrypoint and its argparse contract stay the same.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from wsgiref.simple_server import WSGIServer, make_server

LOG = logging.getLogger("zerokey.sidecar")

# Make sure the sidecar directory is on sys.path so 'zk_desktop' imports.
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def _build_app():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "zk_desktop.settings")
    import django  # imported here, not at module load, so import errors
                   # surface in the parent's stderr capture rather than
                   # at PyInstaller bootstrap time.

    django.setup()
    from zk_desktop.wsgi import application

    return application


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("ZK_SIDECAR_PORT", "0")),
        help="Port to bind on 127.0.0.1. 0 lets the OS pick.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    app = _build_app()
    server: WSGIServer = make_server("127.0.0.1", args.port, app)
    actual_port = server.server_port
    LOG.info("zerokey.sidecar listening on http://127.0.0.1:%d", actual_port)
    # Print so the Electron parent can detect ready, even without a
    # /healthz round-trip (useful when debugging).
    print(f"sidecar-ready port={actual_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
