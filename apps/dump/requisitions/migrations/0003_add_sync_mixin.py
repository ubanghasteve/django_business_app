# Generated for offline-first SyncMixin (uuid + is_deleted)

import uuid
from django.db import migrations, models


def fill_requisition_uuids(apps, schema_editor):
    Requisition = apps.get_model('requisitions', 'Requisition')
    for obj in Requisition.objects.all():
        obj.uuid = uuid.uuid4()
        obj.save(update_fields=['uuid'])


class Migration(migrations.Migration):

    dependencies = [
        ('requisitions', '0002_add_approved_by_approved_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='requisition',
            name='uuid',
            field=models.UUIDField(blank=True, default=None, editable=False, null=True, unique=False),
        ),
        migrations.AddField(
            model_name='requisition',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(fill_requisition_uuids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='requisition',
            name='uuid',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
