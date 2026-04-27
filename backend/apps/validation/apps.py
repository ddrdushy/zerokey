from django.apps import AppConfig


class ValidationConfig(AppConfig):
    name = "apps.validation"
    label = "validation"
    verbose_name = "Validation"
    default_auto_field = "django.db.models.BigAutoField"
