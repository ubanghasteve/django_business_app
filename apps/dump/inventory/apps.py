from django.apps import AppConfig
from django.db.models.signals import post_migrate


class InventoryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.inventory'
    verbose_name = 'Inventory'

    def ready(self):
        import apps.inventory.signals
        from django.dispatch import receiver
        @receiver(post_migrate)
        def _sync_inventory_permissions(sender, **kwargs):
            if sender.name == 'inventory':
                try:
                    from apps.accounts.services import sync_inventory_permissions_to_company_admin
                    sync_inventory_permissions_to_company_admin()
                except Exception:
                    pass
