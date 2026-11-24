# -*- coding: utf-8 -*-
"""
Management command: sync Bulk Mailing permissions to all Company Admin groups.

Usage:
    python manage.py sync_mailing_permissions

Run after adding the mailing app or when new mailing permissions are added.
Ensures every Company Admin role has use_bulk_mailing so approved company admins
see Bulk Mailing in the nav and can send bulk email/SMS.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Add all Bulk Mailing permissions to every Company Admin group.'

    def handle(self, *args, **options):
        try:
            from apps.accounts.services import sync_mailing_permissions_to_company_admin
            updated = sync_mailing_permissions_to_company_admin()
            self.stdout.write(
                self.style.SUCCESS(
                    f'Synced Bulk Mailing permissions to {updated} Company Admin group(s).'
                )
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error: {e}'))
