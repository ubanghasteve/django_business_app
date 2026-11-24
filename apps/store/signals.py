# -*- coding: utf-8 -*-
from django.db.models.signals import pre_save, post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache
from decimal import Decimal

from .models import Store, StoreMovement, WasteLog


def _decimal_safe(value, default=Decimal('0')):
    if value is None:
        return default
    try:
        d = Decimal(str(value))
        return d if not (d.is_nan() or d.is_infinite()) else default
    except Exception:
        return default


# ----- Pre-save: capture old values so post_save can diff them -----

@receiver(pre_save, sender=Store)
def _capture_old_store_values(sender, instance, **kwargs):
    """Store previous field values so post_save can create movements when anything changes."""
    if instance.pk:
        try:
            old = Store.objects.filter(pk=instance.pk).values(
                'opening_stock', 'quantity_in', 'quantity_out', 'waste',
                'unit_price', 'approval_status', 'workflow_status', 'remark', 'date',
            ).first()
            if old is not None:
                instance._mov_old_opening_stock = _decimal_safe(old.get('opening_stock'))
                instance._mov_old_qty_in = _decimal_safe(old.get('quantity_in'))
                instance._mov_old_qty_out = _decimal_safe(old.get('quantity_out'))
                instance._mov_old_waste = _decimal_safe(old.get('waste'))
                instance._mov_old_unit_price = _decimal_safe(old.get('unit_price'))
                instance._mov_old_approval = old.get('approval_status') or 'draft'
                instance._mov_old_workflow = old.get('workflow_status') or 'draft'
                instance._mov_old_remark = old.get('remark') or ''
                instance._mov_old_date = old.get('date')
            else:
                _set_old_defaults(instance)
        except Exception:
            _set_old_defaults(instance)
    else:
        _set_old_defaults(instance)


def _set_old_defaults(instance):
    instance._mov_old_opening_stock = Decimal('0')
    instance._mov_old_qty_in = Decimal('0')
    instance._mov_old_qty_out = Decimal('0')
    instance._mov_old_waste = Decimal('0')
    instance._mov_old_unit_price = Decimal('0')
    instance._mov_old_approval = 'draft'
    instance._mov_old_workflow = 'draft'
    instance._mov_old_remark = ''
    instance._mov_old_date = None


def _clean_mov_attrs(instance):
    for attr in (
        '_mov_old_opening_stock', '_mov_old_qty_in', '_mov_old_qty_out',
        '_mov_old_waste', '_mov_old_unit_price',
        '_mov_old_approval', '_mov_old_workflow', '_mov_old_remark',
        '_mov_old_date',
    ):
        if hasattr(instance, attr):
            delattr(instance, attr)


# ----- Post-save: create movement record when relevant fields change -----

@receiver(post_save, sender=Store)
def _create_store_movement_on_change(sender, instance, created, **kwargs):
    """
    Create an immutable StoreMovement when opening_stock, quantity_in, quantity_out,
    waste, unit_price, approval_status, workflow_status, date, or remark changes.
    Movement captures a snapshot of the store row at that moment.
    """
    if not instance.company_id:
        _clean_mov_attrs(instance)
        return

    old_opening = getattr(instance, '_mov_old_opening_stock', Decimal('0'))
    old_in = getattr(instance, '_mov_old_qty_in', Decimal('0'))
    old_out = getattr(instance, '_mov_old_qty_out', Decimal('0'))
    old_waste = getattr(instance, '_mov_old_waste', Decimal('0'))
    old_price = getattr(instance, '_mov_old_unit_price', Decimal('0'))
    old_approval = getattr(instance, '_mov_old_approval', 'draft')
    old_workflow = getattr(instance, '_mov_old_workflow', 'draft')
    old_remark = getattr(instance, '_mov_old_remark', '')
    old_date = getattr(instance, '_mov_old_date', None)

    new_opening = _decimal_safe(instance.opening_stock)
    new_in = _decimal_safe(instance.quantity_in)
    new_out = _decimal_safe(instance.quantity_out)
    new_waste = _decimal_safe(instance.waste)
    new_price = _decimal_safe(instance.unit_price)
    new_approval = instance.approval_status or 'draft'
    new_workflow = getattr(instance, 'workflow_status', None) or 'draft'
    new_remark = instance.remark or ''
    new_date = instance.date

    old_total = old_opening + old_in - old_out
    new_total = new_opening + new_in - new_out

    approval_or_workflow_changed = old_approval != new_approval or old_workflow != new_workflow
    opening_changed = old_opening != new_opening
    qty_in_changed = old_in != new_in
    qty_out_changed = old_out != new_out
    waste_changed = old_waste != new_waste
    price_changed = old_price != new_price
    remark_changed = old_remark != new_remark
    date_changed = old_date != new_date

    if (
        old_total == new_total
        and not approval_or_workflow_changed
        and not opening_changed
        and not qty_in_changed
        and not qty_out_changed
        and not waste_changed
        and not price_changed
        and not remark_changed
        and not date_changed
    ):
        _clean_mov_attrs(instance)
        return

    unit_price = new_price
    if opening_changed or qty_in_changed or qty_out_changed or waste_changed:
        qty_before, qty_after = old_total, new_total
        qty_in_val, qty_out_val = new_in, new_out
        waste_val = new_waste
        qty_before_str = old_opening
        qty_after_str = new_opening
        remark = new_remark[:500] if new_remark else None
        if waste_changed and not (qty_in_changed or qty_out_changed):
            waste_diff = new_waste - old_waste
            if waste_diff > 0:
                waste_note = f"Waste recorded: +{waste_diff}"
            else:
                waste_note = f"Waste removed: {waste_diff}"
            remark = (waste_note + (f" - {remark}" if remark else ""))[:500]
        if date_changed:
            old_date_str = str(old_date) if old_date else 'none'
            new_date_str = str(new_date) if new_date else 'none'
            date_note = f"Date changed: {old_date_str} → {new_date_str}"
            remark = (date_note + (f" - {remark}" if remark else ""))[:500]
    else:
        qty_before = qty_after = new_total
        qty_in_val = qty_out_val = Decimal('0')
        waste_val = new_waste
        qty_before_str = Decimal('0')
        qty_after_str = Decimal('0')
        if date_changed:
            old_date_str = str(old_date) if old_date else 'none'
            new_date_str = str(new_date) if new_date else 'none'
            remark = f"Date changed: {old_date_str} → {new_date_str}"
        elif remark_changed:
            remark = new_remark[:500] if new_remark else None
        elif approval_or_workflow_changed:
            remark = 'Approval/status updated'
        elif price_changed:
            remark = 'Unit price updated'
        else:
            remark = 'Store record updated'

    try:
        StoreMovement.objects.create(
            product=instance,
            opening_stock=new_opening,
            opening_stock_input=instance.opening_stock_input or '',
            quantity_in=qty_in_val,
            quantity_out=qty_out_val,
            waste=waste_val,
            waste_input=getattr(instance, 'waste_input', '') or '',
            quantity_before=qty_before,
            quantity_after=qty_after,
            unit_price=unit_price,
            balance=instance.total_amount or Decimal('0'),
            stock_balance_remaining=instance.stock_balance_remaining or Decimal('0'),
            waste_value=instance.waste_value or Decimal('0'),
            approval_status=new_approval,
            stock_status=instance.stock_status,
            remark=remark,
            date=instance.date,
            created_by=instance.created_by,
        )
    finally:
        _clean_mov_attrs(instance)


# ----- WasteLog: create movement when waste is recorded -----

@receiver(post_save, sender=WasteLog)
def _create_store_movement_on_waste(sender, instance, created, **kwargs):
    """When a WasteLog is created, create a movement record to track waste."""
    if not created or not instance.store_id:
        return
    store = instance.store
    if not store.company_id:
        return

    opening = _decimal_safe(store.opening_stock)
    qty_in = _decimal_safe(store.quantity_in)
    qty_out = _decimal_safe(store.quantity_out)
    old_total = opening + qty_in - qty_out
    new_total = opening + qty_in - qty_out

    StoreMovement.objects.create(
        product=store,
        opening_stock=_decimal_safe(store.opening_stock),
        opening_stock_input=store.opening_stock_input or '',
        quantity_in=Decimal('0'),
        quantity_out=Decimal('0'),
        waste=_decimal_safe(instance.quantity),
        waste_input=getattr(store, 'waste_input', '') or '',
        quantity_before=old_total,
        quantity_after=new_total,
        unit_price=instance.unit_price or store.unit_price or Decimal('0'),
        balance=Decimal('0'),
        stock_balance_remaining=new_total * (instance.unit_price or store.unit_price or Decimal('0')),
        waste_value=instance.total_value or Decimal('0'),
        approval_status=store.approval_status,
        stock_status=store.stock_status,
        remark=f"Waste recorded: {instance.reason or 'N/A'}",
        date=store.date,
        created_by=instance.created_by,
    )


# ----- Cache invalidation -----

@receiver(post_save, sender=Store)
def clear_store_cache_on_save(sender, instance, **kwargs):
    if instance.company_id:
        cache.delete(f"store_list_{instance.company_id}")


@receiver(post_delete, sender=Store)
def clear_store_cache_on_delete(sender, instance, **kwargs):
    if instance.company_id:
        cache.delete(f"store_list_{instance.company_id}")


@receiver(post_save, sender=WasteLog)
def clear_store_cache_on_waste_log_save(sender, instance, **kwargs):
    if instance.company_id:
        cache.delete(f"store_list_{instance.company_id}")


@receiver(post_delete, sender=WasteLog)
def clear_store_cache_on_waste_log_delete(sender, instance, **kwargs):
    if instance.company_id:
        cache.delete(f"store_list_{instance.company_id}")
