# Generated manually: replace Employee FK with typed staff_name

from django.db import migrations, models


def copy_employee_names(apps, schema_editor):
    Register = apps.get_model('staff_offences', 'StaffOffenceRegister')
    for reg in Register.objects.select_related('employee').all():
        emp = getattr(reg, 'employee', None)
        if emp:
            name = f'{getattr(emp, "first_name", "")} {getattr(emp, "last_name", "")}'.strip()
            reg.staff_name = name or 'Unknown'
            if not reg.department_name and getattr(emp, 'department_id', None):
                dept = getattr(emp, 'department', None)
                if dept:
                    reg.department_name = dept.name or ''
            reg.save(update_fields=['staff_name', 'department_name'])
        elif not reg.staff_name:
            reg.staff_name = 'Unknown'
            reg.save(update_fields=['staff_name'])


class Migration(migrations.Migration):

    dependencies = [
        ('staff_offences', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='staffoffenceregister',
            name='staff_name',
            field=models.CharField(
                default='',
                help_text='Staff member name typed by HR (not linked to HR employee records).',
                max_length=255,
            ),
            preserve_default=False,
        ),
        migrations.RunPython(copy_employee_names, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name='staffoffenceregister',
            name='unique_staff_offence_register_per_month',
        ),
        migrations.RemoveField(
            model_name='staffoffenceregister',
            name='employee',
        ),
        migrations.AlterField(
            model_name='staffoffenceregister',
            name='department_name',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Department name typed manually.',
                max_length=200,
            ),
        ),
        migrations.AddIndex(
            model_name='staffoffenceregister',
            index=models.Index(fields=['staff_name'], name='staff_offen_staff_n_7c0a1e_idx'),
        ),
        migrations.AddConstraint(
            model_name='staffoffenceregister',
            constraint=models.UniqueConstraint(
                fields=('account', 'staff_name', 'year', 'month'),
                name='unique_staff_offence_register_per_month',
            ),
        ),
    ]
