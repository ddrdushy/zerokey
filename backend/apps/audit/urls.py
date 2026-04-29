from django.urls import path

from . import views

app_name = "audit"

urlpatterns = [
    path("stats/", views.stats, name="stats"),
    path("events/", views.list_events, name="list-events"),
    path("action-types/", views.list_action_types, name="list-action-types"),
    path("verify/", views.verify_chain_view, name="verify-chain"),
    path("verify/last/", views.latest_verification_view, name="latest-verification"),
    # Slice 88 — audit CSV export.
    path("export.csv", views.export_audit_csv_view, name="export-audit-csv"),
]
