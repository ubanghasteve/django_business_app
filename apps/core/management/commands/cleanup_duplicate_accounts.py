"""
Remove duplicate Account rows so each owner has exactly one Account (the one they use).

Keeps the "primary" account for each owner (the one where user.account_id == account.id)
and deletes other Account rows with the same owner. Only deletes duplicates that have
no CompanyProfile to avoid data loss.

Usage:
  python manage.py cleanup_duplicate_accounts
  python manage.py cleanup_duplicate_accounts --dry-run  # show what would be deleted
"""
from django.core.management.base import BaseCommand
from django.db.models import Count

from apps.core.models import Account, CompanyProfile
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = "Delete duplicate Account rows (keep one per owner = the one user.account points to)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Only show what would be deleted, do not delete.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN: no changes will be made.'))

        # Fix owners who have no account_id set: point them to their first owned account so admin "primary" filter works
        fixed_users = 0
        for user in User.objects.filter(account_id__isnull=True, owned_accounts__isnull=False).distinct():
            first_account = Account.objects.filter(owner_id=user.pk).order_by('id').first()
            if first_account:
                if not dry_run:
                    user.account_id = first_account.id
                    user.save(update_fields=['account_id'])
                self.stdout.write(
                    f'{"Would set" if dry_run else "Set"} user {user.email} account_id -> {first_account.id}'
                )
                fixed_users += 1
        if fixed_users:
            self.stdout.write(self.style.SUCCESS(f'{"Would fix" if dry_run else "Fixed"} {fixed_users} user(s) with missing account_id.'))

        # Owners that have more than one Account
        owner_counts = (
            Account.objects.filter(owner_id__isnull=False)
            .values('owner_id')
            .annotate(count=Count('id'))
            .filter(count__gt=1)
        )
        owner_ids = [r['owner_id'] for r in owner_counts]

        if not owner_ids:
            self.stdout.write(self.style.SUCCESS('No duplicate accounts found.'))
            return

        deleted = 0
        skipped = 0
        for owner_id in owner_ids:
            try:
                user = User.objects.get(pk=owner_id)
            except User.DoesNotExist:
                self.stdout.write(self.style.WARNING(f'Owner id={owner_id} not found, skipping.'))
                continue

            primary_account_id = getattr(user, 'account_id', None)
            duplicates = Account.objects.filter(owner_id=owner_id).exclude(pk=primary_account_id)

            for acc in duplicates:
                has_profile = CompanyProfile.objects.filter(account=acc).exists()
                if has_profile:
                    self.stdout.write(
                        self.style.WARNING(
                            f'Skipping Account id={acc.id} (owner={user.email}): has CompanyProfile.'
                        )
                    )
                    skipped += 1
                    continue
                if dry_run:
                    self.stdout.write(
                        f'Would delete Account id={acc.id} name="{acc.name}" owner={user.email}'
                    )
                else:
                    acc.delete()
                    self.stdout.write(
                        self.style.SUCCESS(f'Deleted duplicate Account id={acc.id} (owner={user.email})')
                    )
                deleted += 1

        if dry_run:
            self.stdout.write(self.style.WARNING(f'Would delete {deleted} duplicate account(s).'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Deleted {deleted} duplicate account(s).'))
        if skipped:
            self.stdout.write(self.style.WARNING(f'Skipped {skipped} (have CompanyProfile).'))
