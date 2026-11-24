from django.apps import AppConfig


def _configure_sqlite(sender, connection, **kwargs):
    """Allow concurrent reads while a write is in progress (local SQLite only)."""
    if connection.vendor != 'sqlite':
        return
    cursor = connection.cursor()
    cursor.execute('PRAGMA journal_mode=WAL;')
    cursor.execute('PRAGMA busy_timeout=60000;')
    cursor.execute('PRAGMA synchronous=NORMAL;')


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.core'
    verbose_name = 'Core'
    
    def ready(self):
        import apps.core.signals  # noqa: F401
        from apps.core.realtime.signals import connect_realtime_signals
        connect_realtime_signals()
        from django.db.backends.signals import connection_created
        connection_created.connect(_configure_sqlite, dispatch_uid='core.configure_sqlite')