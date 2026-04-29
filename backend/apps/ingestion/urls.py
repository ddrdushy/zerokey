from django.urls import path

from . import views

app_name = "ingestion"

urlpatterns = [
    path("jobs/", views.list_jobs, name="list-jobs"),
    path("jobs/upload/", views.upload, name="upload"),
    path("throughput/", views.throughput, name="throughput"),
    path("jobs/<uuid:job_id>/", views.job_detail, name="job-detail"),
    # Slice 64 — email-forward inbound + per-org inbox address.
    path("inbox/address/", views.inbox_address_view, name="inbox-address"),
    path(
        "inbox/email-forward/",
        views.email_forward_webhook_view,
        name="email-forward-webhook",
    ),
]
