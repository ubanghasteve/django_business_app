# Generated for HR employee portal: force password change on first login after temp password.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0013_remove_expense_management_permissions'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='force_password_change',
            field=models.BooleanField(default=False, verbose_name='Force password change on next login'),
        ),
    ]
