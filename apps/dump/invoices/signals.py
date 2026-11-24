from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Invoice, InvoiceItem


def _invoice_account(invoice):
    if getattr(invoice, 'user_id', None) and getattr(invoice.user, 'account_id', None):
        return invoice.user.account
    return None


@receiver(post_save, sender=Invoice)
def log_invoice_activity(sender, instance, created, **kwargs):
    """Log invoice create/update to security activity log (tenant-safe, automatic)."""
    account = _invoice_account(instance)
    if not account:
        return
    from apps.accounts.models import UserActivity
    from apps.accounts.activity_tracking import get_current_request
    request = get_current_request()
    user = getattr(request, 'user', None) if request else None
    if user and not user.is_authenticated:
        user = instance.user
    activity_type = 'CREATE' if created else 'UPDATE'
    desc = f"Invoice {instance.invoice_number} created" if created else f"Invoice {instance.invoice_number} updated"
    UserActivity.log_activity(
        user=user or instance.user,
        account=account,
        activity_type=activity_type,
        description=desc,
        app_name='invoices',
        model_name='Invoice',
        object_id=str(instance.pk),
        object_repr=instance.invoice_number or str(instance),
        object_url=instance.get_absolute_url() if hasattr(instance, 'get_absolute_url') else '',
    )


@receiver(post_delete, sender=Invoice)
def log_invoice_deleted(sender, instance, **kwargs):
    """Log invoice deletion to security activity log."""
    account = _invoice_account(instance)
    if not account:
        return
    from apps.accounts.models import UserActivity
    from apps.accounts.activity_tracking import get_current_request
    request = get_current_request()
    user = getattr(request, 'user', None) if request else None
    if user and not user.is_authenticated:
        user = instance.user
    UserActivity.log_activity(
        user=user or instance.user,
        account=account,
        activity_type='DELETE',
        description=f"Invoice {instance.invoice_number} deleted",
        app_name='invoices',
        model_name='Invoice',
        object_id=str(instance.pk),
        object_repr=instance.invoice_number or str(instance),
    )


@receiver(post_save, sender=InvoiceItem)
def update_invoice_totals_on_save(sender, instance, **kwargs):
    """Update invoice totals when an item is saved"""
    instance.invoice.calculate_totals()
    instance.invoice.save(update_fields=['subtotal', 'grand_total', 'balance_due', 'status'])


@receiver(post_delete, sender=InvoiceItem)
def update_invoice_totals_on_delete(sender, instance, **kwargs):
    """Update invoice totals when an item is deleted"""
    instance.invoice.calculate_totals()
    instance.invoice.save(update_fields=['subtotal', 'grand_total', 'balance_due', 'status'])
