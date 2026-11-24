# Migration: transaction_id unique per company (4-digit INV-XXXX), not globally unique

from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0003_inventory_company_name'),
    ]

    operations = [
        # Remove global unique so same INV-XXXX can exist in different companies
        migrations.AlterField(
            model_name='inventory',
            name='transaction_id',
            field=models.CharField(
                editable=False,
                help_text='INV- + 4 unique digits per company (e.g. INV-3847).',
                max_length=64,
            ),
        ),
        # Enforce uniqueness of transaction_id within each company
        migrations.AddConstraint(
            model_name='inventory',
            constraint=models.UniqueConstraint(
                condition=Q(company_id__isnull=False),
                fields=('company', 'transaction_id'),
                name='inventory_company_txn_id_uniq',
            ),
        ),
    ]
