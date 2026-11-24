"""
Fix approved account owners so they have full Company Admin access.

Ensures every approved account's owner is assigned to Company Admin with ALL
permissions. Use this to repair company admins who were approved before the
approval flow was fixed, or who have missing permissions.

Usage:
  python manage.py fix_approved_company_admin_permissions
  python manage.py fix_approved_company_admin_permissions --dry-run
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.models import Account
from apps.accounts.models import AccountGroup
from apps.accounts.default_role import COMPANY_ADMIN_ROLE_NAME
from apps.accounts.services import (
    create_account_group,
    update_account_group_permissions,
    assign_user_to_account_group,
    remove_user_from_account_group,
    get_or_create_default_onboarding_role,
    get_all_permission_codenames,
    _clear_user_permission_cache,
)


class Command(BaseCommand):
    help = (
        "Ensure every approved account's owner is in Company Admin with full permissions. "
        "Removes owner from default onboarding role and assigns to Company Admin."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run — no changes will be made.'))

        approved = Account.objects.filter(is_approved=True).select_related('owner')
        count = approved.count()
        if count == 0:
            self.stdout.write(self.style.WARNING('No approved accounts found.'))
            return

        codenames = get_all_permission_codenames()
        self.stdout.write(f'Found {count} approved account(s). Permissions: {len(codenames)}')

        fixed = 0
        for account in approved:
            owner = account.owner
            if not owner:
                self.stdout.write(
                    self.style.WARNING(f'  Account {account.pk} ({account.name}): no owner, skipping.')
                )
                continue
            if dry_run:
                self.stdout.write(
                    f'  Would fix: account {account.pk} ({account.name}), owner {owner.email}'
                )
                fixed += 1
                continue
            with transaction.atomic():
                default_ag = get_or_create_default_onboarding_role(account)
                remove_user_from_account_group(owner, default_ag)
                ag = AccountGroup.objects.filter(
                    account=account,
                    role_name=COMPANY_ADMIN_ROLE_NAME,
                ).select_related('group').first()
                if not ag:
                    ag = create_account_group(
                        account=account,
                        role_name=COMPANY_ADMIN_ROLE_NAME,
                        permission_codenames=codenames,
                    )
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'  Created Company Admin for account {account.pk} ({account.name})'
                        )
                    )
                else:
                    update_account_group_permissions(ag, codenames)
                assign_user_to_account_group(owner, ag)
                _clear_user_permission_cache(owner)
                fixed += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f'  Fixed: account {account.pk} ({account.name}), owner {owner.email}'
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(f'\nDone. Fixed {fixed} approved company admin(s).')
        )
