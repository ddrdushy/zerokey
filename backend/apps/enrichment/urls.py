from django.urls import path

from . import views

app_name = "enrichment"

urlpatterns = [
    path("", views.list_customers, name="list-customers"),
    path("<uuid:customer_id>/", views.customer_detail, name="customer-detail"),
]
