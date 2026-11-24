from django.core.management.base import BaseCommand
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError
from apps.core.models import CompanyProfile
from apps.payroll.models import (
    PayrollStructure,
    EmployeePayrollProfile,
    PayrollPeriod,
    PayrollRun,
    PayrollItem,
    Payslip,
    BonusRule,
    EmployeeBonus,
    EmployeeLoan,
    LoanRepayment,
    SalaryAdvance,
)


class Command(BaseCommand):
    help = "Sync payroll permissions for all company admins"

    def handle(self, *args, **options):
        content_types = {
            "payrollstructure": ContentType.objects.get_for_model(PayrollStructure),
            "employeepayrollprofile": ContentType.objects.get_for_model(EmployeePayrollProfile),
            "payrollperiod": ContentType.objects.get_for_model(PayrollPeriod),
            "payrollrun": ContentType.objects.get_for_model(PayrollRun),
            "payrollitem": ContentType.objects.get_for_model(PayrollItem),
            "payslip": ContentType.objects.get_for_model(Payslip),
            "bonusrule": ContentType.objects.get_for_model(BonusRule),
            "employeebonus": ContentType.objects.get_for_model(EmployeeBonus),
            "employeeloan": ContentType.objects.get_for_model(EmployeeLoan),
            "loanrepayment": ContentType.objects.get_for_model(LoanRepayment),
            "salaryadvance": ContentType.objects.get_for_model(SalaryAdvance),
        }

        perms_to_create = [
            # Payroll Structure
            ("view_payrollstructure", "Can view payroll structure", content_types["payrollstructure"]),
            ("add_payrollstructure", "Can add payroll structure", content_types["payrollstructure"]),
            ("change_payrollstructure", "Can change payroll structure", content_types["payrollstructure"]),
            ("delete_payrollstructure", "Can delete payroll structure", content_types["payrollstructure"]),
            # Employee Payroll Profile
            ("view_employeepayrollprofile", "Can view employee payroll profile", content_types["employeepayrollprofile"]),
            ("add_employeepayrollprofile", "Can add employee payroll profile", content_types["employeepayrollprofile"]),
            ("change_employeepayrollprofile", "Can change employee payroll profile", content_types["employeepayrollprofile"]),
            ("delete_employeepayrollprofile", "Can delete employee payroll profile", content_types["employeepayrollprofile"]),
            # Payroll Period
            ("view_payrollperiod", "Can view payroll period", content_types["payrollperiod"]),
            ("add_payrollperiod", "Can add payroll period", content_types["payrollperiod"]),
            ("change_payrollperiod", "Can change payroll period", content_types["payrollperiod"]),
            ("delete_payrollperiod", "Can delete payroll period", content_types["payrollperiod"]),
            # Payroll Run
            ("view_payrollrun", "Can view payroll run", content_types["payrollrun"]),
            ("add_payrollrun", "Can add payroll run", content_types["payrollrun"]),
            ("change_payrollrun", "Can change payroll run", content_types["payrollrun"]),
            ("delete_payrollrun", "Can delete payroll run", content_types["payrollrun"]),
            # Payroll Item
            ("view_payrollitem", "Can view payroll item", content_types["payrollitem"]),
            ("add_payrollitem", "Can add payroll item", content_types["payrollitem"]),
            ("change_payrollitem", "Can change payroll item", content_types["payrollitem"]),
            ("delete_payrollitem", "Can delete payroll item", content_types["payrollitem"]),
            # Payslip
            ("view_payslip", "Can view payslip", content_types["payslip"]),
            ("add_payslip", "Can add payslip", content_types["payslip"]),
            ("change_payslip", "Can change payslip", content_types["payslip"]),
            ("delete_payslip", "Can delete payslip", content_types["payslip"]),
            # Bonus Rule
            ("view_bonusrule", "Can view bonus rule", content_types["bonusrule"]),
            ("add_bonusrule", "Can add bonus rule", content_types["bonusrule"]),
            ("change_bonusrule", "Can change bonus rule", content_types["bonusrule"]),
            ("delete_bonusrule", "Can delete bonus rule", content_types["bonusrule"]),
            # Employee Bonus
            ("view_employeebonus", "Can view employee bonus", content_types["employeebonus"]),
            ("add_employeebonus", "Can add employee bonus", content_types["employeebonus"]),
            ("change_employeebonus", "Can change employee bonus", content_types["employeebonus"]),
            ("delete_employeebonus", "Can delete employee bonus", content_types["employeebonus"]),
            # Employee Loan
            ("view_employeeloan", "Can view employee loan", content_types["employeeloan"]),
            ("add_employeeloan", "Can add employee loan", content_types["employeeloan"]),
            ("change_employeeloan", "Can change employee loan", content_types["employeeloan"]),
            ("delete_employeeloan", "Can delete employee loan", content_types["employeeloan"]),
            # Loan Repayment
            ("view_loanrepayment", "Can view loan repayment", content_types["loanrepayment"]),
            ("add_loanrepayment", "Can add loan repayment", content_types["loanrepayment"]),
            ("change_loanrepayment", "Can change loan repayment", content_types["loanrepayment"]),
            ("delete_loanrepayment", "Can delete loan repayment", content_types["loanrepayment"]),
            # Salary Advance
            ("view_salaryadvance", "Can view salary advance", content_types["salaryadvance"]),
            ("add_salaryadvance", "Can add salary advance", content_types["salaryadvance"]),
            ("change_salaryadvance", "Can change salary advance", content_types["salaryadvance"]),
            ("delete_salaryadvance", "Can delete salary advance", content_types["salaryadvance"]),
        ]

        perms_created = 0
        for codename, name, content_type in perms_to_create:
            try:
                perm, created = Permission.objects.get_or_create(
                    codename=codename,
                    name=name,
                    content_type=content_type,
                )
                if created:
                    perms_created += 1
            except IntegrityError:
                pass

        self.stdout.write(self.style.SUCCESS(f"Created {perms_created} payroll permissions"))

        # Also add general payroll view permission
        try:
            view_perm, _ = Permission.objects.get_or_create(
                codename="view_payroll",
                name="Can view payroll",
                content_type=content_types["payrollrun"],
            )
        except IntegrityError:
            view_perm = Permission.objects.filter(codename="view_payroll", content_type=content_types["payrollrun"]).first()

        try:
            edit_perm, _ = Permission.objects.get_or_create(
                codename="edit_payroll",
                name="Can edit payroll",
                content_type=content_types["payrollrun"],
            )
        except IntegrityError:
            edit_perm = Permission.objects.filter(codename="edit_payroll", content_type=content_types["payrollrun"]).first()

        try:
            approve_perm, _ = Permission.objects.get_or_create(
                codename="approve_payroll",
                name="Can approve payroll",
                content_type=content_types["payrollrun"],
            )
        except IntegrityError:
            approve_perm = Permission.objects.filter(codename="approve_payroll", content_type=content_types["payrollrun"]).first()

        self.stdout.write(self.style.SUCCESS("Created/verified general payroll permissions: view_payroll, edit_payroll, approve_payroll"))

        # Now assign to all company admins
        companies = CompanyProfile.objects.all()
        total_assigned = 0
        for company in companies:
            owner = getattr(company, 'owner', None)
            if owner:
                all_perms = Permission.objects.filter(content_type__in=content_types.values())
                for perm in all_perms:
                    if not owner.has_perm(f"payroll.{perm.codename}"):
                        owner.user_permissions.add(perm)
                        total_assigned += 1

        self.stdout.write(self.style.SUCCESS(f"Assigned {total_assigned} permissions to company owners"))
        self.stdout.write(self.style.SUCCESS("Payroll permissions sync completed!"))
