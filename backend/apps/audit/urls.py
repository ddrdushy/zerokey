from django.urls import path

from . import views

app_name = "audit"

urlpatterns = [
    path("stats/", views.stats, name="stats"),
]
