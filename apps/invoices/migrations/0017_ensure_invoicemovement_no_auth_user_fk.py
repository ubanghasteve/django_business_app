# -*- coding: utf-8 -*-
"""Ensure InvoiceMovement.created_by_id has no FK to auth_user (custom user model).

Production breakage: migration 0013 pointed created_by at auth.User. On hosts
using accounts.User, every invoice save that wrote a movement failed with a
foreign-key / missing auth_user error, surfacing as
"Could not save the invoice. Please try again."
"""

from django.db import migrations


def _ensure_created_by_id_no_fk(apps, schema_editor):
    connection = schema_editor.connection
    table = 'invoices_invoicemovement'

    with connection.cursor() as cursor:
        if connection.vendor == 'mysql':
            cursor.execute(
                """
                SELECT CONSTRAINT_NAME, COLUMN_NAME
                FROM information_schema.KEY_COLUMN_USAGE
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = %s
                  AND REFERENCED_TABLE_NAME IS NOT NULL
                """,
                [table],
            )
            for constraint_name, column_name in cursor.fetchall():
                if column_name in ('created_by', 'created_by_id'):
                    cursor.execute(
                        f'ALTER TABLE `{table}` DROP FOREIGN KEY `{constraint_name}`'
                    )

            cursor.execute(
                """
                SELECT COLUMN_NAME FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                """,
                [table],
            )
            cols = {row[0] for row in cursor.fetchall()}
            if not cols:
                return

            if 'created_by' in cols and 'created_by_id' not in cols:
                cursor.execute(
                    f'ALTER TABLE `{table}` CHANGE COLUMN `created_by` '
                    f'`created_by_id` INTEGER NULL'
                )
            elif 'created_by' in cols and 'created_by_id' in cols:
                cursor.execute(
                    f'ALTER TABLE `{table}` DROP COLUMN `created_by`'
                )
            elif 'created_by_id' not in cols:
                cursor.execute(
                    f'ALTER TABLE `{table}` ADD COLUMN `created_by_id` INTEGER NULL'
                )

        elif connection.vendor == 'sqlite':
            cursor.execute(f'PRAGMA table_info({table})')
            cols = {row[1] for row in cursor.fetchall()}
            if not cols:
                return
            if 'created_by' in cols and 'created_by_id' not in cols:
                cursor.execute(
                    f'ALTER TABLE {table} RENAME COLUMN created_by TO created_by_id'
                )


def _noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('invoices', '0016_drop_broken_invoicemovement_auth_user_fk'),
    ]

    operations = [
        migrations.RunPython(_ensure_created_by_id_no_fk, _noop),
    ]
