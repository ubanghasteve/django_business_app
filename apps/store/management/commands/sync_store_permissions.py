# -*- coding: utf-8 -*-
"""
Management command: sync store permissions to all Company Admin groups.

Ensures every Company Admin role has all store permissions (view, add,
change, delete, print_store, download_store). Run after `migrate` so
Django has created the permissions in auth_permission.

Usage:
  python manage.py sync_store_permissions

For full sync of all app permissions (including store) for Company Admin, use:
  python manage.py sync_company_admin_all_permissions
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        'Add all store permissions to every Company Admin group. '
        'Run migrate first so Django has created store permissions.'
    )

    def handle(self, *args, **options):
        try:
            from apps.accounts.services import sync_store_permissions_to_company_admin
            updated = sync_store_permissions_to_company_admin()
            self.stdout.write(
                self.style.SUCCESS(f'Synced store permissions to {updated} Company Admin group(s).')
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error: {e}'))
