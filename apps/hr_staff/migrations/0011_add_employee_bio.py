from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hr_staff', '0010_add_employee_sync_mixin'),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='bio',
            field=models.TextField(blank=True, default='', help_text='Short bio or notes for this employee.'),
        ),
    ]

