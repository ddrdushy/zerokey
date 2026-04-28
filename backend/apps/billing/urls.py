"""Billing URL routes."""

from __future__ import annotations

from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("plans/", views.public_plans, name="public-plans"),
    path("overview/", views.billing_overview, name="overview"),
]
