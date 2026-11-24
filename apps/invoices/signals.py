import logging
from contextlib import contextmanager

from django.db import transaction
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import Invoice, InvoiceItem, InvoiceMovement

logger = logging.getLogger('invoices')


_suppress_movement_count = 0


@contextmanager
def suppress_invoice_movements():
    """Skip InvoiceMovement rows and per-item total recalcs (views write one snapshot at the end)."""
    global _suppress_movement_count
    _suppress_movement_count += 1
    try:
        yield
    finally:
        _suppress_movement_count -= 1


def _invoice_account(invoice):
    if getattr(invoice, 'user_id', None) and getattr(invoice.user, 'account_id', None):
        return invoice.user.account
    return None


def _get_user_from_request():
    try:
        from apps.accounts.activity_tracking import get_current_request
        request = get_current_request()
        user = getattr(request, 'user', None) if request else None
        if user and not getattr(user, 'is_authenticated', False):
            user = None
        return user
    except Exception:
        return None


def _get_items_snapshot(invoice):
    items_snapshot = []
    try:
        for item in InvoiceItem.objects.filter(invoice_id=invoice.pk):
            items_snapshot.append({
                'product_service': item.product_service or '',
                'description': item.description or '',
                'quantity': str(item.quantity) if item.quantity else '0',
                'quantity_display': item.quantity_display or '',
                'unit_price': str(item.unit_price) if item.unit_price else '0',
                'line_total': str(item.line_total) if item.line_total else '0',
            })
    except Exception:
        pass
    return items_snapshot


def _create_movement(invoice):
    """Create a single movement record for an invoice.

    Failures are logged and never raised: invoice create/edit must not 500
    because ledger logging failed. Uses a savepoint so a failed insert cannot
    poison an outer transaction.atomic() (important on MySQL).
    """
    global _suppress_movement_count
    if _suppress_movement_count > 0:
        return
    if invoice is None or invoice.pk is None:
        return
    try:
        user = _get_user_from_request()
        if not user:
            user = getattr(invoice, 'user', None)
        created_by_id = getattr(user, 'pk', None) if user else None
        items_snapshot = _get_items_snapshot(invoice)
        # Nested atomic = SAVEPOINT: rollback of this insert only
        with transaction.atomic():
            InvoiceMovement.objects.create(
                invoice_id=invoice.pk,
                client_name=invoice.client_name or '',
                client_phone=invoice.client_phone or '',
                client_email=invoice.client_email or '',
                client_address=invoice.client_address or '',
                subtotal=invoice.subtotal or 0,
                total_tax=invoice.total_tax or 0,
                tax_type=invoice.tax_type or 'percentage',
                tax_value=invoice.tax_value or 0,
                total_discount=invoice.total_discount or 0,
                discount_type=invoice.discount_type or 'percentage',
                discount_value=invoice.discount_value or 0,
                shipping_fee=invoice.shipping_fee or 0,
                other_charges=invoice.other_charges or 0,
                grand_total=invoice.grand_total or 0,
                amount_paid=invoice.amount_paid or 0,
                balance_due=invoice.balance_due or 0,
                status=invoice.status or 'unpaid',
                notes=invoice.notes or '',
                show_bank_details=bool(invoice.show_bank_details),
                show_signature=bool(invoice.show_signature),
                items_snapshot=items_snapshot,
                created_by_id=created_by_id,
            )
    except Exception as e:
        logger.error('[InvoiceMovement] Insert failed for invoice_id=%s: %s', invoice.pk, e)


def write_invoice_activity(invoice, created=False):
    """Write one security activity row for an invoice create/update."""
    account = _invoice_account(invoice)
    if not account:
        return
    try:
        from apps.accounts.models import UserActivity
        user = _get_user_from_request() or getattr(invoice, 'user', None)
        activity_type = 'CREATE' if created else 'UPDATE'
        desc = f"Invoice {invoice.invoice_number} created" if created else f"Invoice {invoice.invoice_number} updated"
        with transaction.atomic():
            UserActivity.log_activity(
                user=user,
                account=account,
                activity_type=activity_type,
                description=desc,
                app_name='invoices',
                model_name='Invoice',
                object_id=str(invoice.pk),
                object_repr=invoice.invoice_number or str(invoice),
                object_url=invoice.get_absolute_url() if hasattr(invoice, 'get_absolute_url') else '',
            )
    except Exception as e:
        logger.error('[Invoice] Activity log failed for invoice_id=%s: %s', invoice.pk, e)


@receiver(post_save, sender=Invoice)
def log_invoice_activity(sender, instance, created, **kwargs):
    """Log invoice create/update to security activity log."""
    if _suppress_movement_count > 0:
        return
    write_invoice_activity(instance, created=created)


@receiver(post_save, sender=Invoice)
def create_invoice_movement(sender, instance, created, **kwargs):
    """Create an immutable movement record whenever an invoice is created or updated."""
    _create_movement(instance)


@receiver(post_delete, sender=Invoice)
def log_invoice_deleted(sender, instance, **kwargs):
    """Log invoice deletion to security activity log."""
    account = _invoice_account(instance)
    if not account:
        return
    try:
        from apps.accounts.models import UserActivity
        user = _get_user_from_request() or getattr(instance, 'user', None)
        UserActivity.log_activity(
            user=user,
            account=account,
            activity_type='DELETE',
            description=f"Invoice {instance.invoice_number} deleted",
            app_name='invoices',
            model_name='Invoice',
            object_id=str(instance.pk),
            object_repr=instance.invoice_number or str(instance),
        )
    except Exception as e:
        logger.error('[Invoice] Delete activity log failed for invoice_id=%s: %s', instance.pk, e)


@receiver(post_save, sender=InvoiceItem)
def update_invoice_totals_on_save(sender, instance, **kwargs):
    """Update invoice totals when an item is saved."""
    if _suppress_movement_count > 0:
        return
    try:
        instance.invoice.calculate_totals()
        instance.invoice.save(update_fields=['subtotal', 'grand_total', 'balance_due', 'status'])
        # Keep linked receipts' balance/payment_type aligned with new grand_total
        from apps.receipts.models import resync_invoice_and_receipts
        resync_invoice_and_receipts(instance.invoice)
    except Exception as e:
        logger.error('[Invoice] Totals update on item save failed: %s', e)


@receiver(post_delete, sender=InvoiceItem)
def update_invoice_totals_on_delete(sender, instance, **kwargs):
    """Update invoice totals when an item is deleted."""
    if _suppress_movement_count > 0:
        return
    try:
        instance.invoice.calculate_totals()
        instance.invoice.save(update_fields=['subtotal', 'grand_total', 'balance_due', 'status'])
        from apps.receipts.models import resync_invoice_and_receipts
        resync_invoice_and_receipts(instance.invoice)
    except Exception:
        pass


@receiver(post_save, sender=InvoiceItem)
def create_invoice_movement_on_item_change(sender, instance, **kwargs):
    """Create a movement record when an invoice item is added or changed."""
    _create_movement(instance.invoice)


@receiver(post_delete, sender=InvoiceItem)
def create_invoice_movement_on_item_delete(sender, instance, **kwargs):
    """Create a movement record when an invoice item is deleted."""
    _create_movement(instance.invoice)
