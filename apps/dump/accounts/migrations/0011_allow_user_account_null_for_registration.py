# Allow User.account to be null so registration can create User first,
# then Account(owner=user), then set user.account (breaking the circular dependency).

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0010_rename_accounts_us_account_7a0b0d_idx_accounts_us_account_f02fc6_idx'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='account',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='users',
                to='core.account',
                help_text='Owning account / tenant for this user',
            ),
        ),
    ]
