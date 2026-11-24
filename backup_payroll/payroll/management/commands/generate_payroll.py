from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model

from apps.core.ownership import get_account_for_user
from apps.core.utils import get_company_profile_for_user
from apps.payroll.models import PayrollStructure
from apps.payroll.services import generate_payroll_run


User = get_user_model()


class Command(BaseCommand):
    help = "Generate payroll for a given month and year."

    def add_arguments(self, parser):
        parser.add_argument("--month", type=int, required=True, help="Payroll month (1-12)")
        parser.add_argument("--year", type=int, required=True, help="Payroll year, e.g. 2026")
        parser.add_argument(
            "--user-id",
            type=int,
            required=True,
            help="ID of the user who will be treated as the actor (must belong to the tenant).",
        )
        parser.add_argument(
            "--structure-id",
            type=int,
            default=None,
            help="Optional PayrollStructure ID to use.",
        )

    def handle(self, *args, **options):
        month = options["month"]
        year = options["year"]
        user_id = options["user_id"]
        structure_id = options.get("structure_id")

        if month < 1 or month > 12:
            raise CommandError("Month must be between 1 and 12.")

        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            raise CommandError(f"User with id={user_id} does not exist.")

        account = get_account_for_user(user)
        company = get_company_profile_for_user(user, request=None)
        if not account or not company:
            raise CommandError("User must be linked to an account and company.")

        structure = None
        if structure_id is not None:
            try:
                structure = PayrollStructure.objects.get(pk=structure_id, company=company)
            except PayrollStructure.DoesNotExist:
                raise CommandError(f"PayrollStructure with id={structure_id} not found for this company.")

        payroll_run = generate_payroll_run(user=user, month=month, year=year, structure=structure, request=None)
        self.stdout.write(
            self.style.SUCCESS(
                f"Payroll run {payroll_run.id} generated for {month}/{year} (status={payroll_run.status})."
            )
        )

