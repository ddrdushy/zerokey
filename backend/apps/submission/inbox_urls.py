from django.urls import path

from . import inbox_views

app_name = "submission_inbox"

urlpatterns = [
    path("", inbox_views.list_inbox, name="list-inbox"),
    path(
        "<uuid:item_id>/resolve/",
        inbox_views.resolve_inbox_item,
        name="resolve-inbox-item",
    ),
]
