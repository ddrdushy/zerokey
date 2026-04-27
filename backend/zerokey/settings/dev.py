"""Development settings — used for local docker-compose and CI."""

from .base import *  # noqa: F401,F403
from .base import INSTALLED_APPS, MIDDLEWARE  # explicit re-import for mutation

DEBUG = True

INSTALLED_APPS = [*INSTALLED_APPS]
MIDDLEWARE = [*MIDDLEWARE]

# Permissive CORS for local frontend
CORS_ALLOW_ALL_ORIGINS = True

# Eager Celery in tests is set in the test settings; in dev we want real queues.
