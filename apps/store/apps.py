# -*- coding: utf-8 -*-
from django.apps import AppConfig
from django.db.models.signals import post_migrate


class StoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.store'
    verbose_name = 'Store'

    def ready(self):
        import apps.store.signals
        from django.dispatch import receiver
        @receiver(post_migrate)
        def _sync_store_permissions(sender, **kwargs):
            if sender.name == 'store':
                try:
                    from apps.accounts.services import sync_store_permissions_to_company_admin
                    sync_store_permissions_to_company_admin()
                except Exception:
                    pass
