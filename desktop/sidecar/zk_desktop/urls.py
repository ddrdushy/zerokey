"""Sidecar URL routes.

Reuses the cloud app URL modules wherever possible — same paths the
cloud serves, so a future migration of the renderer to the sidecar's
URL is a config flip rather than a code change.

We deliberately do NOT mount the cloud's billing or admin URL trees;
those stay cloud-only.
"""

from __future__ import annotations

from django.http import JsonResponse
from django.urls import include, path


def healthz(_request) -> JsonResponse:
    return JsonResponse({"status": "ok"})


def version(_request) -> JsonResponse:
    return JsonResponse({"sidecar_version": "0.1.0", "phase": "3b"})


urlpatterns = [
    # Lifecycle probes the Electron parent uses.
    path("healthz", healthz),
    path("version", version),
    # Phase 3b — mount the cloud tenant URLs. The desktop app speaks
    # to these directly via http://127.0.0.1:<port>. The renderer's
    # api client (when wired in Phase 5) will hit the same paths.
    path("api/v1/identity/", include("apps.identity.urls")),
    path("api/v1/invoices/", include("apps.submission.urls")),
    path("api/v1/audit/", include("apps.audit.urls")),
    path("api/v1/connectors/", include("apps.connectors.urls")),
    path("api/v1/inbox/", include("apps.submission.inbox_urls")),
]
