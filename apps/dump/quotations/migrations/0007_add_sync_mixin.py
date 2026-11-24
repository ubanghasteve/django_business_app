# Generated for offline-first SyncMixin (uuid + is_deleted)

import uuid
from django.db import migrations, models


def fill_quotation_uuids(apps, schema_editor):
    Quotation = apps.get_model('quotations', 'Quotation')
    for obj in Quotation.objects.all():
        obj.uuid = uuid.uuid4()
        obj.save(update_fields=['uuid'])


class Migration(migrations.Migration):

    dependencies = [
        ('quotations', '0006_rename_quotations__account_idx_quotations__account_f16a94_idx'),
    ]

    operations = [
        migrations.AddField(
            model_name='quotation',
            name='uuid',
            field=models.UUIDField(blank=True, default=None, editable=False, null=True, unique=False),
        ),
        migrations.AddField(
            model_name='quotation',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(fill_quotation_uuids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='quotation',
            name='uuid',
            field=models.UUIDField(default=uuid.uuid4, editable=False, null=False, unique=True),
        ),
    ]
