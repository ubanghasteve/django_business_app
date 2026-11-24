# -*- coding: utf-8 -*-
from django.db.models.signals import post_save, pre_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache
from decimal import Decimal

from .models import (
    Inventory,
    InventoryMovement,
    WasteLog,
    InventoryIssue,
    InventoryReceipt,
    net_remaining_quantity,
)


def _sync_inventory_movement_to_accounting(movement):
    """
    Create an accounting Transaction and FinancialTransaction for an inventory
    movement with non-zero balance so tax/reports see inventory impact.
    """
    try:
        from apps.accounting.models import Transaction
        from apps.finance_engine.services import sync_app_transaction_to_finance
        from apps.finance_engine.models import FinancialTransaction
    except ImportError:
        return
    company = getattr(movement.product, 'company', None)
    if not company:
        return
    balance = _decimal_safe(movement.balance)
    if balance == 0:
        return
    amount = abs(balance)
    source_id = str(movement.pk)
    if Transaction.objects.filter(
        company=company,
        source_app='inventory',
        reference_id=source_id,
    ).exists():
        return
    user = movement.created_by or getattr(company, 'user', None)
    if not user:
        return
    currency = getattr(company, 'currency_symbol', None) or getattr(company, 'currency_code', '₦')
    if balance > 0:
        title = f"Inventory in - {movement.product.product_name} ({movement.product.transaction_id})"
        trans_type = 'expense'
        finance_type = FinancialTransaction.TRANSACTION_PURCHASE
    else:
        title = f"Inventory out / COGS - {movement.product.product_name} ({movement.product.transaction_id})"
        trans_type = 'expense'
        finance_type = FinancialTransaction.TRANSACTION_EXPENSE
    txn = Transaction.objects.create(
        user=user,
        company=company,
        type=trans_type,
        title=title,
        description=movement.remark or title,
        amount=amount,
        currency=currency,
        source_app='inventory',
        reference_id=source_id,
        reference_model='InventoryMovement',
        transaction_date=movement.created_at.date(),
        notes=f"Auto-synced from inventory movement {movement.product.transaction_id}",
    )
    sync_app_transaction_to_finance(
        company=company,
        source_app='inventory',
        source_id=source_id,
        transaction_type=finance_type,
        amount=amount,
        transaction_date=movement.created_at.date(),
        description=(title or '')[:500],
    )


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
                'quantity_in', 'quantity_out', 'waste', 'unit_price', 'approval_status', 'workflow_status'
            ).first()
            if old is not None:
                instance._movement_old_qty_in = _decimal_safe(old['quantity_in'])
                instance._movement_old_qty_out = _decimal_safe(old['quantity_out'])
                instance._movement_old_waste = _decimal_safe(old.get('waste'))
                instance._movement_old_unit_price = _decimal_safe(old.get('unit_price'))
                instance._movement_old_approval = old.get('approval_status') or 'draft'
                instance._movement_old_workflow = old.get('workflow_status') or 'draft'
            else:
                instance._movement_old_qty_in = Decimal('0')
                instance._movement_old_qty_out = Decimal('0')
                instance._movement_old_waste = Decimal('0')
                instance._movement_old_unit_price = Decimal('0')
                instance._movement_old_approval = 'draft'
                instance._movement_old_workflow = 'draft'
        except Exception:
            instance._movement_old_qty_in = Decimal('0')
            instance._movement_old_qty_out = Decimal('0')
            instance._movement_old_waste = Decimal('0')
            instance._movement_old_unit_price = Decimal('0')
            instance._movement_old_approval = 'draft'
            instance._movement_old_workflow = 'draft'
    else:
        instance._movement_old_qty_in = Decimal('0')
        instance._movement_old_qty_out = Decimal('0')
        instance._movement_old_waste = Decimal('0')
        instance._movement_old_unit_price = Decimal('0')
        instance._movement_old_approval = 'draft'
        instance._movement_old_workflow = 'draft'


def _clean_movement_attrs(instance):
    for attr in (
        '_movement_old_qty_in',
        '_movement_old_qty_out',
        '_movement_old_waste',
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
    old_waste = getattr(instance, '_movement_old_waste', Decimal('0'))
    old_unit_price = getattr(instance, '_movement_old_unit_price', Decimal('0'))
    old_actual = old_in - old_waste
    new_in = _decimal_safe(instance.quantity_in)
    new_out = _decimal_safe(instance.quantity_out)
    new_waste = _decimal_safe(instance.waste)
    new_actual = new_in - new_waste
    old_remaining = net_remaining_quantity(old_in, old_waste, old_out)
    new_remaining = net_remaining_quantity(new_in, new_waste, new_out)
    new_unit_price = _decimal_safe(instance.unit_price)
    old_approval = getattr(instance, '_movement_old_approval', 'draft')
    old_workflow = getattr(instance, '_movement_old_workflow', 'draft')
    new_approval = (instance.approval_status or 'draft')
    new_workflow = (getattr(instance, 'workflow_status', None) or 'draft')
    approval_or_workflow_changed = (old_approval != new_approval or old_workflow != new_workflow)
    qty_changed = (old_in != new_in) or (old_out != new_out)
    waste_changed = (old_waste != new_waste)
    price_changed = (old_unit_price != new_unit_price)

    if old_remaining == new_remaining and not approval_or_workflow_changed and not qty_changed and not price_changed and not waste_changed:
        _clean_movement_attrs(instance)
        return

    unit_price = new_unit_price
    if old_remaining != new_remaining or waste_changed:
        qty_in, qty_out = new_in, new_out
        waste = new_waste
        qty_before, qty_after = old_remaining, new_remaining
        balance = (qty_in - qty_out) * unit_price
        stock_balance_remaining = new_remaining * unit_price
        waste_value = waste * unit_price
        remark = (instance.remark or '')[:500] if instance.remark else None
        if waste_changed:
            waste_change = new_waste - old_waste
            if waste_change > 0:
                remark = f"Waste recorded: +{waste_change}" + (f" - {remark}" if remark else "")
            else:
                remark = f"Waste removed: {waste_change}" + (f" - {remark}" if remark else "")
    else:
        qty_in, qty_out = Decimal('0'), Decimal('0')
        waste = new_waste
        qty_before = qty_after = new_remaining
        balance = (qty_in - qty_out) * unit_price
        stock_balance_remaining = qty_after * unit_price
        waste_value = waste * unit_price
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
        movement = InventoryMovement.objects.create(
            product=instance,
            quantity_in=qty_in,
            quantity_out=qty_out,
            waste=waste,
            quantity_before=qty_before,
            quantity_after=qty_after,
            unit_price=unit_price,
            balance=balance,
            stock_balance_remaining=stock_balance_remaining,
            waste_value=waste_value,
            approval_status=new_approval,
            stock_status=instance.stock_status,
            remark=remark,
            created_by=instance.created_by,
        )
        _sync_inventory_movement_to_accounting(movement)
    finally:
        _clean_movement_attrs(instance)


@receiver(post_save, sender=Inventory)
def clear_inventory_cache_on_save(sender, instance, **kwargs):
    _clear_company_inventory_cache(instance)


@receiver(post_delete, sender=Inventory)
def clear_inventory_cache_on_delete(sender, instance, **kwargs):
    _clear_company_inventory_cache(instance)


@receiver(post_save, sender=WasteLog)
def clear_inventory_cache_on_waste_log_save(sender, instance, **kwargs):
    _clear_company_inventory_cache(instance.inventory)


@receiver(post_delete, sender=WasteLog)
def clear_inventory_cache_on_waste_log_delete(sender, instance, **kwargs):
    if instance.inventory_id:
        _clear_company_inventory_cache(instance.inventory)


@receiver(post_save, sender=InventoryIssue)
def clear_inventory_cache_on_issue_save(sender, instance, **kwargs):
    _clear_company_inventory_cache(instance.inventory)


@receiver(post_delete, sender=InventoryIssue)
def clear_inventory_cache_on_issue_delete(sender, instance, **kwargs):
    if instance.inventory_id:
        _clear_company_inventory_cache(instance.inventory)


@receiver(post_save, sender=InventoryReceipt)
def clear_inventory_cache_on_receipt_save(sender, instance, **kwargs):
    _clear_company_inventory_cache(instance.inventory)


@receiver(post_delete, sender=InventoryReceipt)
def clear_inventory_cache_on_receipt_delete(sender, instance, **kwargs):
    if instance.inventory_id:
        _clear_company_inventory_cache(instance.inventory)
