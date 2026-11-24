# Add full_company_visibility to AccountGroup so super admins can create
# multiple custom-named roles (e.g. Company Read Only 1, 2, 3) with full
# company visibility and exactly the permissions they assign (no stripping).

from django.db import migrations, models


def backfill_full_company_visibility(apps, schema_editor):
    AccountGroup = apps.get_model('accounts', 'AccountGroup')
    # Preserve current behavior: existing roles named "Company Read Only" get the flag.
    AccountGroup.objects.filter(
        role_name__iexact='Company Read Only'
    ).update(full_company_visibility=True)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0011_allow_user_account_null_for_registration'),
    ]

    operations = [
        migrations.AddField(
            model_name='accountgroup',
            name='full_company_visibility',
            field=models.BooleanField(
                default=False,
                help_text='Users in this role see all company records (no data isolation). Use for read-only style roles with any name. Permissions are exactly what you assign below.'
            ),
        ),
        migrations.RunPython(backfill_full_company_visibility, noop_reverse),
    ]
