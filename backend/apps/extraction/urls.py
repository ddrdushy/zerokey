from django.urls import path

from . import views

app_name = "extraction"

urlpatterns = [
    path("", views.engine_summary, name="engine-summary"),
    path("calls/", views.engine_calls, name="engine-calls"),
]
