# -*- coding: utf-8 -*-
"""
HR signals: on Employee delete, deactivate linked User (HR cannot delete User directly).
"""
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from .models import Employee


@receiver(pre_delete, sender=Employee)
def employee_pre_delete_deactivate_user(sender, instance, **kwargs):
    """
    When an Employee with portal access is deleted, deactivate the linked User.
    HR cannot delete User directly; deactivating prevents login.
    """
    if instance.linked_user_id:
        user = instance.linked_user
        if user and user.is_active:
            user.is_active = False
            user.save(update_fields=['is_active'])
