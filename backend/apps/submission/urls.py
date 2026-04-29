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
    # Slice 61 + 62 — issue amendments (CN / DN / RN)
    path(
        "<uuid:invoice_id>/issue-credit-note/",
        views.issue_credit_note_view,
        name="issue-credit-note",
    ),
    path(
        "<uuid:invoice_id>/issue-debit-note/",
        views.issue_debit_note_view,
        name="issue-debit-note",
    ),
    path(
        "<uuid:invoice_id>/issue-refund-note/",
        views.issue_refund_note_view,
        name="issue-refund-note",
    ),
    # Slice 84 — signed-document download (decrypted bytes).
    path(
        "<uuid:invoice_id>/signed-document/",
        views.signed_document_download_view,
        name="signed-document",
    ),
    # Slice 87 — two-step approval workflow.
    path("approvals/pending/", views.pending_approvals_view, name="approvals-pending"),
    path(
        "<uuid:invoice_id>/request-approval/",
        views.request_approval_view,
        name="request-approval",
    ),
    path(
        "approvals/<uuid:approval_id>/approve/",
        views.approve_invoice_view,
        name="approval-approve",
    ),
    path(
        "approvals/<uuid:approval_id>/reject/",
        views.reject_invoice_view,
        name="approval-reject",
    ),
]
