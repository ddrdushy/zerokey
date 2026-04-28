from django.urls import path

from . import views

app_name = "audit"

urlpatterns = [
    path("stats/", views.stats, name="stats"),
    path("events/", views.list_events, name="list-events"),
    path("action-types/", views.list_action_types, name="list-action-types"),
]
