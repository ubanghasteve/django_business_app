# Generated for offline-first SyncMixin (uuid + is_deleted)

import uuid
from django.db import migrations, models


def fill_client_uuids(apps, schema_editor):
    Client = apps.get_model('clients', 'Client')
    for obj in Client.objects.all():
        obj.uuid = uuid.uuid4()
        obj.save(update_fields=['uuid'])


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0002_add_client_source_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='client',
            name='uuid',
            field=models.UUIDField(blank=True, default=None, editable=False, null=True, unique=False),
        ),
        migrations.AddField(
            model_name='client',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(fill_client_uuids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='client',
            name='uuid',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
