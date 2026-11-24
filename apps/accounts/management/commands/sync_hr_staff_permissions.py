# -*- coding: utf-8 -*-
"""
Management command: sync HR & Staff permissions to all Company Admin groups.

Usage:
    python manage.py sync_hr_staff_permissions

Run after adding the hr_staff app or when new HR permissions are added.
Ensures every Company Admin role has view/add/change/delete for Department,
Employee, and LeaveRequest so approved company admins see HR & Staff in the nav
and can access all HR features.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Add all HR & Staff permissions to every Company Admin group.'

    def handle(self, *args, **options):
        try:
            from apps.accounts.services import sync_hr_staff_permissions_to_company_admin
            updated = sync_hr_staff_permissions_to_company_admin()
            self.stdout.write(
                self.style.SUCCESS(
                    f'Synced HR & Staff permissions to {updated} Company Admin group(s).'
                )
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error: {e}'))
