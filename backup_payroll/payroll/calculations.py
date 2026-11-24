from decimal import Decimal

from .models import PayrollItem, PayrollStructure


def _to_decimal(value, default="0.00"):
    try:
        return Decimal(value or default)
    except Exception:
        return Decimal(default)


def calculate_gross_salary(
    basic_salary,
    allowances=Decimal("0.00"),
    bonuses=Decimal("0.00"),
    overtime=Decimal("0.00"),
):
    basic = _to_decimal(basic_salary)
    allow = _to_decimal(allowances)
    bonus = _to_decimal(bonuses)
    ot = _to_decimal(overtime)
    return basic + allow + bonus + ot


def calculate_pension(gross_salary):
    """
    Employee pension 8% of gross.
    """
    gross = _to_decimal(gross_salary)
    return (gross * Decimal("0.08")).quantize(Decimal("0.01"))


def calculate_nhf(basic_salary):
    """
    NHF is 2.5% of basic salary.
    """
    basic = _to_decimal(basic_salary)
    return (basic * Decimal("0.025")).quantize(Decimal("0.01"))


def _compute_cra(gross_income):
    """
    Consolidated Relief Allowance:
    Higher of 200000 or 1% of gross income, plus 20% of gross income.
    """
    gross = _to_decimal(gross_income)
    one_percent = gross * Decimal("0.01")
    base = max(Decimal("200000"), one_percent)
    return (base + (gross * Decimal("0.20"))).quantize(Decimal("0.01"))


def _apply_nigeria_paye_brackets(taxable_income):
    """
    Nigerian PAYE progressive tax brackets.
    """
    ti = _to_decimal(taxable_income)
    if ti <= 0:
        return Decimal("0.00")

    tax = Decimal("0.00")
    remaining = ti

    brackets = [
        (Decimal("300000"), Decimal("0.07")),
        (Decimal("300000"), Decimal("0.11")),
        (Decimal("500000"), Decimal("0.15")),
        (Decimal("500000"), Decimal("0.19")),
        (Decimal("1600000"), Decimal("0.21")),
    ]

    for limit, rate in brackets:
        if remaining <= 0:
            break
        chunk = min(remaining, limit)
        tax += chunk * rate
        remaining -= chunk

    if remaining > 0:
        tax += remaining * Decimal("0.24")

    return tax.quantize(Decimal("0.01"))


def calculate_tax(gross_salary, pension, nhf):
    """
    Taxable income = gross - CRA - pension - nhf.
    """
    gross = _to_decimal(gross_salary)
    pen = _to_decimal(pension)
    nhf_val = _to_decimal(nhf)
    cra = _compute_cra(gross)
    taxable = gross - cra - pen - nhf_val
    if taxable <= 0:
        return Decimal("0.00")
    return _apply_nigeria_paye_brackets(taxable)


def calculate_loan_deduction(loan):
    if not loan or loan.status != "active":
        return Decimal("0.00")
    return _to_decimal(loan.monthly_repayment_amount)


def calculate_salary_advance(advance):
    if not advance or advance.status != "approved":
        return Decimal("0.00")
    return _to_decimal(advance.amount)


def apply_bonus(basic_salary, employee_bonuses):
    """
    Sum explicit EmployeeBonus amounts; rules are resolved at service layer.
    """
    total = Decimal("0.00")
    for bonus in employee_bonuses:
        total += _to_decimal(bonus.amount)
    return total


def apply_13th_month_salary(gross_salary, structure: PayrollStructure, month: int):
    """
    If structure.enable_thirteenth_salary and month == 12, add extra basic salary.
    At calculation time we pass the extra amount (basic) from the service layer,
    so here we simply return the gross_salary unchanged (placeholder hook).
    """
    # This function kept simple; actual extra basic is added in services.calculate_employee_salary.
    return _to_decimal(gross_salary)


def calculate_net_salary(
    gross_salary,
    pension,
    nhf,
    tax,
    loan_deduction,
    salary_advance,
    other_deductions=Decimal("0.00"),
):
    gross = _to_decimal(gross_salary)
    pen = _to_decimal(pension)
    nhf_val = _to_decimal(nhf)
    tax_val = _to_decimal(tax)
    loan_val = _to_decimal(loan_deduction)
    adv_val = _to_decimal(salary_advance)
    other = _to_decimal(other_deductions)
    net = gross - pen - nhf_val - tax_val - loan_val - adv_val - other
    return net.quantize(Decimal("0.01"))


def recalculate_payroll_item(item: PayrollItem):
    """
    Utility used by services to recalc a PayrollItem instance in-place.
    """
    pension = calculate_pension(item.gross_salary)
    nhf = calculate_nhf(item.basic_salary)
    tax = calculate_tax(item.gross_salary, pension, nhf)
    item.pension = pension
    item.nhf = nhf
    item.tax = tax
    item.net_salary = calculate_net_salary(
        item.gross_salary,
        pension,
        nhf,
        tax,
        item.loan_deduction,
        item.salary_advance,
        item.other_deductions,
    )
    return item

