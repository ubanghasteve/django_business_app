# Generated manually for per-register authorized signature

from django.db import migrations, models
import apps.staff_offences.models


class Migration(migrations.Migration):

    dependencies = [
        ('staff_offences', '0002_manual_staff_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='staffoffenceregister',
            name='authorized_signature',
            field=models.ImageField(
                blank=True,
                help_text='Authorized signature for this monthly register only (not shared across registers).',
                null=True,
                upload_to=apps.staff_offences.models.staff_offence_signature_upload_path,
            ),
        ),
        migrations.AddField(
            model_name='staffoffenceregister',
            name='authorized_signatory_name',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Name of the person who authorized/signed this register.',
                max_length=255,
            ),
        ),
    ]
