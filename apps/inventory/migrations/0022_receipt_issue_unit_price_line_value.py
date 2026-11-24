# -*- coding: utf-8 -*-
from decimal import Decimal

from django.db import migrations, models


def backfill_ledger_prices(apps, schema_editor):
    InventoryReceipt = apps.get_model('inventory', 'InventoryReceipt')
    InventoryIssue = apps.get_model('inventory', 'InventoryIssue')
    for receipt in InventoryReceipt.objects.select_related('inventory').iterator():
        inv = receipt.inventory
        up = inv.unit_price if inv else Decimal('0')
        qty = receipt.quantity or Decimal('0')
        InventoryReceipt.objects.filter(pk=receipt.pk).update(
            unit_price=up,
            line_value=qty * up,
        )
    for issue in InventoryIssue.objects.select_related('inventory').iterator():
        inv = issue.inventory
        up = inv.unit_price if inv else Decimal('0')
        qty = issue.quantity or Decimal('0')
        InventoryIssue.objects.filter(pk=issue.pk).update(
            unit_price=up,
            line_value=qty * up,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0021_inventory_receipt_waste_quantity_input'),
    ]

    operations = [
        migrations.AddField(
            model_name='inventoryreceipt',
            name='unit_price',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0'),
                help_text='Unit price when this receipt was recorded.',
                max_digits=14,
            ),
        ),
        migrations.AddField(
            model_name='inventoryreceipt',
            name='line_value',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0'),
                help_text='Value of this line = quantity × unit_price at recording time.',
                max_digits=16,
            ),
        ),
        migrations.AddField(
            model_name='inventoryissue',
            name='unit_price',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0'),
                help_text='Unit price when this withdrawal was recorded.',
                max_digits=14,
            ),
        ),
        migrations.AddField(
            model_name='inventoryissue',
            name='line_value',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0'),
                help_text='Value of this line = quantity × unit_price at recording time.',
                max_digits=16,
            ),
        ),
        migrations.RunPython(backfill_ledger_prices, migrations.RunPython.noop),
    ]
