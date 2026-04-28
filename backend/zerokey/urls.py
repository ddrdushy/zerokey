"""Root URL configuration.

API versioning is path-based (``/api/v1/``) per API_DESIGN.md.
"""

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)


def healthz(_request) -> JsonResponse:
    """Liveness probe. Cheap; does not touch DB or Redis."""
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthz, name="healthz"),
    # OpenAPI / docs
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/v1/schema/swagger/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger",
    ),
    path(
        "api/v1/schema/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),
    # Bounded-context routes mount under /api/v1/ as they are added.
    path("api/v1/identity/", include("apps.identity.urls")),
    path("api/v1/ingestion/", include("apps.ingestion.urls")),
    path("api/v1/invoices/", include("apps.submission.urls")),
    path("api/v1/customers/", include("apps.enrichment.urls")),
    path("api/v1/engines/", include("apps.extraction.urls")),
    path("api/v1/inbox/", include("apps.submission.inbox_urls")),
    path("api/v1/audit/", include("apps.audit.urls")),
    path("api/v1/admin/", include("apps.administration.urls")),
]
