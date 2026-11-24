# Migration: add SyncMixin fields to LeaveRequest with unique UUID backfill
# Fixes "Callable default on unique field leaverequest.uuid will not generate unique values"

import uuid
from django.utils import timezone
from django.db import migrations, models


def fill_leaverequest_sync_fields(apps, schema_editor):
    LeaveRequest = apps.get_model('hr_staff', 'LeaveRequest')
    for obj in LeaveRequest.objects.all():
        if obj.uuid is None:
            obj.uuid = uuid.uuid4()
        if getattr(obj, 'updated_at', None) is None:
            obj.updated_at = getattr(obj, 'created_at', None) or timezone.now()
        obj.save(update_fields=['uuid', 'updated_at'])


class Migration(migrations.Migration):

    dependencies = [
        ('hr_staff', '0013_department_sync_mixin'),
    ]

    operations = [
        migrations.AddField(
            model_name='leaverequest',
            name='uuid',
            field=models.UUIDField(editable=False, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='leaverequest',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.AddField(
            model_name='leaverequest',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(fill_leaverequest_sync_fields, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='leaverequest',
            name='uuid',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AlterField(
            model_name='leaverequest',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
    ]
