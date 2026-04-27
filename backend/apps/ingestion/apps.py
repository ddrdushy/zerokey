from django.apps import AppConfig


class IngestionConfig(AppConfig):
    name = "apps.ingestion"
    label = "ingestion"
    verbose_name = "Ingestion"
    default_auto_field = "django.db.models.BigAutoField"
