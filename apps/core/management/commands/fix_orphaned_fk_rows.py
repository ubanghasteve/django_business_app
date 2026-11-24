"""
Fix orphaned rows that cause IntegrityError when SQLite runs PRAGMA foreign_key_check
after migrations (e.g. accounting_ledger.company_id, core_useractivity.user_id).

Run once before migrate if you see:
  IntegrityError: ... has an invalid foreign key ...

Usage:
  python manage.py fix_orphaned_fk_rows
  python manage.py migrate
"""
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Delete orphaned rows so migrations can run (fixes FK integrity errors)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Only report what would be deleted.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run – no changes will be made.'))

        with connection.cursor() as cursor:
            # 1) accounting_ledger: delete rows whose company_id is not in core_companyprofile
            cursor.execute("""
                SELECT id, company_id FROM accounting_ledger
                WHERE company_id IS NOT NULL
                AND company_id NOT IN (SELECT id FROM core_companyprofile)
            """)
            ledger_orphans = cursor.fetchall()
            if ledger_orphans:
                self.stdout.write(
                    self.style.WARNING(
                        f'Found {len(ledger_orphans)} accounting_ledger row(s) with invalid company_id.'
                    )
                )
                if not dry_run:
                    cursor.execute("""
                        DELETE FROM accounting_ledger
                        WHERE company_id IS NOT NULL
                        AND company_id NOT IN (SELECT id FROM core_companyprofile)
                    """)
                    self.stdout.write(self.style.SUCCESS(f'  Deleted {cursor.rowcount} row(s).'))
            else:
                self.stdout.write('  accounting_ledger: no orphaned rows.')

            # 2) core_useractivity: delete rows whose user_id is not in auth user table
            # User table name from settings.AUTH_USER_MODEL (e.g. accounts.User -> accounts_user)
            from django.contrib.auth import get_user_model
            user_table = get_user_model()._meta.db_table
            cursor.execute("""
                SELECT id, user_id FROM core_useractivity
                WHERE user_id IS NOT NULL
                AND user_id NOT IN (SELECT id FROM """ + user_table + """)
            """)
            activity_orphans = cursor.fetchall()
            if activity_orphans:
                self.stdout.write(
                    self.style.WARNING(
                        f'Found {len(activity_orphans)} core_useractivity row(s) with invalid user_id.'
                    )
                )
                if not dry_run:
                    cursor.execute("""
                        DELETE FROM core_useractivity
                        WHERE user_id IS NOT NULL
                        AND user_id NOT IN (SELECT id FROM """ + user_table + """)
                    """)
                    self.stdout.write(self.style.SUCCESS(f'  Deleted {cursor.rowcount} row(s).'))
            else:
                self.stdout.write('  core_useractivity: no orphaned rows.')

        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run complete. Run without --dry-run to apply.'))
        else:
            self.stdout.write(self.style.SUCCESS('Done. You can now run: python manage.py migrate'))
