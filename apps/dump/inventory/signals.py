# -*- coding: utf-8 -*-
from django.db.models.signals import post_save, pre_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache
from decimal import Decimal

from .models import Inventory, InventoryMovement


def _decimal_safe(value, default=Decimal('0')):
    if value is None:
        return default
    try:
        d = Decimal(str(value))
        return d if not (d.is_nan() or d.is_infinite()) else default
    except Exception:
        return default


def _clear_company_inventory_cache(instance):
    if instance.company_id:
        cache.delete(f"inventory_list_{instance.company_id}")


@receiver(pre_save, sender=Inventory)
def _capture_old_quantity_for_movement(sender, instance, **kwargs):
    """Store previous quantities/price and approval/workflow so post_save can create movements when the report-relevant snapshot changes."""
    if instance.pk:
        try:
            old = Inventory.objects.filter(pk=instance.pk).values(
                'quantity_in', 'quantity_out', 'unit_price', 'approval_status', 'workflow_status'
            ).first()
            if old is not None:
                instance._movement_old_qty_in = _decimal_safe(old['quantity_in'])
                instance._movement_old_qty_out = _decimal_safe(old['quantity_out'])
                instance._movement_old_unit_price = _decimal_safe(old.get('unit_price'))
                instance._movement_old_approval = old.get('approval_status') or 'draft'
                instance._movement_old_workflow = old.get('workflow_status') or 'draft'
            else:
                instance._movement_old_qty_in = Decimal('0')
                instance._movement_old_qty_out = Decimal('0')
                instance._movement_old_unit_price = Decimal('0')
                instance._movement_old_approval = 'draft'
                instance._movement_old_workflow = 'draft'
        except Exception:
            instance._movement_old_qty_in = Decimal('0')
            instance._movement_old_qty_out = Decimal('0')
            instance._movement_old_unit_price = Decimal('0')
            instance._movement_old_approval = 'draft'
            instance._movement_old_workflow = 'draft'
    else:
        instance._movement_old_qty_in = Decimal('0')
        instance._movement_old_qty_out = Decimal('0')
        instance._movement_old_unit_price = Decimal('0')
        instance._movement_old_approval = 'draft'
        instance._movement_old_workflow = 'draft'


def _clean_movement_attrs(instance):
    for attr in (
        '_movement_old_qty_in',
        '_movement_old_qty_out',
        '_movement_old_unit_price',
        '_movement_old_approval',
        '_movement_old_workflow',
    ):
        if hasattr(instance, attr):
            delattr(instance, attr)


@receiver(post_save, sender=Inventory)
def _create_inventory_movement_on_quantity_change(sender, instance, created, **kwargs):
    """Create an immutable InventoryMovement when the report snapshot changes.
    
    Each movement row stores a SNAPSHOT of the inventory row at that moment, so the report
    can display the same format as the main table. We create a 0/0 movement row for changes that
    don't affect remaining quantity (e.g. unit price edit, approval/workflow update) so the report
    still reflects what the user changed.
    """
    old_in = getattr(instance, '_movement_old_qty_in', Decimal('0'))
    old_out = getattr(instance, '_movement_old_qty_out', Decimal('0'))
    old_unit_price = getattr(instance, '_movement_old_unit_price', Decimal('0'))
    old_remaining = old_in - old_out
    new_in = _decimal_safe(instance.quantity_in)
    new_out = _decimal_safe(instance.quantity_out)
    new_remaining = new_in - new_out
    new_unit_price = _decimal_safe(instance.unit_price)
    old_approval = getattr(instance, '_movement_old_approval', 'draft')
    old_workflow = getattr(instance, '_movement_old_workflow', 'draft')
    new_approval = (instance.approval_status or 'draft')
    new_workflow = (getattr(instance, 'workflow_status', None) or 'draft')
    approval_or_workflow_changed = (old_approval != new_approval or old_workflow != new_workflow)
    qty_changed = (old_in != new_in) or (old_out != new_out)
    price_changed = (old_unit_price != new_unit_price)

    if old_remaining == new_remaining and not approval_or_workflow_changed and not qty_changed and not price_changed:
        _clean_movement_attrs(instance)
        return

    unit_price = new_unit_price
    if old_remaining != new_remaining:
        balance = _decimal_safe(getattr(instance, 'total_amount', None)) or (new_in * unit_price)
        stock_balance_remaining = _decimal_safe(getattr(instance, 'stock_balance_remaining', None)) or (new_remaining * unit_price)
        qty_in, qty_out = new_in, new_out
        qty_before, qty_after = old_remaining, new_remaining
        remark = (instance.remark or '')[:500] if instance.remark else None
    else:
        # Snapshot-only (no remaining change): create a 0/0 movement so report shows the update.
        balance = _decimal_safe(getattr(instance, 'total_amount', None)) or (new_in * unit_price)
        stock_balance_remaining = _decimal_safe(getattr(instance, 'stock_balance_remaining', None)) or (new_remaining * unit_price)
        qty_in, qty_out = Decimal('0'), Decimal('0')
        qty_before = qty_after = new_remaining
        remark = (instance.remark or '')[:500] if instance.remark else None
        if not (remark or '').strip():
            if approval_or_workflow_changed:
                remark = 'Approval/status updated'
            elif price_changed and not qty_changed:
                remark = 'Unit price updated'
            elif qty_changed and not price_changed:
                remark = 'Quantity updated'
            else:
                remark = 'Inventory updated'

    try:
        InventoryMovement.objects.create(
            product=instance,
            quantity_in=qty_in,
            quantity_out=qty_out,
            quantity_before=qty_before,
            quantity_after=qty_after,
            unit_price=unit_price,
            balance=balance,
            stock_balance_remaining=stock_balance_remaining,
            approval_status=new_approval,
            stock_status=instance.stock_status,
            remark=remark,
            created_by=instance.created_by,
        )
    finally:
        _clean_movement_attrs(instance)


@receiver(post_save, sender=Inventory)
def clear_inventory_cache_on_save(sender, instance, **kwargs):
    _clear_company_inventory_cache(instance)


@receiver(post_delete, sender=Inventory)
def clear_inventory_cache_on_delete(sender, instance, **kwargs):
    _clear_company_inventory_cache(instance)
