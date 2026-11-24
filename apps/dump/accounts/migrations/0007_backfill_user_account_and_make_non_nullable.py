from django.db import migrations, models
import django.db.models.deletion


def backfill_user_account(apps, schema_editor):
    """
    Ensure every existing User row is linked to exactly one Account.

    Strategy:
    - If an Account already exists with owner=user, reuse it.
    - Otherwise, create a new Account with owner=user and a best-effort name.
    """
    User = apps.get_model('accounts', 'User')
    Account = apps.get_model('core', 'Account')

    for user in User.objects.filter(account__isnull=True):
        # Try to find an existing account owned by this user
        account = Account.objects.filter(owner=user).first()
        if account is None:
            full_name = f'{user.first_name} {user.last_name}'.strip()
            name = full_name or user.email or ''
            account = Account.objects.create(owner=user, name=name)
        user.account = account
        user.save(update_fields=['account'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_account_companyprofile_account'),
        ('accounts', '0006_add_subuser_is_staff'),
    ]

    operations = [
        # 1. Add account FK as nullable so the column exists
        migrations.AddField(
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
        # 2. Backfill: set account for every user that has none
        migrations.RunPython(backfill_user_account, migrations.RunPython.noop),
        # 3. Make account non-nullable
        migrations.AlterField(
            model_name='user',
            name='account',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='users',
                to='core.account',
                help_text='Owning account / tenant for this user',
            ),
        ),
    ]

