from django.urls import path

from . import views

app_name = "submission"

urlpatterns = [
    path("by-job/<uuid:job_id>/", views.invoice_by_job, name="invoice-by-job"),
    path("<uuid:invoice_id>/", views.invoice_detail, name="invoice-detail"),
]
