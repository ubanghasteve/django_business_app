from django.apps import AppConfig


class SyncApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.sync_api'
    verbose_name = 'Sync API (Offline-First v1)'
