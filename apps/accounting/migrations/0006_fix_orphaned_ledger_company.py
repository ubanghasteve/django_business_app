# Fix orphaned Ledger rows whose company_id does not exist in core_companyprofile.
# This resolves IntegrityError when SQLite runs foreign key check after migrations.

from django.db import migrations


def delete_orphaned_ledgers(apps, schema_editor):
    Ledger = apps.get_model('accounting', 'Ledger')
    CompanyProfile = apps.get_model('core', 'CompanyProfile')
    valid_company_ids = set(CompanyProfile.objects.values_list('id', flat=True))
    deleted, _ = Ledger.objects.exclude(company_id__in=valid_company_ids).delete()
    if deleted:
        # Log only if we actually delete (migration output)
        pass


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0005_decimal_max_digits_64'),
    ]

    operations = [
        migrations.RunPython(delete_orphaned_ledgers, noop),
    ]
