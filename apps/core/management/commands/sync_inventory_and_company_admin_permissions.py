"""
One-shot sync: give every Company Admin group ALL permissions (including inventory).

Use this after migrate or when you want to ensure Company Admin and any
approved users have full access to Inventory and all other apps.

- Updates Django auth_permission usage: every Company Admin group gets every
  permission in the database (inventory view/add/change/delete/print/download,
  requisitions, invoices, etc.).
- Super admin (Django superuser) already has all permissions by default.

Usage:
  python manage.py sync_inventory_and_company_admin_permissions
  python manage.py sync_inventory_and_company_admin_permissions --dry-run
"""
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = (
        'Give every Company Admin role all permissions (including all inventory permissions). '
        'Run after migrate so auth_permission is up to date.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without changing the database.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run — no changes will be made.'))

        try:
            from apps.accounts.models import AccountGroup
            from apps.accounts.default_role import COMPANY_ADMIN_ROLE_NAME
            from apps.accounts.services import (
                get_all_permission_codenames,
                update_account_group_permissions,
                sync_inventory_permissions_to_company_admin,
            )
        except ImportError as e:
            self.stdout.write(self.style.ERROR(f'Import error: {e}'))
            return

        codenames = get_all_permission_codenames()
        auth_extra = ['auth.view_group', 'auth.add_group', 'auth.change_group', 'auth.delete_group']
        for c in auth_extra:
            if c not in codenames:
                codenames.append(c)

        qs = AccountGroup.objects.filter(role_name=COMPANY_ADMIN_ROLE_NAME).select_related('group', 'account')
        count = qs.count()
        if count == 0:
            self.stdout.write(
                self.style.WARNING(
                    f'No AccountGroup with role_name="{COMPANY_ADMIN_ROLE_NAME}" found. '
                    'Approve an account in Django admin to create Company Admin roles first.'
                )
            )
            return

        self.stdout.write(f'Total permissions in DB: {len(codenames)} (includes all inventory).')
        self.stdout.write(f'Updating {count} Company Admin role(s).')

        if dry_run:
            self.stdout.write(self.style.SUCCESS('Dry run: no changes made.'))
            return

        with transaction.atomic():
            for ag in qs:
                update_account_group_permissions(ag, codenames)
                self.stdout.write(
                    self.style.SUCCESS(f'  Updated Company Admin for account {ag.account_id}.')
                )
            # Belt-and-suspenders: ensure inventory perms are on every Company Admin
            updated = sync_inventory_permissions_to_company_admin()
            if updated:
                self.stdout.write(
                    self.style.SUCCESS(f'  Synced inventory permissions to {updated} Company Admin group(s).')
                )

        self.stdout.write(
            self.style.SUCCESS(
                f'\nDone. All Company Admin roles now have {len(codenames)} permissions (including inventory).'
            )
        )
