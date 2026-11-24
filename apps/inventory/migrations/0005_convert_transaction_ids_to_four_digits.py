# Data migration: convert old INV-<uuid> transaction_id to INV-XXXX per company

import re
from django.db import migrations


OLD_PATTERN = re.compile(r'^INV-[a-f0-9]{32}$')
SHORT_PATTERN = re.compile(r'^INV-(\d{4})$')


def convert_old_transaction_ids(apps, schema_editor):
    Inventory = apps.get_model('inventory', 'Inventory')
    # Process per company to keep uniqueness
    company_ids = list(
        Inventory.objects.values_list('company_id', flat=True).distinct()
    )
    for company_id in company_ids:
        if company_id is None:
            continue
        # Already-used 4-digit numbers in this company
        used = set()
        for inv in Inventory.objects.filter(company_id=company_id).only('transaction_id'):
            m = SHORT_PATTERN.match(inv.transaction_id)
            if m:
                used.add(int(m.group(1)))
        # Update records that still have old long format (order by created_at for stable IDs)
        for inv in (
            Inventory.objects.filter(company_id=company_id)
            .order_by('created_at', 'id')
        ):
            if not OLD_PATTERN.match(inv.transaction_id or ''):
                continue
            for candidate in range(1000, 10000):
                if candidate not in used:
                    used.add(candidate)
                    Inventory.objects.filter(pk=inv.pk).update(
                        transaction_id=f'INV-{candidate}'
                    )
                    break


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0004_transaction_id_unique_per_company'),
    ]

    operations = [
        migrations.RunPython(convert_old_transaction_ids, noop),
    ]
