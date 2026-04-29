"""Items UI surface (Slice 83). Mounted at ``/api/v1/items/``."""

from django.urls import path

from . import views

app_name = "items"

urlpatterns = [
    path("", views.list_items, name="list-items"),
    path("<uuid:item_id>/", views.item_detail, name="item-detail"),
]
