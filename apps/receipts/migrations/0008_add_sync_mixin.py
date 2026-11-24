# Generated for offline-first SyncMixin (uuid + is_deleted)

import uuid
from django.db import migrations, models


def fill_receipt_uuids(apps, schema_editor):
    Receipt = apps.get_model('receipts', 'Receipt')
    for obj in Receipt.objects.all():
        obj.uuid = uuid.uuid4()
        obj.save(update_fields=['uuid'])


class Migration(migrations.Migration):

    dependencies = [
        ('receipts', '0007_receipt_amount_max_digits_64'),
    ]

    operations = [
        migrations.AddField(
            model_name='receipt',
            name='uuid',
            field=models.UUIDField(blank=True, default=None, editable=False, null=True, unique=False),
        ),
        migrations.AddField(
            model_name='receipt',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(fill_receipt_uuids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='receipt',
            name='uuid',
            field=models.UUIDField(default=uuid.uuid4, editable=False, null=False, unique=True),
        ),
    ]
