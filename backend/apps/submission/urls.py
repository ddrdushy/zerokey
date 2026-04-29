from django.urls import path

from . import views

app_name = "submission"

urlpatterns = [
    path("", views.list_invoices, name="list-invoices"),
    path("by-job/<uuid:job_id>/", views.invoice_by_job, name="invoice-by-job"),
    path("<uuid:invoice_id>/", views.invoice_detail, name="invoice-detail"),
    # Slice 59B — LHDN lifecycle gestures
    path(
        "<uuid:invoice_id>/submit-to-lhdn/",
        views.submit_invoice_to_lhdn_view,
        name="submit-to-lhdn",
    ),
    path(
        "<uuid:invoice_id>/cancel-lhdn/",
        views.cancel_invoice_lhdn_view,
        name="cancel-lhdn",
    ),
    path(
        "<uuid:invoice_id>/poll-lhdn/",
        views.poll_invoice_lhdn_view,
        name="poll-lhdn",
    ),
    # Slice 61 — issue an amendment (Credit Note today)
    path(
        "<uuid:invoice_id>/issue-credit-note/",
        views.issue_credit_note_view,
        name="issue-credit-note",
    ),
]
