from django.apps import AppConfig


class MailingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.mailing'
    verbose_name = 'Bulk Mailing'

    def ready(self):
        from . import signals  # noqa: F401 - registers post_migrate to sync mailing perms to Company Admin
