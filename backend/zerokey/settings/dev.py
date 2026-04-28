"""Development settings — used for local docker-compose and CI."""

from .base import *  # noqa: F403
from .base import INSTALLED_APPS, MIDDLEWARE  # explicit re-import for mutation

DEBUG = True

INSTALLED_APPS = [*INSTALLED_APPS]
MIDDLEWARE = [*MIDDLEWARE]

# CORS for local frontend. When credentials are sent (session cookies), the
# browser refuses ``Access-Control-Allow-Origin: *`` — the origin must be
# explicit. So instead of ALLOW_ALL we whitelist localhost:3000 and let cookies
# through.
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
# CSRF needs the same trust list so the X-CSRFToken header validates.
CSRF_TRUSTED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

# Eager Celery in tests is set in the test settings; in dev we want real queues.
