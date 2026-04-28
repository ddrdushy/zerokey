"""Integrations URL routes."""

from __future__ import annotations

from django.urls import path

from . import views

app_name = "integrations"

urlpatterns = [
    path("webhooks/", views.webhooks, name="webhooks"),
    path("webhooks/<uuid:webhook_id>/", views.revoke_webhook, name="webhook-revoke"),
    path(
        "webhooks/<uuid:webhook_id>/test/",
        views.test_webhook,
        name="webhook-test",
    ),
    path("deliveries/", views.webhook_deliveries, name="deliveries"),
]
