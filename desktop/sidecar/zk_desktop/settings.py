"""Django settings for the desktop sidecar.

The sidecar shares source with the cloud backend. We add
``backend/`` to sys.path (via ``zk_desktop.boot``) so
``import apps.foo`` resolves to the cloud's modules, then monkeypatch
``apps.identity.tenancy`` to the single-tenant shim in
``zk_desktop.tenancy``.

Differences from the cloud's ``zerokey.settings.base``:

  - SQLite (not Postgres + RLS).
  - No Celery, no Redis, no S3, no KMS, no Stripe, no Sentry.
  - No DRF throttling middleware (the LAN audience is one user).
  - No corsheaders (everything is localhost).
  - No drf-spectacular (no public API docs to host).
  - INSTALLED_APPS limited to the cloud apps that are safe to load
    on the desktop (see boot.py survey notes). `apps.ingestion`,
    `apps.extraction`, `apps.enrichment`, `apps.archive`,
    `apps.billing` stay cloud-only for now.

Phase 4 will wire the entitlement middleware here (gate POSTs on
``entitlement.status == "active"`` etc).
"""

from __future__ import annotations

import os
from pathlib import Path

# CRITICAL: import boot before anything else. boot wires sys.path so
# ``apps.foo`` resolves, and monkeypatches apps.identity.tenancy to
# the desktop shim. INSTALLED_APPS below depends on both.
from zk_desktop import boot as _boot

_boot.boot()


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "ZK_DESKTOP_SECRET_KEY", "desktop-sidecar-dev-only-key-do-not-ship"
)
DEBUG = bool(os.environ.get("ZK_DESKTOP_DEBUG", ""))
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

# Per-install local data dir. Phase 4 swaps this to the OS-appropriate
# user_data_dir (Windows %LOCALAPPDATA%, macOS Library/Application
# Support, Linux ~/.local/share). For Phase 3 we keep it next to the
# sidecar so dev cycles are easy to wipe.
DESKTOP_DATA_DIR = Path(
    os.environ.get("ZK_DESKTOP_DATA_DIR", BASE_DIR / "_data")
).resolve()
DESKTOP_DATA_DIR.mkdir(parents=True, exist_ok=True)


# --- INSTALLED_APPS ---------------------------------------------------------
#
# The cloud apps live under ``apps.*`` — backend/ is on sys.path via
# boot.py. Order matters: identity defines the User model, audit
# tables it; administration depends on identity; submission depends
# on identity + administration + audit.

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    # Sessions are present so admin's IsPlatformStaff works during
    # local debugging via /django-admin/. Desktop UI doesn't use them
    # for normal flows — the desktop process bypasses auth because
    # the OS user IS the tenant.
    "django.contrib.sessions",
    "django.contrib.messages",
    # Cloud apps — same source as the production backend.
    "apps.identity",
    "apps.administration",
    "apps.audit",
    "apps.licensing",
    # Billing is loaded because apps.submission imports
    # apps.billing.decorators.feature_required. The Stripe integration
    # is lazy (no `import stripe` at module load), so this is light.
    # The desktop never bills — feature flags fall back to True.
    "apps.billing",
    "apps.submission",
    "apps.connectors",
    # apps.connectors imports apps.enrichment for customer / item
    # masters; loading the model classes requires this in INSTALLED_APPS.
    "apps.enrichment",
    "apps.notifications",
    "apps.validation",
    # Required for migration graph consistency (other apps' migrations
    # reference these). Their models load cleanly; the heavy
    # dependencies (boto3 in ingestion.services, OCR engines in
    # extraction.services) are lazily loaded inside functions — Django
    # never touches them just from INSTALLED_APPS.
    "apps.ingestion",
    "apps.extraction",
    "apps.archive",
    "apps.integrations",
]

# The cloud's User model lives in apps.identity. We re-use it on
# desktop so future identity-aware code (audit actor_id, etc) keeps
# working unchanged. Desktop has at most one real user — created
# during license activation.
AUTH_USER_MODEL = "identity.User"


MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # The desktop tenancy middleware is a no-op that pins
    # current_tenant_id from boot. Including it keeps the
    # request.context shape consistent with cloud code that reads it.
    "zk_desktop.tenancy.TenantContextMiddleware",
]

ROOT_URLCONF = "zk_desktop.urls"
WSGI_APPLICATION = "zk_desktop.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(DESKTOP_DATA_DIR / "zerokey.db"),
        # Phase 4 swaps to sqlcipher3 with a key derived from the OS
        # keychain. For Phase 3 the DB is plaintext so dev wipes are
        # one ``rm`` away.
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "Asia/Kuala_Lumpur"


# --- DRF --------------------------------------------------------------------
# Single-user desktop; no throttling, no auth. Everything that responds
# is gated by the entitlement (added in Phase 4).
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}


# --- Cloud signing endpoint (where to call for intermediary signing) -------
# Phase 3a shipped the cloud endpoint at
# POST /api/v1/licenses/sign/document/. The desktop's
# zk_desktop.cloud_signing module hits this URL when an org is in
# intermediary signing mode. Production points at zerokey.symprio.com.
ZK_LICENSE_API_BASE = os.environ.get(
    "ZK_LICENSE_API_BASE", "https://zerokey.symprio.com"
)


# --- Logging ----------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.db.backends": {"handlers": ["console"], "level": "WARNING"},
    },
}


# --- Stubs for cloud-only settings that imported modules expect ------------
# Many cloud apps reference settings at module load (e.g. an S3 bucket
# name) even if the runtime path is never reached on desktop. Declare
# them as empty here to avoid AttributeError; if a code path actually
# tries to use one of these, it'll fail loudly at call time.

AWS_REGION = ""
AWS_S3_DOCUMENTS_BUCKET = ""
AWS_KMS_KEY_ID = ""
STRIPE_SECRET_KEY = ""
STRIPE_WEBHOOK_SECRET = ""
CELERY_BROKER_URL = ""
CELERY_RESULT_BACKEND = ""
SENTRY_DSN = ""
LICENSING_ED25519_PRIVATE_KEY_PEM = ""
LICENSING_ED25519_PUBLIC_KEY_PEM = ""

# Encryption key for apps.administration.fields.EncryptedTextField.
# In production this is a base64 Fernet key from KMS; on desktop we
# generate one from a value pinned in the OS keychain at first run
# (Phase 4). For Phase 3 dev, an env-supplied or hard-coded dev key
# keeps tests + first-boot working.
FIELD_ENCRYPTION_KEY = os.environ.get(
    "ZK_DESKTOP_FIELD_KEY",
    # 32 bytes urlsafe-base64 = Fernet key. THIS KEY IS PUBLIC — only
    # for dev. Production replaces it at install time.
    "Z2VuZXJhdGVfYV9zZWN1cmVfa2V5X2Zvcl9wcm9kdWN0aW9uX3VzZQ==",
)
