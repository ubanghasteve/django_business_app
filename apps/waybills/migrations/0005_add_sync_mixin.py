# Generated for offline-first SyncMixin (uuid + is_deleted)

import uuid
from django.db import migrations, models


def fill_waybill_uuids(apps, schema_editor):
    Waybill = apps.get_model('waybills', 'Waybill')
    for obj in Waybill.objects.all():
        obj.uuid = uuid.uuid4()
        obj.save(update_fields=['uuid'])


class Migration(migrations.Migration):

    dependencies = [
        ('waybills', '0004_rename_waybills_waybill_account_idx_waybills_wa_account_c8cb0a_idx'),
    ]

    operations = [
        migrations.AddField(
            model_name='waybill',
            name='uuid',
            field=models.UUIDField(blank=True, default=None, editable=False, null=True, unique=False),
        ),
        migrations.AddField(
            model_name='waybill',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(fill_waybill_uuids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='waybill',
            name='uuid',
            field=models.UUIDField(default=uuid.uuid4, editable=False, null=False, unique=True),
        ),
    ]
