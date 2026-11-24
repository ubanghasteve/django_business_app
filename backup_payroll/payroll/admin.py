from django.contrib import admin

from .models import (
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


@admin.register(PayrollStructure)
class PayrollStructureAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "enable_thirteenth_salary", "is_active", "created_at")
    search_fields = ("name", "company__company_name")
    list_filter = ("company", "enable_thirteenth_salary", "is_active")


@admin.register(EmployeePayrollProfile)
class EmployeePayrollProfileAdmin(admin.ModelAdmin):
    list_display = ("employee", "company", "basic_salary", "allowance", "pension_enabled", "nhf_enabled")
    search_fields = ("employee__first_name", "employee__last_name", "employee__employee_id")
    list_filter = ("company", "pension_enabled", "nhf_enabled")


@admin.register(PayrollPeriod)
class PayrollPeriodAdmin(admin.ModelAdmin):
    list_display = ("company", "month", "year", "status", "start_date", "end_date")
    list_filter = ("company", "status", "year", "month")


@admin.register(PayrollRun)
class PayrollRunAdmin(admin.ModelAdmin):
    list_display = ("id", "company", "period", "status", "total_gross", "total_net", "created_at")
    list_filter = ("company", "status", "period__year", "period__month")
    search_fields = ("id", "company__company_name")


@admin.register(PayrollItem)
class PayrollItemAdmin(admin.ModelAdmin):
    list_display = ("employee", "company", "payroll_run", "gross_salary", "tax", "net_salary")
    list_filter = ("company", "payroll_run__period__year", "payroll_run__period__month")
    search_fields = ("employee__first_name", "employee__last_name", "employee__employee_id")


@admin.register(Payslip)
class PayslipAdmin(admin.ModelAdmin):
    list_display = ("employee", "company", "period", "created_at")
    list_filter = ("company", "period__year", "period__month")
    search_fields = ("employee__first_name", "employee__last_name", "employee__employee_id")


@admin.register(BonusRule)
class BonusRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "bonus_type", "percentage_of_basic", "is_active")
    list_filter = ("company", "bonus_type", "is_active")
    search_fields = ("name",)


@admin.register(EmployeeBonus)
class EmployeeBonusAdmin(admin.ModelAdmin):
    list_display = ("employee", "company", "bonus_type", "amount", "payroll_run", "created_at")
    list_filter = ("company", "bonus_type", "payroll_run")
    search_fields = ("employee__first_name", "employee__last_name", "employee__employee_id")


@admin.register(EmployeeLoan)
class EmployeeLoanAdmin(admin.ModelAdmin):
    list_display = ("employee", "company", "principal_amount", "outstanding_balance", "monthly_repayment_amount", "status")
    list_filter = ("company", "status")
    search_fields = ("employee__first_name", "employee__last_name", "employee__employee_id")


@admin.register(LoanRepayment)
class LoanRepaymentAdmin(admin.ModelAdmin):
    list_display = ("loan", "company", "amount", "date")
    list_filter = ("company", "date")


@admin.register(SalaryAdvance)
class SalaryAdvanceAdmin(admin.ModelAdmin):
    list_display = ("employee", "company", "amount", "status", "created_at")
    list_filter = ("company", "status")
    search_fields = ("employee__first_name", "employee__last_name", "employee__employee_id")

