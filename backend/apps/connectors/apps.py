from django.apps import AppConfig


class ConnectorsConfig(AppConfig):
    name = "apps.connectors"
    label = "connectors"
    verbose_name = "Reference-data connectors"
    default_auto_field = "django.db.models.BigAutoField"
