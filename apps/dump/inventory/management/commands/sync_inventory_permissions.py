# -*- coding: utf-8 -*-
"""
Management command: sync inventory permissions to all Company Admin groups.

Ensures every Company Admin role has all inventory permissions (view, add,
change, delete, print_inventory, download_inventory). Run after `migrate` so
Django has created the permissions in auth_permission.

Usage:
  python manage.py sync_inventory_permissions

For full sync of all app permissions (including inventory) for Company Admin, use:
  python manage.py sync_company_admin_all_permissions
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        'Add all inventory permissions to every Company Admin group. '
        'Run migrate first so Django has created inventory permissions.'
    )

    def handle(self, *args, **options):
        try:
            from apps.accounts.services import sync_inventory_permissions_to_company_admin
            updated = sync_inventory_permissions_to_company_admin()
            self.stdout.write(
                self.style.SUCCESS(f'Synced inventory permissions to {updated} Company Admin group(s).')
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error: {e}'))
