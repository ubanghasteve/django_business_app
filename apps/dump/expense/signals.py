# -*- coding: utf-8 -*-
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache
from .models import Expense


def _clear_company_expense_cache(instance):
    if instance.company_id:
        cache.delete(f"expense_list_{instance.company_id}")


@receiver(post_save, sender=Expense)
def clear_expense_cache_on_save(sender, instance, **kwargs):
    _clear_company_expense_cache(instance)


@receiver(post_delete, sender=Expense)
def clear_expense_cache_on_delete(sender, instance, **kwargs):
    _clear_company_expense_cache(instance)
