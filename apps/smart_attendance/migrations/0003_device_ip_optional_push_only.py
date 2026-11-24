# Generated manually for push-only device support

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('smart_attendance', '0002_audit_add_shift_and_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='biometricdevice',
            name='device_ip',
            field=models.GenericIPAddressField(
                blank=True,
                help_text='Required for pull sync. Use 0.0.0.0 for push-only devices.',
                null=True,
            ),
        ),
    ]
