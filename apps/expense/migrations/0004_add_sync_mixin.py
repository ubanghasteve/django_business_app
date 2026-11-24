# Generated for offline-first SyncMixin (uuid + is_deleted)

import uuid
from django.db import migrations, models


def fill_expense_uuids(apps, schema_editor):
    Expense = apps.get_model('expense', 'Expense')
    for obj in Expense.objects.all():
        obj.uuid = uuid.uuid4()
        obj.save(update_fields=['uuid'])


class Migration(migrations.Migration):

    dependencies = [
        ('expense', '0003_alter_expense_options_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='expense',
            name='uuid',
            field=models.UUIDField(blank=True, default=None, editable=False, null=True, unique=False),
        ),
        migrations.AddField(
            model_name='expense',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(fill_expense_uuids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='expense',
            name='uuid',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
