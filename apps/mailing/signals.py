# -*- coding: utf-8 -*-
"""
Signals for mailing app:
- post_migrate: add mailing permissions (use_bulk_mailing) to all Company Admin groups
  so existing Company Admins see Bulk Mailing in the nav and can use it.
"""
from django.db.models.signals import post_migrate
from django.dispatch import receiver


@receiver(post_migrate)
def sync_mailing_permissions_after_migrate(sender, **kwargs):
    """After mailing migrations: add mailing permissions to every Company Admin group."""
    if getattr(sender, 'name', '') != 'apps.mailing':
        return
    try:
        from apps.accounts.services import sync_mailing_permissions_to_company_admin
        sync_mailing_permissions_to_company_admin()
    except Exception:
        pass
