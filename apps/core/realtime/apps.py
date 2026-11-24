from django.apps import AppConfig


class RealtimeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.core.realtime'
    verbose_name = 'Realtime Sync'

    def ready(self):
        # Signals are connected from apps.core.apps.CoreConfig.ready()
        pass