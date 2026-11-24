"""
Create a full-access role for an account and optionally assign users to it.

Use when the Admin AccountGroup form doesn't work (e.g. linking existing groups).
This creates a NEW role via the service layer, bypassing the admin form.

Usage:
  python manage.py create_full_access_role --account-id=5
  python manage.py create_full_access_role --account-id=5 --assign-user=15
  python manage.py create_full_access_role --account-id=5 --assign-all-users
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.models import Account
from apps.accounts.models import User
from apps.accounts.services import create_account_group, set_user_account_role, get_all_permission_codenames


class Command(BaseCommand):
    help = (
        "Create a 'Company Admin' role with full permissions for an account. "
        "Optionally assign users to it."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--account-id',
            type=int,
            required=True,
            help='Account ID (from Core, Accounts).',
        )
        parser.add_argument(
            '--role-name',
            type=str,
            default='Company Admin',
            help='Role name (default: Company Admin). Must be unique per account.',
        )
        parser.add_argument(
            '--assign-user',
            type=int,
            action='append',
            dest='assign_users',
            default=[],
            metavar='USER_ID',
            help='User ID(s) to assign to this role. Can be repeated.',
        )
        parser.add_argument(
            '--assign-all-users',
            action='store_true',
            help='Assign all users in the account to this role.',
        )

    def handle(self, *args, **options):
        account_id = options['account_id']
        role_name = options['role_name']
        assign_users = options['assign_users']
        assign_all = options['assign_all_users']

        try:
            account = Account.objects.get(pk=account_id)
        except Account.DoesNotExist:
            self.stderr.write(self.style.ERROR(f'Account {account_id} does not exist.'))
            return

        permission_codenames = get_all_permission_codenames()

        with transaction.atomic():
            # Check if role already exists
            from apps.accounts.models import AccountGroup
            existing = AccountGroup.objects.filter(
                account=account,
                role_name__iexact=role_name,
            ).first()
            if existing:
                self.stdout.write(
                    self.style.WARNING(
                        f'Role "{role_name}" already exists for account {account.name} (pk={account.pk}). '
                        f'Using it.'
                    )
                )
                ag = existing
            else:
                ag = create_account_group(
                    account=account,
                    role_name=role_name,
                    permission_codenames=permission_codenames,
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Created role "{role_name}" for account {account.name} (pk={account.pk}).'
                    )
                )

            to_assign = []
            if assign_all:
                to_assign = list(User.objects.filter(account=account))
            elif assign_users:
                for uid in assign_users:
                    try:
                        u = User.objects.get(pk=uid, account=account)
                        to_assign.append(u)
                    except User.DoesNotExist:
                        self.stderr.write(
                            self.style.WARNING(
                                f'User {uid} not found or not in account {account_id}. Skipping.'
                            )
                        )

            for user in to_assign:
                try:
                    set_user_account_role(user, ag)
                    self.stdout.write(
                        self.style.SUCCESS(f'  Assigned {user.email} to "{role_name}".')
                    )
                except ValueError as e:
                    self.stderr.write(
                        self.style.WARNING(f'  Could not assign {user.email}: {e}')
                    )

        self.stdout.write(
            self.style.SUCCESS(
                f'\nDone. You can now assign users to "{role_name}" via '
                f'Admin > Accounts > Users > edit user > Groups.'
            )
        )
