# -*- coding: utf-8 -*-
# InventoryMovement: immutable ledger of quantity changes per inventory record

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0009_add_sync_mixin'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='InventoryMovement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantity_in', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('quantity_out', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('quantity_before', models.DecimalField(decimal_places=2, help_text='Remaining quantity before this movement.', max_digits=14)),
                ('quantity_after', models.DecimalField(decimal_places=2, help_text='Remaining quantity after this movement.', max_digits=14)),
                ('unit_price', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('balance', models.DecimalField(decimal_places=2, default=0, help_text='Movement value = (quantity_in - quantity_out) × unit_price.', max_digits=16)),
                ('stock_balance_remaining', models.DecimalField(decimal_places=2, default=0, help_text='Quantity_after × unit_price.', max_digits=16)),
                ('approval_status', models.CharField(choices=[('draft', 'Draft'), ('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')], default='draft', help_text='Approval status of the inventory row at the time of movement.', max_length=20)),
                ('remark', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='inventory_movements_created', to=settings.AUTH_USER_MODEL)),
                ('product', models.ForeignKey(help_text='Inventory row this movement belongs to.', on_delete=django.db.models.deletion.PROTECT, related_name='movements', to='inventory.inventory')),
            ],
            options={
                'verbose_name': 'Inventory Movement',
                'verbose_name_plural': 'Inventory Movements',
                'ordering': ['-created_at'],
            },
        ),
    ]
