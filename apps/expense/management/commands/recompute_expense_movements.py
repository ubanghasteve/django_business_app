# -*- coding: utf-8 -*-
"""
Recompute balance and stock_value_remaining for all ExpenseMovement records.

- balance = (quantity_purchased - quantity_out) × unit_price
- stock_value_remaining = quantity_after × unit_price

Run once after fixing the signal so existing report table rows add up correctly.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.expense.models import ExpenseMovement


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
        'Recompute balance and stock_value_remaining for all ExpenseMovement '
        'records so the report table Balance column matches (Qty Purchased - Qty Out) × Unit Price.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--batch', type=int, default=500, help='Batch size for bulk_update.')

    def handle(self, *args, **options):
        batch_size = options['batch']
        batch = []
        updated = 0
        for m in ExpenseMovement.objects.all().order_by('pk'):
            m.balance = (_decimal_safe(m.quantity_purchased) - _decimal_safe(m.quantity_out)) * _decimal_safe(m.unit_price)
            m.stock_value_remaining = _decimal_safe(m.quantity_after) * _decimal_safe(m.unit_price)
            batch.append(m)
            updated += 1
            if len(batch) >= batch_size:
                ExpenseMovement.objects.bulk_update(batch, ['balance', 'stock_value_remaining'])
                batch = []
        if batch:
            ExpenseMovement.objects.bulk_update(batch, ['balance', 'stock_value_remaining'])
        self.stdout.write(self.style.SUCCESS(f'Recomputed balance and stock_value_remaining for {updated} movement(s).'))
