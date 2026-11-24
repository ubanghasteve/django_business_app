# -*- coding: utf-8 -*-
from django.db.models.signals import pre_save, post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache
from decimal import Decimal

from .models import Expense, ExpenseMovement


def _decimal_safe(value, default=Decimal('0')):
    if value is None:
        return default
    try:
        d = Decimal(str(value))
        return d if not (d.is_nan() or d.is_infinite()) else default
    except Exception:
        return default


def _clear_company_expense_cache(instance):
    if instance.company_id:
        cache.delete(f"expense_list_{instance.company_id}")


@receiver(pre_save, sender=Expense)
def _capture_old_for_expense_movement(sender, instance, **kwargs):
    """Store previous quantities/price/status so post_save can create movements when report-relevant snapshot changes."""
    if instance.pk:
        try:
            old = Expense.objects.filter(pk=instance.pk).values(
                'quantity_purchased', 'quantity_out', 'unit_price', 'quantity_threshold', 'status'
            ).first()
            if old is not None:
                instance._movement_old_qty_purchased = _decimal_safe(old['quantity_purchased'])
                instance._movement_old_qty_out = _decimal_safe(old['quantity_out'])
                instance._movement_old_unit_price = _decimal_safe(old.get('unit_price'))
                instance._movement_old_threshold = _decimal_safe(old.get('quantity_threshold'))
                instance._movement_old_status = old.get('status') or 'draft'
            else:
                instance._movement_old_qty_purchased = Decimal('0')
                instance._movement_old_qty_out = Decimal('0')
                instance._movement_old_unit_price = Decimal('0')
                instance._movement_old_threshold = Decimal('0')
                instance._movement_old_status = 'draft'
        except Exception:
            instance._movement_old_qty_purchased = Decimal('0')
            instance._movement_old_qty_out = Decimal('0')
            instance._movement_old_unit_price = Decimal('0')
            instance._movement_old_threshold = Decimal('0')
            instance._movement_old_status = 'draft'
    else:
        instance._movement_old_qty_purchased = Decimal('0')
        instance._movement_old_qty_out = Decimal('0')
        instance._movement_old_unit_price = Decimal('0')
        instance._movement_old_threshold = Decimal('0')
        instance._movement_old_status = 'draft'


def _clean_expense_movement_attrs(instance):
    for attr in (
        '_movement_old_qty_purchased', '_movement_old_qty_out', '_movement_old_unit_price',
        '_movement_old_threshold', '_movement_old_status',
    ):
        if hasattr(instance, attr):
            delattr(instance, attr)


@receiver(post_save, sender=Expense)
def _create_expense_movement_on_change(sender, instance, created, **kwargs):
    """Create an immutable ExpenseMovement when the report snapshot changes.
    balance = (quantity_purchased - quantity_out) × unit_price;
    stock_value_remaining = quantity_after × unit_price.
    """
    old_in = getattr(instance, '_movement_old_qty_purchased', Decimal('0'))
    old_out = getattr(instance, '_movement_old_qty_out', Decimal('0'))
    old_unit_price = getattr(instance, '_movement_old_unit_price', Decimal('0'))
    old_remaining = old_in - old_out
    new_in = _decimal_safe(instance.quantity_purchased)
    new_out = _decimal_safe(instance.quantity_out)
    new_remaining = new_in - new_out
    new_unit_price = _decimal_safe(instance.unit_price)
    new_threshold = _decimal_safe(instance.quantity_threshold)
    old_status = getattr(instance, '_movement_old_status', 'draft')
    new_status = (instance.status or 'draft')
    status_changed = (old_status != new_status)
    qty_changed = (old_in != new_in) or (old_out != new_out)
    price_changed = (old_unit_price != new_unit_price)

    if old_remaining == new_remaining and not status_changed and not qty_changed and not price_changed:
        _clean_expense_movement_attrs(instance)
        return

    unit_price = new_unit_price
    if old_remaining != new_remaining:
        qty_purchased, qty_out = new_in, new_out
        qty_before, qty_after = old_remaining, new_remaining
        balance = (qty_purchased - qty_out) * unit_price
        stock_value_remaining = qty_after * unit_price
        remark = (instance.description or '')[:500] if instance.description else None
    else:
        qty_purchased, qty_out = Decimal('0'), Decimal('0')
        qty_before = qty_after = new_remaining
        balance = (qty_purchased - qty_out) * unit_price
        stock_value_remaining = qty_after * unit_price
        remark = (instance.description or '')[:500] if instance.description else None
        if not (remark or '').strip():
            if status_changed:
                remark = 'Status updated'
            elif price_changed:
                remark = 'Unit price updated'
            else:
                remark = 'Expense updated'

    low_stock_alert = new_remaining <= new_threshold
    try:
        ExpenseMovement.objects.create(
            expense=instance,
            quantity_purchased=qty_purchased,
            quantity_out=qty_out,
            quantity_before=qty_before,
            quantity_after=qty_after,
            unit_price=unit_price,
            balance=balance,
            stock_value_remaining=stock_value_remaining,
            status=new_status,
            low_stock_alert=low_stock_alert,
            remark=remark,
            created_by=instance.created_by,
        )
    finally:
        _clean_expense_movement_attrs(instance)


@receiver(post_save, sender=Expense)
def clear_expense_cache_on_save(sender, instance, **kwargs):
    _clear_company_expense_cache(instance)


@receiver(post_delete, sender=Expense)
def clear_expense_cache_on_delete(sender, instance, **kwargs):
    _clear_company_expense_cache(instance)
