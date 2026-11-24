from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Add all staff offence permissions to every Company Admin group.'

    def handle(self, *args, **options):
        from apps.accounts.services import sync_staff_offence_permissions_to_company_admin
        updated = sync_staff_offence_permissions_to_company_admin()
        self.stdout.write(self.style.SUCCESS(
            f'Updated {updated} Company Admin group(s) with staff offence permissions.'
        ))
