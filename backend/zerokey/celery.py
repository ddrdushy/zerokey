"""Celery application bootstrap.

Per ARCHITECTURE.md: separate queues by priority, idempotent tasks, exponential
backoff with jitter, dead-letter handling. Task implementations live inside their
owning bounded-context app.
"""

from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "zerokey.settings.dev")

app = Celery("zerokey")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self) -> str:
    return f"Request: {self.request!r}"
