# Generated for offline-first sync (soft delete)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0006_fix_orphaned_ledger_company'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
    ]
