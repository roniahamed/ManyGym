from django.apps import AppConfig


class MembersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.members"
    verbose_name = "Members & Subscriptions"

    def ready(self):
        import apps.members.signals  # noqa: F401

