from django.apps import AppConfig


class IdentityConfig(AppConfig):
    name = "apps.identity"
    label = "identity"
    verbose_name = "Identity"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        # Wire auth signal handlers — login/logout/login-failed → audit log.
        from . import signals  # noqa: F401
