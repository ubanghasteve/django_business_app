# Generated for offline-first SyncMixin (uuid + is_deleted)

import uuid
from django.db import migrations, models


def fill_inventory_uuids(apps, schema_editor):
    Inventory = apps.get_model('inventory', 'Inventory')
    for obj in Inventory.objects.all():
        obj.uuid = uuid.uuid4()
        obj.save(update_fields=['uuid'])


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0008_add_stock_balance_remaining'),
    ]

    operations = [
        migrations.AddField(
            model_name='inventory',
            name='uuid',
            field=models.UUIDField(blank=True, default=None, editable=False, null=True, unique=False),
        ),
        migrations.AddField(
            model_name='inventory',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(fill_inventory_uuids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='inventory',
            name='uuid',
            field=models.UUIDField(default=uuid.uuid4, editable=False, null=False, unique=True),
        ),
    ]
