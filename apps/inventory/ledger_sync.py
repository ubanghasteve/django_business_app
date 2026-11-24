# -*- coding: utf-8 -*-
"""
Keep Inventory.quantity_in / quantity_out / waste aligned with receipt, issue,
and waste-log ledgers. Full repair runs only when data looks out of sync.
"""
from decimal import Decimal

from django.db.models import Count, Sum

from .models import (
    Inventory,
    InventoryIssue,
    InventoryReceipt,
    WasteLog,
    _decimal_safe,
    compose_total_quantity_input,
)

_TOLERANCE = Decimal('0.01')


def inventory_with_ledger_stats(pk):
    """Single query: inventory row + ledger counts and sums."""
    return (
        Inventory.objects.filter(pk=pk)
        .annotate(
            issue_count=Count('issues', distinct=True),
            receipt_count=Count('receipts', distinct=True),
            waste_log_count=Count('waste_logs', distinct=True),
            issues_sum=Sum('issues__quantity'),
            receipts_sum=Sum('receipts__quantity'),
            waste_logs_sum=Sum('waste_logs__quantity'),
        )
        .first()
    )


def needs_ledger_repair(inv):
    """
    Cheap check: True only when header totals and ledger lines likely disagree.
    """
    if inv is None:
        return False
    issue_count = getattr(inv, 'issue_count', None)
    if issue_count is None:
        issue_count = InventoryIssue.objects.filter(inventory_id=inv.pk).count()
    receipt_count = getattr(inv, 'receipt_count', None)
    if receipt_count is None:
        receipt_count = InventoryReceipt.objects.filter(inventory_id=inv.pk).count()
    waste_log_count = getattr(inv, 'waste_log_count', None)
    if waste_log_count is None:
        waste_log_count = WasteLog.objects.filter(inventory_id=inv.pk).count()

    qty_in = _decimal_safe(inv.quantity_in)
    qty_out = _decimal_safe(inv.quantity_out)
    waste = _decimal_safe(inv.waste)
    issues_sum = _decimal_safe(getattr(inv, 'issues_sum', None))
    receipts_sum = _decimal_safe(getattr(inv, 'receipts_sum', None))
    waste_sum = _decimal_safe(getattr(inv, 'waste_logs_sum', None))

    if issue_count:
        if abs(issues_sum - qty_out) > _TOLERANCE:
            return True
    elif qty_out > _TOLERANCE:
        return True

    if receipt_count:
        if abs(receipts_sum - qty_in) > _TOLERANCE:
            return True
    elif qty_in > _TOLERANCE:
        return True

    if waste_log_count:
        if abs(waste_sum - waste) > _TOLERANCE:
            return True
    elif waste > _TOLERANCE:
        return True

    return False


def sync_inventory_from_ledgers(inventory, *, skip_repair=False):
    """
    Re-aggregate quantity_in, quantity_out, and waste from log tables, then save
    once so Net qty, Balance qty, stock value remaining, and stock status stay
    aligned with every ledger (receipts, withdrawals, waste).
    """
    if isinstance(inventory, int):
        pk = inventory
    else:
        pk = inventory.pk

    inv = Inventory.objects.get(pk=pk)
    if not skip_repair:
        InventoryReceipt._repair_legacy_receipts(inv)
        InventoryIssue._repair_legacy_from_movements(inv)
        WasteLog._repair_legacy_waste(inv)
        inv = Inventory.objects.get(pk=pk)

    receipts = InventoryReceipt.objects.filter(inventory_id=pk)
    if receipts.exists():
        total_in = _decimal_safe(receipts.aggregate(total=Sum('quantity'))['total'])
        inv.quantity_in = total_in
        inv.quantity_in_input = compose_total_quantity_input(
            total_in,
            list(receipts.values_list('quantity_input', flat=True)),
        )
    else:
        inv.quantity_in = Decimal('0')
        inv.quantity_in_input = ''

    issues = InventoryIssue.objects.filter(inventory_id=pk)
    if issues.exists():
        total_out = _decimal_safe(issues.aggregate(total=Sum('quantity'))['total'])
        inv.quantity_out = total_out
        inv.quantity_out_input = compose_total_quantity_input(
            total_out,
            list(issues.values_list('quantity_input', flat=True)),
        )
    else:
        inv.quantity_out = Decimal('0')
        inv.quantity_out_input = ''

    waste_logs = WasteLog.objects.filter(inventory_id=pk)
    if waste_logs.exists():
        inv.waste = _decimal_safe(waste_logs.aggregate(total=Sum('quantity'))['total'])
    else:
        inv.waste = Decimal('0')

    inv.save()
    return inv


def sync_inventory_row(inventory, *, repair=None):
    """
    Repair (if needed) and sync header fields from logs.
    Set repair=True to force; False to skip repair; None = auto-detect.
    """
    if isinstance(inventory, int):
        inventory = inventory_with_ledger_stats(inventory) or Inventory.objects.get(pk=inventory)
    pk = inventory.pk

    if repair is None:
        repair = needs_ledger_repair(inventory)
    if not repair:
        return sync_inventory_from_ledgers(inventory, skip_repair=True)

    InventoryReceipt._repair_legacy_receipts(inventory)
    InventoryIssue._repair_legacy_from_movements(inventory)
    WasteLog._repair_legacy_waste(inventory)

    return sync_inventory_from_ledgers(pk, skip_repair=True)


def prepare_inventory_for_panel(inventory):
    """
    Fast path for dropdown panels: repair only when clearly out of sync.
    """
    if isinstance(inventory, int):
        inv = inventory_with_ledger_stats(inventory)
        if not inv:
            return None
    else:
        inv = inventory_with_ledger_stats(inventory.pk) or inventory
    try:
        if needs_ledger_repair(inv):
            return sync_inventory_row(inv, repair=True)
    except Exception:
        pk = inv.pk
        return Inventory.objects.filter(pk=pk).first()
    return inv
