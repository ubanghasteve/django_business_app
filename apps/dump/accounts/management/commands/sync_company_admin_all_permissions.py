"""
Give every Company Admin role (all accounts) full permissions from the database.

Run from Django admin or CLI so Company Admin can use all app features.
Updates all AccountGroups with role_name="Company Admin" to have every
Permission in the database.

Usage:
  python manage.py sync_company_admin_all_permissions
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import AccountGroup
from apps.accounts.default_role import COMPANY_ADMIN_ROLE_NAME
from apps.accounts.services import (
    get_all_permission_codenames,
    update_account_group_permissions,
)


class Command(BaseCommand):
    help = (
        "Assign ALL permissions (from the database) to every Company Admin role "
        "across all accounts. Includes inventory (view/add/change/delete/print/download), "
        "requisitions, and every other app. Run after migrate or adding new apps so "
        "Company Admin and approved users keep full access."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without changing the database.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        codenames = get_all_permission_codenames()
        self.stdout.write(f"Total permissions in DB: {len(codenames)}")

        qs = AccountGroup.objects.filter(
            role_name=COMPANY_ADMIN_ROLE_NAME,
        ).select_related('group', 'account')
        count = qs.count()
        if count == 0:
            self.stdout.write(
                self.style.WARNING(
                    f'No AccountGroup with role_name="{COMPANY_ADMIN_ROLE_NAME}" found. '
                    'Create Company Admin roles per account (e.g. approve account in admin) first.'
                )
            )
            return

        self.stdout.write(f"Updating {count} Company Admin role(s) with all permissions.")

        if dry_run:
            self.stdout.write(self.style.SUCCESS("Dry run: no changes made."))
            return

        with transaction.atomic():
            for ag in qs:
                update_account_group_permissions(ag, codenames)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  Updated Company Admin for account {ag.account_id} ({getattr(ag.account, 'name', '') or ag.account_id})."
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. All Company Admin roles now have {len(codenames)} permissions."
            )
        )
