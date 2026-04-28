"""Base Django settings — shared across all environments.

Per ARCHITECTURE.md, this monolith is organized into bounded-context apps living under
``apps.*``. Each app exposes a service-layer interface; cross-context model imports are
forbidden.
"""

from __future__ import annotations

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
)

# Read .env if present (dev convenience; production injects env vars directly).
env_file = BASE_DIR.parent / ".env"
if env_file.exists():
    environ.Env.read_env(str(env_file))

SECRET_KEY = env("DJANGO_SECRET_KEY", default="insecure-base-key-override-me")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# --- Applications ---------------------------------------------------------------------

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "corsheaders",
    "drf_spectacular",
]

# Bounded-context apps (see ARCHITECTURE.md). Order matches the document's list.
LOCAL_APPS = [
    "apps.identity",
    "apps.billing",
    "apps.ingestion",
    "apps.extraction",
    "apps.enrichment",
    "apps.validation",
    "apps.submission",
    "apps.archive",
    "apps.audit",
    "apps.integrations",
    "apps.administration",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# --- Middleware -----------------------------------------------------------------------

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.identity.tenancy.TenantContextMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "zerokey.urls"
WSGI_APPLICATION = "zerokey.wsgi.application"
ASGI_APPLICATION = "zerokey.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database -------------------------------------------------------------------------
# Per DATA_MODEL.md and ARCHITECTURE.md, multi-tenancy is enforced via PostgreSQL RLS.
# The application connects as a non-superuser role so RLS policies actually apply.

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": env("POSTGRES_HOST", default="postgres"),
        "PORT": env("POSTGRES_PORT", default="5432"),
        "NAME": env("POSTGRES_DB", default="zerokey"),
        "USER": env("POSTGRES_APP_USER", default=env("POSTGRES_USER", default="zerokey")),
        "PASSWORD": env(
            "POSTGRES_APP_PASSWORD",
            default=env("POSTGRES_PASSWORD", default="zerokey_dev"),
        ),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {
            "application_name": "zerokey-backend",
        },
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Custom User model — UUID PK, email-based auth (see apps.identity.models.User).
AUTH_USER_MODEL = "identity.User"

# --- Cache / sessions -----------------------------------------------------------------

# --- Object storage (MinIO in dev, AWS S3 in prod) ------------------------------------
# See apps.integrations.storage for the bucket/key conventions.

S3_ENDPOINT_URL = env("S3_ENDPOINT_URL", default="")
S3_PUBLIC_ENDPOINT_URL = env("S3_PUBLIC_ENDPOINT_URL", default="")
S3_REGION = env("S3_REGION", default="ap-southeast-5")
S3_ACCESS_KEY = env("S3_ACCESS_KEY", default="")
S3_SECRET_KEY = env("S3_SECRET_KEY", default="")
S3_BUCKET_UPLOADS = env("S3_BUCKET_UPLOADS", default="zerokey-uploads")
S3_BUCKET_SIGNED = env("S3_BUCKET_SIGNED", default="zerokey-signed")
S3_BUCKET_EXPORTS = env("S3_BUCKET_EXPORTS", default="zerokey-exports")

REDIS_URL = env("REDIS_URL", default="redis://redis:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    },
}

SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
SESSION_CACHE_ALIAS = "default"

# --- Auth & passwords -----------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Internationalization -------------------------------------------------------------

LANGUAGE_CODE = "en"
TIME_ZONE = "Asia/Kuala_Lumpur"
USE_I18N = True
USE_TZ = True

# Per VISUAL_IDENTITY.md the four launch languages are EN, BM, ZH, TA.
LANGUAGES = [
    ("en", "English"),
    ("ms", "Bahasa Malaysia"),
    ("zh-hans", "简体中文"),
    ("ta", "தமிழ்"),
]

# --- Static files ---------------------------------------------------------------------

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- DRF ------------------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        # API-key auth runs first so a Bearer header short-circuits
        # the session lookup. Session auth is the fallback for
        # browser-based requests with a Django session cookie.
        "apps.identity.api_key_auth.APIKeyAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
}

SPECTACULAR_SETTINGS = {
    "TITLE": "ZeroKey API",
    "DESCRIPTION": "ZeroKey REST API. See API_DESIGN.md for conventions.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# --- Celery ---------------------------------------------------------------------------

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://redis:6379/1")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://redis:6379/2")
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_TASK_ACKS_LATE = True
# Queues by priority (per ARCHITECTURE.md). The signing service runs on its
# own queue; Celery auto-creates queues from task definitions, so we don't
# need to enumerate them here.
CELERY_TASK_DEFAULT_QUEUE = "default"

# --- Celery Beat (scheduled tasks) -----------------------------------------------------
# Scheduled (recurring) tasks live here. The beat container reads this dict
# and dispatches at the configured interval. Each entry pins to a queue that
# matches the worker fleet so the task is picked up.

# The audit chain verification cadence. Default 6 hours — frequent enough to
# catch tampering within a meaningful window, cheap enough that even a multi-
# million-event chain finishes well under the interval. Tunable per-environment
# via env so dev can dial it down to seconds for live testing.
AUDIT_CHAIN_VERIFY_SECONDS = env.int("AUDIT_CHAIN_VERIFY_SECONDS", default=6 * 60 * 60)

CELERY_BEAT_SCHEDULE = {
    "audit.verify_audit_chain": {
        "task": "audit.verify_audit_chain",
        "schedule": float(AUDIT_CHAIN_VERIFY_SECONDS),
        "options": {"queue": "low"},
    },
}

# --- Logging --------------------------------------------------------------------------
# Sensitive data is never logged (CLAUDE.md). Loggers must rely on field-level redaction
# at the call site; the formatter does not redact retroactively.

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(name)s %(levelname)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "celery": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# --- CORS -----------------------------------------------------------------------------

CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=["http://localhost:3000"],
)
