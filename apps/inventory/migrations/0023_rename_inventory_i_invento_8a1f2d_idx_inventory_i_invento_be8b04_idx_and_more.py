# Index renames are recorded in Django's migration state only.
# On MySQL the old index names from 0021 are often missing (auto-named indexes),
# so running ALTER RENAME would fail with error 1176. The indexes themselves are fine.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0022_receipt_issue_unit_price_line_value'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RenameIndex(
                    model_name='inventoryreceipt',
                    new_name='inventory_i_invento_be8b04_idx',
                    old_name='inventory_i_invento_8a1f2d_idx',
                ),
                migrations.RenameIndex(
                    model_name='inventoryreceipt',
                    new_name='inventory_i_company_984a57_idx',
                    old_name='inventory_i_company_4c2e1a_idx',
                ),
                migrations.RenameIndex(
                    model_name='inventoryreceipt',
                    new_name='inventory_i_supplie_57fce7_idx',
                    old_name='inventory_i_supplie_9b3f4c_idx',
                ),
            ],
        ),
    ]
