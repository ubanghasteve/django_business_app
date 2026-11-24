from django.apps import AppConfig
from django.db.models.signals import post_migrate


class ExpenseConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.expense'
    verbose_name = 'Expense'

    def ready(self):
        import apps.expense.signals
        from django.dispatch import receiver
        @receiver(post_migrate)
        def _sync_expense_permissions(sender, **kwargs):
            if sender.name == 'expense':
                try:
                    from apps.accounts.services import sync_expense_permissions_to_company_admin
                    sync_expense_permissions_to_company_admin()
                except Exception:
                    pass
