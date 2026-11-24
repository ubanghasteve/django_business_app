from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core.ownership import get_account_for_user
from apps.core.utils import get_company_profile_for_user
from apps.hr_staff.models import Employee
from apps.smart_attendance.models import DailyAttendance, AttendanceAnalytics
from apps.accounting.models import AccountingTransaction, JournalEntry, JournalEntryLine

from .calculations import (
    calculate_gross_salary,
    calculate_pension,
    calculate_nhf,
    calculate_tax,
    calculate_net_salary,
    calculate_loan_deduction,
    calculate_salary_advance,
    apply_bonus,
)
from .models import (
    PayrollStructure,
    EmployeePayrollProfile,
    PayrollPeriod,
    PayrollRun,
    PayrollItem,
    Payslip,
    EmployeeBonus,
    EmployeeLoan,
    SalaryAdvance,
    LoanRepayment,
)


def _get_tenant_for_user(user, request=None):
    account = get_account_for_user(user)
    company = get_company_profile_for_user(user, request)
    return account, company


def sync_employee_payroll_profiles(account, company, user, default_structure: PayrollStructure | None = None):
    """
    Ensure every active HR employee under this tenant has a Payroll profile.

    - Creates EmployeePayrollProfile records for employees that don't have one.
    - Uses Employee.monthly_salary as basic_salary when available.
    - Leaves allowances at 0 by default (can be edited later).
    """
    if not account or not company:
        return

    employees = (
        Employee.objects.filter(account=account, company=company, status="active", is_deleted=False)
        .select_related("department")
    )
    existing_ids = set(
        EmployeePayrollProfile.objects.filter(account=account, company=company)
        .values_list("employee_id", flat=True)
    )

    to_create = []
    for emp in employees:
        if emp.id in existing_ids:
            continue
        basic = emp.monthly_salary or Decimal("0.00")
        to_create.append(
            EmployeePayrollProfile(
                account=account,
                company=company,
                created_by=user,
                employee=emp,
                payroll_structure=default_structure,
                basic_salary=basic,
                allowance=Decimal("0.00"),
                pension_enabled=True,
                nhf_enabled=True,
            )
        )
    if to_create:
        EmployeePayrollProfile.objects.bulk_create(to_create)


@transaction.atomic
def generate_payroll_run(user, month: int, year: int, structure: PayrollStructure = None, request=None):
    """
    High-level orchestration: create PayrollPeriod + PayrollRun and populate PayrollItem rows.
    """
    account, company = _get_tenant_for_user(user, request)
    if not account or not company:
        raise ValueError("Tenant account/company not resolved for user.")

    period, _ = PayrollPeriod.objects.get_or_create(
        company=company,
        month=month,
        year=year,
        defaults={
            "account": account,
            "created_by": user,
            "start_date": date(year, month, 1),
            "end_date": timezone.now().date(),
        },
    )
    # Ensure payroll profiles exist for all active employees before generating items
    sync_employee_payroll_profiles(account, company, user, default_structure=structure)

    payroll_run = PayrollRun.objects.create(
        account=account,
        company=company,
        created_by=user,
        period=period,
        structure=structure,
        status="processing",
    )

    profiles = EmployeePayrollProfile.objects.filter(
        account=account,
        company=company,
    ).select_related("employee", "payroll_structure")

    total_gross = Decimal("0.00")
    total_tax = Decimal("0.00")
    total_pension = Decimal("0.00")
    total_nhf = Decimal("0.00")
    total_net = Decimal("0.00")

    for profile in profiles:
        item = calculate_employee_salary(payroll_run, profile, month, year)
        total_gross += item.gross_salary
        total_tax += item.tax
        total_pension += item.pension
        total_nhf += item.nhf
        total_net += item.net_salary

    payroll_run.total_gross = total_gross
    payroll_run.total_tax = total_tax
    payroll_run.total_pension = total_pension
    payroll_run.total_nhf = total_nhf
    payroll_run.total_net = total_net
    payroll_run.status = "pending_approval"
    payroll_run.save()

    return payroll_run


def _get_attendance_summary(employee: Employee, month: int, year: int):
    """
    Map HR employee to attendance profile and compute:
    - total_work_days: count of DailyAttendance rows in month
    - absent_days: rows with STATUS_ABSENT
    - overtime_hours: derived from AttendanceAnalytics.overtime_minutes (monthly)
    """
    attendance_qs = DailyAttendance.objects.filter(
        employee__hr_employee=employee,
        date__year=year,
        date__month=month,
    )
    total_days = attendance_qs.count()
    absent_days = attendance_qs.filter(status=DailyAttendance.STATUS_ABSENT).count()

    analytics_qs = AttendanceAnalytics.objects.filter(
        employee__hr_employee=employee,
        period=AttendanceAnalytics.PERIOD_MONTHLY,
        date__year=year,
        date__month=month,
    )
    total_overtime_minutes = sum(
        (a.overtime_minutes or 0) for a in analytics_qs
    )
    overtime_hours = (
        Decimal(total_overtime_minutes) / Decimal("60") if total_overtime_minutes else Decimal("0.00")
    )
    return total_days, absent_days, overtime_hours


def calculate_employee_salary(payroll_run: PayrollRun, profile: EmployeePayrollProfile, month: int, year: int):
    """
    Derive PayrollItem for a given employee profile, including attendance, loans, bonuses, and 13th month.
    """
    employee = profile.employee
    structure = profile.payroll_structure or payroll_run.structure

    total_work_days, absent_days, overtime_hours = _get_attendance_summary(employee, month, year)

    basic_salary = profile.basic_salary
    allowances = profile.allowance

    employee_bonuses = EmployeeBonus.objects.filter(
        employee=employee,
        payroll_run=payroll_run,
    )
    bonuses = apply_bonus(basic_salary, employee_bonuses)

    # Optional: overtime conversion – here we simply treat each overtime hour as 1/173 of basic salary.
    overtime_rate = (basic_salary / Decimal("173")) if basic_salary else Decimal("0.00")
    overtime_amount = (overtime_rate * overtime_hours).quantize(Decimal("0.01")) if overtime_rate else Decimal("0.00")

    gross = calculate_gross_salary(
        basic_salary=basic_salary,
        allowances=allowances,
        bonuses=bonuses,
        overtime=overtime_amount,
    )

    if structure and structure.enable_thirteenth_salary and month == 12:
        gross += basic_salary

    pension = calculate_pension(gross) if profile.pension_enabled else Decimal("0.00")
    nhf = calculate_nhf(basic_salary) if profile.nhf_enabled else Decimal("0.00")
    tax = calculate_tax(gross, pension, nhf)

    loan = EmployeeLoan.objects.filter(employee=employee, status="active").first()
    loan_deduction = calculate_loan_deduction(loan)

    advance = SalaryAdvance.objects.filter(
        employee=employee,
        status="approved",
    ).first()
    salary_advance = calculate_salary_advance(advance)

    net = calculate_net_salary(
        gross_salary=gross,
        pension=pension,
        nhf=nhf,
        tax=tax,
        loan_deduction=loan_deduction,
        salary_advance=salary_advance,
        other_deductions=Decimal("0.00"),
    )

    item = PayrollItem.objects.create(
        account=payroll_run.account,
        company=payroll_run.company,
        created_by=payroll_run.created_by,
        payroll_run=payroll_run,
        employee=employee,
        basic_salary=basic_salary,
        allowances=allowances,
        bonuses=bonuses,
        overtime=overtime_amount,
        gross_salary=gross,
        pension=pension,
        nhf=nhf,
        tax=tax,
        loan_deduction=loan_deduction,
        salary_advance=salary_advance,
        other_deductions=Decimal("0.00"),
        net_salary=net,
        total_work_days=total_work_days,
        absent_days=absent_days,
        overtime_hours=overtime_hours,
    )

    if loan and loan_deduction > 0:
        LoanRepayment.objects.create(
            account=item.account,
            company=item.company,
            created_by=item.created_by,
            loan=loan,
            payroll_item=item,
            amount=loan_deduction,
            date=payroll_run.period.end_date,
        )
        loan.outstanding_balance = (loan.outstanding_balance or Decimal("0.00")) - loan_deduction
        if loan.outstanding_balance <= 0:
            loan.status = "paid"
            loan.outstanding_balance = Decimal("0.00")
        loan.save()

    if advance and salary_advance > 0:
        advance.status = "deducted"
        advance.payroll_item = item
        advance.save()

    return item


def apply_employee_bonuses(payroll_run: PayrollRun):
    """
    Placeholder for any bulk bonus logic – current implementation uses EmployeeBonus linked to payroll_run.
    """
    return EmployeeBonus.objects.filter(payroll_run=payroll_run)


def deduct_loans(payroll_run: PayrollRun):
    """
    Loans are handled in calculate_employee_salary; this function is kept for API symmetry.
    """
    return LoanRepayment.objects.filter(payroll_item__payroll_run=payroll_run)


def deduct_salary_advances(payroll_run: PayrollRun):
    """
    Salary advances are handled in calculate_employee_salary; this function is kept for API symmetry.
    """
    return SalaryAdvance.objects.filter(payroll_item__payroll_run=payroll_run)


def generate_payslip(payroll_item: PayrollItem, pdf_file=None, created_by=None):
    """
    Create or update Payslip for a given PayrollItem.
    The actual PDF is generated via exporters/report engine and passed in.
    """
    payslip, _ = Payslip.objects.get_or_create(
        payroll_item=payroll_item,
        defaults={
            "account": payroll_item.account,
            "company": payroll_item.company,
            "employee": payroll_item.employee,
            "period": payroll_item.payroll_run.period,
            "created_by": created_by or payroll_item.created_by,
        },
    )
    if pdf_file is not None:
        payslip.pdf_file = pdf_file
    if created_by is not None:
        payslip.created_by = created_by
    payslip.save()
    return payslip


@transaction.atomic
def post_payroll_to_accounting(payroll_run: PayrollRun, user):
    """
    Post aggregated payroll amounts to accounting as a double-entry journal:
      Salary Expense (debit), Salary Payable (credit).
    When salary is marked as paid, a separate journal should move from Salary Payable to Bank.
    """
    company = payroll_run.company
    total_net = payroll_run.total_net
    if total_net <= 0:
        return None

    txn = AccountingTransaction.objects.create(
        company=company,
        reference=f"PAYROLL-{payroll_run.id}",
        source_app="manual",
        source_id=str(payroll_run.id),
        amount=total_net,
        currency=getattr(company, "currency_code", "₦"),
    )

    journal = JournalEntry.objects.create(
        company=company,
        transaction=txn,
        reference=f"Payroll {payroll_run.period}",
        description="Payroll posting – Salary Expense to Salary Payable",
        date=payroll_run.period.end_date,
        created_by=user,
        status="posted",
    )

    # NOTE: In a production system, these ChartOfAccount instances should be configurable per tenant.
    salary_expense_account = company.chart_of_accounts.filter(code__icontains="SAL-EXP").first()
    salary_payable_account = company.chart_of_accounts.filter(code__icontains="SAL-PAY").first()
    if not salary_expense_account or not salary_payable_account:
        # Fallback: do not create lines if accounts are missing.
        return journal

    JournalEntryLine.objects.create(
        journal=journal,
        account=salary_expense_account,
        description="Salary Expense",
        debit=total_net,
        credit=Decimal("0.00"),
    )
    JournalEntryLine.objects.create(
        journal=journal,
        account=salary_payable_account,
        description="Salary Payable",
        debit=Decimal("0.00"),
        credit=total_net,
    )

    payroll_run.status = "approved"
    payroll_run.save(update_fields=["status"])
    return journal


@transaction.atomic
def mark_payroll_as_paid(payroll_run: PayrollRun, user, bank_account=None):
    """
    Mark payroll as paid and post payment journal:
      Salary Payable → Debit
      Bank → Credit
    """
    company = payroll_run.company
    total_net = payroll_run.total_net
    if total_net <= 0:
        return None

    salary_payable_account = company.chart_of_accounts.filter(code__icontains="SAL-PAY").first()
    if bank_account is None:
        bank_account = company.chart_of_accounts.filter(code__icontains="BANK").first()
    if not salary_payable_account or not bank_account:
        return None

    txn = AccountingTransaction.objects.create(
        company=company,
        reference=f"PAYROLL-PAYMENT-{payroll_run.id}",
        source_app="manual",
        source_id=str(payroll_run.id),
        amount=total_net,
        currency=getattr(company, "currency_code", "₦"),
    )

    journal = JournalEntry.objects.create(
        company=company,
        transaction=txn,
        reference=f"Payroll Payment {payroll_run.period}",
        description="Salary payment – Salary Payable to Bank",
        date=timezone.now().date(),
        created_by=user,
        status="posted",
    )

    JournalEntryLine.objects.create(
        journal=journal,
        account=salary_payable_account,
        description="Salary Payable",
        debit=total_net,
        credit=Decimal("0.00"),
    )
    JournalEntryLine.objects.create(
        journal=journal,
        account=bank_account,
        description="Bank",
        debit=Decimal("0.00"),
        credit=total_net,
    )

    payroll_run.status = "paid"
    payroll_run.save(update_fields=["status"])
    return journal

