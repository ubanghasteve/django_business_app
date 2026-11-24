# Migration: add SyncMixin fields to Department with unique UUID backfill
# Fixes "Callable default on unique field department.uuid will not generate unique values"

import uuid
from django.utils import timezone
from django.db import migrations, models


def fill_department_sync_fields(apps, schema_editor):
    Department = apps.get_model('hr_staff', 'Department')
    for obj in Department.objects.all():
        if obj.uuid is None:
            obj.uuid = uuid.uuid4()
        if getattr(obj, 'updated_at', None) is None:
            obj.updated_at = getattr(obj, 'created_at', None) or timezone.now()
        obj.save(update_fields=['uuid', 'updated_at'])


class Migration(migrations.Migration):

    dependencies = [
        ('hr_staff', '0012_leaverequest_status_changed_at_and_more'),
    ]

    operations = [
        # 1) Add uuid as nullable so existing rows get NULL
        migrations.AddField(
            model_name='department',
            name='uuid',
            field=models.UUIDField(editable=False, null=True, unique=True),
        ),
        # 2) Add other SyncMixin fields
        migrations.AddField(
            model_name='department',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.AddField(
            model_name='department',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
        # 3) Backfill unique UUIDs and updated_at for existing rows
        migrations.RunPython(fill_department_sync_fields, migrations.RunPython.noop),
        # 4) Make uuid non-null and set default for new rows
        migrations.AlterField(
            model_name='department',
            name='uuid',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        # 5) Make updated_at non-null (auto_now=True so no backfill needed)
        migrations.AlterField(
            model_name='department',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
    ]
