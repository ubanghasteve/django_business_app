# -*- coding: utf-8 -*-
"""
Signals for requisitions app:
- post_migrate: call reusable sync to add requisition permissions to all Company Admin groups.
  Company Read Only gets view_requisition only (enforced by core.signals view_* / print_* / download_*).
- post_save / post_delete: invalidate list cache so requisition list shows fresh data after edit/delete.
"""
from django.db.models.signals import post_migrate, post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache


def _invalidate_requisition_list_cache(requisition):
    """Clear any cached requisition list for this account so list view shows fresh data."""
    if requisition and getattr(requisition, 'account_id', None):
        cache.delete(f'requisition_list_account_{requisition.account_id}')


@receiver(post_migrate)
def add_requisition_permissions_to_company_admin(sender, **kwargs):
    """
    After requisitions migrations: sync all requisition permissions to every Company Admin group.
    Company Read Only groups are enforced by core.signals to have only view_*, print_*, download_*
    so they automatically get view_requisition (and print/download if you add them to that set).
    """
    if sender.name != 'requisitions':
        return
    try:
        from apps.accounts.services import sync_requisition_permissions_to_company_admin
        sync_requisition_permissions_to_company_admin()
    except Exception:
        pass


@receiver(post_save, sender='requisitions.Requisition')
def invalidate_requisition_list_on_save(sender, instance, **kwargs):
    """When a requisition is created or updated, invalidate list cache so list stays in sync."""
    _invalidate_requisition_list_cache(instance)


@receiver(post_delete, sender='requisitions.Requisition')
def invalidate_requisition_list_on_delete(sender, instance, **kwargs):
    """When a requisition is deleted, invalidate list cache so list updates without extra refresh."""
    _invalidate_requisition_list_cache(instance)
