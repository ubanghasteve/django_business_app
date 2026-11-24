from django.apps import AppConfig


class StaffOffencesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.staff_offences'
    verbose_name = 'Staff Offences'

    def ready(self):
        import apps.staff_offences.signals  # noqa: F401
