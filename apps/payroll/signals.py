"""
Smart Payroll Signals
================
Django signals for payroll records.
"""

from django.db.models.signals import post_save, post_delete, pre_delete
from django.dispatch import receiver

from .models import (
    PayrollRecord,
    PayrollCategory,
    PayrollRecordAccessLog,
    PayrollRecordShare,
    PayrollNotification,
    PayrollSetting,
)


@receiver(post_save, sender=PayrollRecord)
def payroll_record_post_save(sender, instance, created, **kwargs):
    """
    Handle post-save actions for PayrollRecord.
    """
    if created:
        pass


@receiver(pre_delete, sender=PayrollRecord)
def payroll_record_pre_delete(sender, instance, **kwargs):
    """
    Handle pre-delete actions for PayrollRecord.
    """
    pass


@receiver(post_delete, sender=PayrollRecord)
def payroll_record_post_delete(sender, instance, **kwargs):
    """
    Handle post-delete actions for PayrollRecord.
    """
    pass


@receiver(post_save, sender=PayrollCategory)
def payroll_category_post_save(sender, instance, created, **kwargs):
    """
    Handle post-save actions for PayrollCategory.
    """
    pass


@receiver(post_delete, sender=PayrollCategory)
def payroll_category_post_delete(sender, instance, **kwargs):
    """
    Handle post-delete actions for PayrollCategory.
    """
    pass


@receiver(post_save, sender=PayrollRecordAccessLog)
def access_log_post_save(sender, instance, created, **kwargs):
    """
    Handle post-save actions for PayrollRecordAccessLog.
    """
    pass


@receiver(post_delete, sender=PayrollRecordAccessLog)
def access_log_post_delete(sender, instance, **kwargs):
    """
    Handle post-delete actions for PayrollRecordAccessLog.
    """
    pass


@receiver(post_save, sender=PayrollRecordShare)
def share_post_save(sender, instance, created, **kwargs):
    """
    Handle post-save actions for PayrollRecordShare.
    """
    pass


@receiver(post_delete, sender=PayrollRecordShare)
def share_post_delete(sender, instance, **kwargs):
    """
    Handle post-delete actions for PayrollRecordShare.
    """
    pass


@receiver(post_save, sender=PayrollNotification)
def notification_post_save(sender, instance, created, **kwargs):
    """
    Handle post-save actions for PayrollNotification.
    """
    pass


@receiver(post_delete, sender=PayrollNotification)
def notification_post_delete(sender, instance, **kwargs):
    """
    Handle post-delete actions for PayrollNotification.
    """
    pass
