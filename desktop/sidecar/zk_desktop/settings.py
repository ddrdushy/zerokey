"""Django settings for the desktop sidecar.

Deliberately tiny — Phase 2 only needs Django up enough to serve
``/healthz``. Phase 3 lands the real tenant apps + SQLite + SQLCipher
encryption-at-rest.

Key differences from the cloud backend:
  - SQLite, not Postgres. No RLS (single-tenant per install).
  - No Celery, no Redis, no S3, no KMS, no Stripe.
  - The sidecar listens only on 127.0.0.1; ALLOWED_HOSTS reflects that.
  - DEBUG is off — the renderer doesn't need stack-trace pages, and
    we never want them in a packaged build.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Random per-install secret used for Django session/CSRF crypto.
# Phase 3 will mint and persist this into the OS keychain on first run.
SECRET_KEY = os.environ.get(
    "ZK_DESKTOP_SECRET_KEY", "desktop-sidecar-dev-only-key-do-not-ship"
)
DEBUG = False
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
]

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "zk_desktop.urls"
WSGI_APPLICATION = "zk_desktop.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        # Phase 3 swaps this to ``user_data_dir() / 'zerokey.db'`` with
        # SQLCipher. For Phase 2 we don't migrate anything yet, so
        # in-memory is fine.
        "NAME": ":memory:",
    }
}

USE_TZ = True
TIME_ZONE = "Asia/Kuala_Lumpur"  # matches the customer base
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}
