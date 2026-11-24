from django.apps import AppConfig


class PayrollConfig(AppConfig):
    name = "apps.payroll"
    label = "payroll"
    verbose_name = "Payroll"

    def ready(self):
        # Import signals on app ready
        from . import signals  # noqa: F401

