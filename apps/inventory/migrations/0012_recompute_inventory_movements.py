from django.db import migrations
from decimal import Decimal


def recompute_inventory_movements(apps, schema_editor):
    InventoryMovement = apps.get_model('inventory', 'InventoryMovement')

    # Group by product so we can walk each product's history in time order.
    product_ids = (
        InventoryMovement.objects.order_by()
        .values_list('product_id', flat=True)
        .distinct()
    )
    for product_id in product_ids:
        movements = list(
            InventoryMovement.objects.filter(product_id=product_id)
            .order_by('created_at', 'id')
        )
        prev_remaining = Decimal('0')
        for m in movements:
            # Use existing quantity_after as the authoritative remaining qty after movement.
            new_remaining = m.quantity_after
            if new_remaining is None:
                continue
            try:
                new_remaining = Decimal(str(new_remaining))
            except Exception:
                continue
            old_remaining = prev_remaining
            diff = new_remaining - old_remaining
            if diff > 0:
                qty_in = diff
                qty_out = Decimal('0')
            else:
                qty_in = Decimal('0')
                qty_out = abs(diff)
            unit_price = Decimal(str(m.unit_price or 0))
            m.quantity_before = old_remaining
            m.quantity_in = qty_in
            m.quantity_out = qty_out
            m.balance = (qty_in - qty_out) * unit_price
            m.stock_balance_remaining = new_remaining * unit_price
            prev_remaining = new_remaining
        if movements:
            InventoryMovement.objects.bulk_update(
                movements,
                ['quantity_before', 'quantity_in', 'quantity_out', 'balance', 'stock_balance_remaining'],
            )


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0011_inventorymovement_stock_status'),
    ]

    operations = [
        migrations.RunPython(recompute_inventory_movements, migrations.RunPython.noop),
    ]

