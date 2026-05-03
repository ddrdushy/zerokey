"""Celery application bootstrap.

Per ARCHITECTURE.md: separate queues by priority, idempotent tasks, exponential
backoff with jitter, dead-letter handling. Task implementations live inside their
owning bounded-context app.
"""

from __future__ import annotations

import os

from celery import Celery
from celery.signals import before_task_publish, task_postrun, task_prerun

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "zerokey.settings.dev")

app = Celery("zerokey")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


# --- Slice 104 — request_id propagation ----------------------------------------------
# Pull the active request id off the contextvar when the parent
# enqueues, stash it as a custom task header, then re-push it onto
# the worker's contextvar before the task body runs. The result: a
# single request id stitches the inbound HTTP log line to every
# downstream task log line — quoting it back to a customer is
# enough to find the whole trace.

# Worker-side reset tokens, keyed by task id. Module-level dict is
# safe because Celery dispatches one task at a time per worker
# process; the prefork model isolates these.
_token_by_task_id: dict[str, object] = {}


@before_task_publish.connect
def _propagate_request_id_on_publish(headers: dict | None = None, **_: object) -> None:
    from zerokey.middleware import get_request_id

    rid = get_request_id()
    if rid and headers is not None:
        headers["x_request_id"] = rid


@task_prerun.connect
def _restore_request_id_in_worker(task_id: str, task: object, **_: object) -> None:
    from zerokey.middleware import set_request_id

    rid = None
    request = getattr(task, "request", None)
    if request is not None:
        rid = getattr(request, "x_request_id", None) or (
            (request.headers or {}).get("x_request_id") if hasattr(request, "headers") else None
        )
    if rid:
        _token_by_task_id[task_id] = set_request_id(rid)


@task_postrun.connect
def _clear_request_id_in_worker(task_id: str, **_: object) -> None:
    from zerokey.middleware import _request_id_var

    token = _token_by_task_id.pop(task_id, None)
    if token is not None:
        try:
            _request_id_var.reset(token)  # type: ignore[arg-type]
        except (LookupError, ValueError):
            pass


@app.task(bind=True)
def debug_task(self) -> str:
    return f"Request: {self.request!r}"
