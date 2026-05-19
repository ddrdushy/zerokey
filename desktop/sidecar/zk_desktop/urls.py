"""Sidecar URL routes.

Phase 2 only ships /healthz + /version. Phase 3 will mount the
moved-from-cloud apps under /api/v1/.
"""

from __future__ import annotations

from django.http import JsonResponse
from django.urls import path


def healthz(_request) -> JsonResponse:
    return JsonResponse({"status": "ok"})


def version(_request) -> JsonResponse:
    # Phase 5 will read this from the packaged app metadata; today it's
    # hard-coded to the desktop's 0.1.0 baseline.
    return JsonResponse({"sidecar_version": "0.1.0", "phase": "2"})


urlpatterns = [
    path("healthz", healthz),
    path("version", version),
]
