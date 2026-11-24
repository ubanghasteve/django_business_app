from io import BytesIO

import openpyxl

from .models import PayrollItem


def _base_workbook(title: str):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title
    return wb, ws


def export_paye(company, period, queryset=None):
    """
    Generate PAYE Excel compliant with typical Nigerian remittance formats.
    """
    qs = queryset or PayrollItem.objects.filter(
        company=company, payroll_run__period=period
    ).select_related("employee")
    wb, ws = _base_workbook("PAYE")
    ws.append(["Employee", "Employee ID", "Taxable Income", "PAYE Deducted"])
    for item in qs:
        emp = item.employee
        taxable_income = item.gross_salary  # CRA already applied inside tax calc
        ws.append(
            [
                emp.full_name,
                emp.employee_id,
                float(taxable_income),
                float(item.tax),
            ]
        )
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def export_nhf(company, period, queryset=None):
    qs = queryset or PayrollItem.objects.filter(
        company=company, payroll_run__period=period
    ).select_related("employee")
    wb, ws = _base_workbook("NHF")
    ws.append(["Employee", "Employee ID", "NHF Contribution"])
    for item in qs:
        emp = item.employee
        ws.append([emp.full_name, emp.employee_id, float(item.nhf)])
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def export_pension(company, period, queryset=None):
    qs = queryset or PayrollItem.objects.filter(
        company=company, payroll_run__period=period
    ).select_related("employee")
    wb, ws = _base_workbook("Pension")
    ws.append(["Employee", "Employee ID", "Employee Pension"])
    for item in qs:
        emp = item.employee
        ws.append([emp.full_name, emp.employee_id, float(item.pension)])
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def export_payroll_summary(company, period, queryset=None):
    qs = queryset or PayrollItem.objects.filter(
        company=company, payroll_run__period=period
    ).select_related("employee")
    wb, ws = _base_workbook("Payroll Summary")
    ws.append(
        [
            "Employee",
            "Employee ID",
            "Basic Salary",
            "Allowances",
            "Bonuses",
            "Overtime",
            "Gross Salary",
            "Pension",
            "NHF",
            "Tax",
            "Loan Deduction",
            "Salary Advance",
            "Other Deductions",
            "Net Salary",
        ]
    )
    for item in qs:
        emp = item.employee
        ws.append(
            [
                emp.full_name,
                emp.employee_id,
                float(item.basic_salary),
                float(item.allowances),
                float(item.bonuses),
                float(item.overtime),
                float(item.gross_salary),
                float(item.pension),
                float(item.nhf),
                float(item.tax),
                float(item.loan_deduction),
                float(item.salary_advance),
                float(item.other_deductions),
                float(item.net_salary),
            ]
        )
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf

