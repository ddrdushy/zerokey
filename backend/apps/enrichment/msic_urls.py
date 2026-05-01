"""URLs for MSIC catalog suggestions (Slice 94)."""

from django.urls import path

from . import views

app_name = "msic"

urlpatterns = [
    path("suggest/", views.msic_suggest_view, name="suggest"),
]
