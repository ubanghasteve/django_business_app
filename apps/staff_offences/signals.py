# -*- coding: utf-8 -*-
from django.db.models.signals import post_migrate, post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache


def _invalidate_register_list_cache(register):
    if register and getattr(register, 'account_id', None):
        cache.delete(f'staff_offence_list_account_{register.account_id}')


@receiver(post_migrate)
def add_staff_offence_permissions_to_company_admin(sender, **kwargs):
    if sender.name != 'staff_offences':
        return
    try:
        from apps.accounts.services import sync_staff_offence_permissions_to_company_admin
        sync_staff_offence_permissions_to_company_admin()
    except Exception:
        pass


@receiver(post_save, sender='staff_offences.StaffOffenceRegister')
def invalidate_register_list_on_save(sender, instance, **kwargs):
    _invalidate_register_list_cache(instance)


@receiver(post_delete, sender='staff_offences.StaffOffenceRegister')
def invalidate_register_list_on_delete(sender, instance, **kwargs):
    _invalidate_register_list_cache(instance)


@receiver(post_save, sender='staff_offences.StaffOffenceEntry')
def invalidate_register_list_on_entry_save(sender, instance, **kwargs):
    _invalidate_register_list_cache(getattr(instance, 'register', None))


@receiver(post_delete, sender='staff_offences.StaffOffenceEntry')
def invalidate_register_list_on_entry_delete(sender, instance, **kwargs):
    _invalidate_register_list_cache(getattr(instance, 'register', None))
