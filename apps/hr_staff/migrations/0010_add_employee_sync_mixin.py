# Generated for offline-first SyncMixin (uuid + is_deleted + updated_at) on Employee

import uuid
from django.db import migrations, models
from django.utils import timezone


def fill_employee_uuids_and_updated(apps, schema_editor):
    Employee = apps.get_model('hr_staff', 'Employee')
    now = timezone.now()
    for obj in Employee.objects.all():
        obj.uuid = uuid.uuid4()
        obj.updated_at = now
        obj.save(update_fields=['uuid', 'updated_at'])


class Migration(migrations.Migration):

    dependencies = [
        ('hr_staff', '0009_fix_portal_created_by_hr_for_admin_created'),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, default=timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='employee',
            name='uuid',
            field=models.UUIDField(blank=True, default=None, editable=False, null=True, unique=False),
        ),
        migrations.AddField(
            model_name='employee',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(fill_employee_uuids_and_updated, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='employee',
            name='uuid',
            field=models.UUIDField(default=uuid.uuid4, editable=False, null=False, unique=True),
        ),
    ]
