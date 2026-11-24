# -*- coding: utf-8 -*-
"""
Recompute balance and stock_balance_remaining for all InventoryMovement records.

- balance = (quantity_in - quantity_out) × unit_price  (movement value)
- stock_balance_remaining = quantity_after × unit_price (value of remaining stock)

Run once after fixing the signal so existing report table rows add up correctly.
Uses bulk_update (no save()) so it works even though movements are immutable.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.inventory.models import InventoryMovement


def _decimal_safe(value, default=Decimal('0')):
    if value is None:
        return default
    try:
        d = Decimal(str(value))
        return d if not (d.is_nan() or d.is_infinite()) else default
    except Exception:
        return default


class Command(BaseCommand):
    help = (
        'Recompute balance and stock_balance_remaining for all InventoryMovement '
        'records so the report table Balance column matches (Qty In - Qty Out) × Unit Price.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch',
            type=int,
            default=500,
            help='Batch size for bulk_update (default 500).',
        )

    def handle(self, *args, **options):
        batch_size = options['batch']
        batch = []
        updated = 0
        for m in InventoryMovement.objects.all().order_by('pk'):
            m.balance = (_decimal_safe(m.quantity_in) - _decimal_safe(m.quantity_out)) * _decimal_safe(m.unit_price)
            m.stock_balance_remaining = _decimal_safe(m.quantity_after) * _decimal_safe(m.unit_price)
            batch.append(m)
            updated += 1
            if len(batch) >= batch_size:
                InventoryMovement.objects.bulk_update(batch, ['balance', 'stock_balance_remaining'])
                batch = []
        if batch:
            InventoryMovement.objects.bulk_update(batch, ['balance', 'stock_balance_remaining'])
        self.stdout.write(
            self.style.SUCCESS(f'Recomputed balance and stock_balance_remaining for {updated} movement(s).')
        )
