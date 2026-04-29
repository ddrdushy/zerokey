"""Billing URL routes."""

from __future__ import annotations

from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("plans/", views.public_plans, name="public-plans"),
    path("overview/", views.billing_overview, name="overview"),
    # Slice 63 — Stripe wiring
    path("checkout/", views.start_checkout_view, name="start-checkout"),
    path(
        "stripe-webhook/", views.stripe_webhook_view, name="stripe-webhook"
    ),
]
