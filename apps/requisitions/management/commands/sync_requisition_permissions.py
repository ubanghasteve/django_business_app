# -*- coding: utf-8 -*-
"""
Management command: sync requisition permissions to all Company Admin groups.

Usage:
    python manage.py sync_requisition_permissions

Run after adding the requisitions app or when new requisition permissions are added.
Company Read Only groups are unchanged (they get view_* only via core signals).
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Add all requisition permissions to every Company Admin group.'

    def handle(self, *args, **options):
        try:
            from apps.accounts.services import sync_requisition_permissions_to_company_admin
            updated = sync_requisition_permissions_to_company_admin()
            self.stdout.write(
                self.style.SUCCESS(f'Synced requisition permissions to {updated} Company Admin group(s).')
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error: {e}'))
