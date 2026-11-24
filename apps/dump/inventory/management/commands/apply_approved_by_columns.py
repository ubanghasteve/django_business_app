"""
One-time command to add approved_by_id and approved_at columns to inventory_inventory
when the normal migration fails due to unrelated DB constraint errors (e.g. accounting_ledger).
Run: python manage.py apply_approved_by_columns
Then the inventory detail page will work.
"""
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.utils import OperationalError


class Command(BaseCommand):
    help = 'Add approved_by_id and approved_at columns to inventory_inventory; then mark migration 0007 applied.'

    def handle(self, *args, **options):
        vendor = connection.vendor
        table = 'inventory_inventory'
        quoted_table = connection.ops.quote_name(table)

        with connection.cursor() as cursor:
            # Add columns (ignore if they already exist)
            for col, sql_sqlite, sql_mysql in [
                ('approved_at', f'ALTER TABLE {quoted_table} ADD COLUMN approved_at datetime NULL',
                 f'ALTER TABLE {quoted_table} ADD COLUMN approved_at datetime NULL'),
                ('approved_by_id', f'ALTER TABLE {quoted_table} ADD COLUMN approved_by_id integer NULL',
                 f'ALTER TABLE {quoted_table} ADD COLUMN approved_by_id integer NULL'),
            ]:
                try:
                    cursor.execute(sql_sqlite if vendor == 'sqlite' else sql_mysql)
                    self.stdout.write(f'Added column {col}.')
                except OperationalError as e:
                    if 'duplicate column' in str(e).lower() or 'already exists' in str(e).lower():
                        self.stdout.write(self.style.WARNING(f'Column {col} already exists, skipping.'))
                    else:
                        raise

            # Mark migration 0007 as applied so Django does not try to run it again
            cursor.execute(
                "SELECT 1 FROM django_migrations WHERE app = %s AND name = %s",
                ['inventory', '0007_add_approved_by_approved_at']
            )
            if not cursor.fetchone():
                if vendor == 'sqlite':
                    cursor.execute(
                        "INSERT INTO django_migrations (app, name, applied) VALUES (%s, %s, datetime('now'))",
                        ['inventory', '0007_add_approved_by_approved_at']
                    )
                else:
                    cursor.execute(
                        "INSERT INTO django_migrations (app, name, applied) VALUES (%s, %s, NOW())",
                        ['inventory', '0007_add_approved_by_approved_at']
                    )
                self.stdout.write('Marked migration 0007_add_approved_by_approved_at as applied.')
            else:
                self.stdout.write('Migration 0007 was already marked as applied.')

        self.stdout.write(self.style.SUCCESS('Done. Inventory detail page should work now.'))
