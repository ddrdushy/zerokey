from django.urls import path

from . import views

app_name = "connectors"

urlpatterns = [
    path("configs/", views.configs, name="configs"),
    path(
        "configs/<uuid:config_id>/",
        views.config_delete,
        name="config-delete",
    ),
    path(
        "configs/<uuid:config_id>/sync-csv/",
        views.sync_csv,
        name="sync-csv",
    ),
    # Slice 85 — AutoCount upload (no column-mapping required).
    # Slice 98 — same endpoint handles SQL Account + Sage UBS;
    # the per-type URLs are aliases for FE clarity.
    path(
        "configs/<uuid:config_id>/sync-autocount/",
        views.sync_autocount,
        name="sync-autocount",
    ),
    path(
        "configs/<uuid:config_id>/sync-sql_account/",
        views.sync_autocount,
        name="sync-sql-account",
    ),
    path(
        "configs/<uuid:config_id>/sync-sage_ubs/",
        views.sync_autocount,
        name="sync-sage-ubs",
    ),
    path(
        "proposals/<uuid:proposal_id>/",
        views.proposal_detail,
        name="proposal-detail",
    ),
    path(
        "proposals/<uuid:proposal_id>/apply/",
        views.proposal_apply,
        name="proposal-apply",
    ),
    path(
        "proposals/<uuid:proposal_id>/revert/",
        views.proposal_revert,
        name="proposal-revert",
    ),
    path("conflicts/", views.list_conflicts, name="conflicts"),
    path(
        "conflicts/<uuid:conflict_id>/resolve/",
        views.conflict_resolve,
        name="conflict-resolve",
    ),
    path("locks/", views.lock_create, name="lock-create"),
    path("locks/unlock/", views.lock_remove, name="lock-remove"),
]
