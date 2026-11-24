# Data migration: approve all existing accounts so they are not locked out.

from django.db import migrations


def approve_existing_accounts(apps, schema_editor):
    """Set is_approved=True for all existing accounts (backfill for migration 0006)."""
    Account = apps.get_model('core', 'Account')
    Account.objects.all().update(is_approved=True)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_add_account_is_approved'),
    ]

    operations = [
        migrations.RunPython(approve_existing_accounts, migrations.RunPython.noop),
    ]
