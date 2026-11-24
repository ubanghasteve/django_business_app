# Generated migration: add account FK to UserActivity and view_activity_log permission

from django.db import migrations, models
import django.db.models.deletion


def backfill_activity_account(apps, schema_editor):
    UserActivity = apps.get_model('accounts', 'UserActivity')
    User = apps.get_model('accounts', 'User')
    user_accounts = dict(User.objects.filter(account_id__isnull=False).values_list('id', 'account_id'))
    for row in UserActivity.objects.filter(user_id__isnull=False):
        aid = user_accounts.get(row.user_id)
        if aid:
            row.account_id = aid
            row.save(update_fields=['account_id'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_account_companyprofile_account'),
        ('accounts', '0008_subuser_linked_user_accountgroup'),
    ]

    operations = [
        migrations.AddField(
            model_name='useractivity',
            name='account',
            field=models.ForeignKey(
                blank=True,
                help_text='Account/company this activity belongs to; always set for authenticated actions.',
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='security_activities',
                to='core.account',
                db_index=True,
            ),
        ),
        migrations.RunPython(backfill_activity_account, noop),
        migrations.AddIndex(
            model_name='useractivity',
            index=models.Index(fields=['account', '-timestamp'], name='accounts_us_account_7a0b0d_idx'),
        ),
        migrations.AlterModelOptions(
            name='useractivity',
            options={
                'ordering': ['-timestamp'],
                'permissions': [('view_activity_log', 'View activity log')],
                'verbose_name': 'User Activity',
                'verbose_name_plural': 'User Activities',
            },
        ),
    ]
