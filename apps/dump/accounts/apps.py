from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.accounts'
    verbose_name = 'Accounts'

    def ready(self):
        # Import signal handlers that enforce tenant-aware group membership and
        # ensure every user is linked to an account. Importing here avoids
        # side effects at module import time and is the recommended pattern
        # for Django apps.
        from . import signals  # noqa: F401

