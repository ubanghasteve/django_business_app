from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.core.ownership import TenantOwnedManager
from apps.core.sync_mixin import SyncMixin


User = settings.AUTH_USER_MODEL


class PayrollStructure(SyncMixin, models.Model):
    """
    Defines payroll configuration for a company or group of employees.
    """

    account = models.ForeignKey(
        "core.Account",
        on_delete=models.CASCADE,
        related_name="payroll_structures",
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        "core.CompanyProfile",
        on_delete=models.CASCADE,
        related_name="payroll_structures",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payroll_structures_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    enable_thirteenth_salary = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    objects = TenantOwnedManager()

    class Meta:
        ordering = ["name"]
        verbose_name = "Payroll Structure"
        verbose_name_plural = "Payroll Structures"

    def __str__(self) -> str:
        return self.name


class EmployeePayrollProfile(SyncMixin, models.Model):
    """
    Per-employee payroll configuration (links HR employee to payroll structure).
    """

    account = models.ForeignKey(
        "core.Account",
        on_delete=models.CASCADE,
        related_name="employee_payroll_profiles",
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        "core.CompanyProfile",
        on_delete=models.CASCADE,
        related_name="employee_payroll_profiles",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee_payroll_profiles_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    employee = models.ForeignKey(
        "hr_staff.Employee",
        on_delete=models.CASCADE,
        related_name="payroll_profile",
    )
    payroll_structure = models.ForeignKey(
        PayrollStructure,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee_profiles",
    )
    basic_salary = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    allowance = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    pension_enabled = models.BooleanField(default=True)
    nhf_enabled = models.BooleanField(default=True)

    objects = TenantOwnedManager()

    class Meta:
        ordering = ["employee__last_name", "employee__first_name"]
        verbose_name = "Employee Payroll Profile"
        verbose_name_plural = "Employee Payroll Profiles"

    def __str__(self) -> str:
        return f"Payroll profile for {self.employee}"


class PayrollPeriod(SyncMixin, models.Model):
    """
    Monthly (or custom) payroll period.
    """

    STATUS_CHOICES = [
        ("open", "Open"),
        ("closed", "Closed"),
    ]

    account = models.ForeignKey(
        "core.Account",
        on_delete=models.CASCADE,
        related_name="payroll_periods",
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        "core.CompanyProfile",
        on_delete=models.CASCADE,
        related_name="payroll_periods",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payroll_periods_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    month = models.PositiveSmallIntegerField()
    year = models.PositiveSmallIntegerField()
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default="open"
    )

    objects = TenantOwnedManager()

    class Meta:
        unique_together = ("company", "month", "year")
        ordering = ["-year", "-month"]
        verbose_name = "Payroll Period"
        verbose_name_plural = "Payroll Periods"

    def __str__(self) -> str:
        return f"{self.month:02d}/{self.year}"


class PayrollRun(SyncMixin, models.Model):
    """
    A specific execution of payroll for a period.
    """

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("processing", "Processing"),
        ("pending_approval", "Pending Approval"),
        ("approved", "Approved"),
        ("paid", "Paid"),
    ]

    account = models.ForeignKey(
        "core.Account",
        on_delete=models.CASCADE,
        related_name="payroll_runs",
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        "core.CompanyProfile",
        on_delete=models.CASCADE,
        related_name="payroll_runs",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payroll_runs_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    period = models.ForeignKey(
        PayrollPeriod,
        on_delete=models.PROTECT,
        related_name="runs",
    )
    structure = models.ForeignKey(
        PayrollStructure,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="runs",
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="draft"
    )
    notes = models.TextField(blank=True, default="")

    total_gross = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00")
    )
    total_tax = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00")
    )
    total_pension = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00")
    )
    total_nhf = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00")
    )
    total_net = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00")
    )

    objects = TenantOwnedManager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Payroll Run"
        verbose_name_plural = "Payroll Runs"
        permissions = [
            ("view_payroll", "View payroll"),
            ("create_payroll", "Create payroll"),
            ("edit_payroll", "Edit payroll"),
            ("delete_payroll", "Delete payroll"),
            ("run_payroll", "Run payroll"),
            ("approve_payroll", "Approve payroll"),
        ]

    def __str__(self) -> str:
        return f"Payroll Run {self.id} - {self.period}"


class PayrollItem(SyncMixin, models.Model):
    """
    Per-employee entry in a payroll run.
    """

    account = models.ForeignKey(
        "core.Account",
        on_delete=models.CASCADE,
        related_name="payroll_items",
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        "core.CompanyProfile",
        on_delete=models.CASCADE,
        related_name="payroll_items",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payroll_items_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    payroll_run = models.ForeignKey(
        PayrollRun,
        on_delete=models.CASCADE,
        related_name="items",
    )
    employee = models.ForeignKey(
        "hr_staff.Employee",
        on_delete=models.PROTECT,
        related_name="payroll_items",
    )

    # Earnings
    basic_salary = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    allowances = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    bonuses = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    overtime = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    gross_salary = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )

    # Statutory deductions
    pension = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    nhf = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    tax = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )

    # Other deductions
    loan_deduction = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    salary_advance = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    other_deductions = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )

    net_salary = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )

    total_work_days = models.PositiveIntegerField(default=0)
    absent_days = models.PositiveIntegerField(default=0)
    overtime_hours = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )

    objects = TenantOwnedManager()

    class Meta:
        ordering = ["employee__last_name", "employee__first_name"]
        verbose_name = "Payroll Item"
        verbose_name_plural = "Payroll Items"

    def __str__(self) -> str:
        return f"{self.employee} – {self.payroll_run}"


class Payslip(SyncMixin, models.Model):
    """
    Generated payslip for an employee and payroll item.
    """

    account = models.ForeignKey(
        "core.Account",
        on_delete=models.CASCADE,
        related_name="payslips",
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        "core.CompanyProfile",
        on_delete=models.CASCADE,
        related_name="payslips",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payslips_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    payroll_item = models.OneToOneField(
        PayrollItem,
        on_delete=models.CASCADE,
        related_name="payslip",
    )
    employee = models.ForeignKey(
        "hr_staff.Employee",
        on_delete=models.PROTECT,
        related_name="payslips",
    )
    period = models.ForeignKey(
        PayrollPeriod,
        on_delete=models.PROTECT,
        related_name="payslips",
    )
    pdf_file = models.FileField(
        upload_to="payroll/payslips/%Y/%m/",
        blank=True,
        null=True,
    )

    objects = TenantOwnedManager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Payslip"
        verbose_name_plural = "Payslips"
        # Only custom permission; Django already provides builtin view/add/change/delete.
        permissions = [
            ("generate_payslip", "Generate payslip"),
        ]

    def __str__(self) -> str:
        return f"Payslip – {self.employee} – {self.period}"


class BonusRule(SyncMixin, models.Model):
    """
    Configurable bonus rules per tenant.
    """

    BONUS_TYPE_CHOICES = [
        ("performance", "Performance"),
        ("profit_share", "Profit Share"),
        ("holiday_bonus", "Holiday Bonus"),
        ("manual_bonus", "Manual Bonus"),
    ]

    account = models.ForeignKey(
        "core.Account",
        on_delete=models.CASCADE,
        related_name="payroll_bonus_rules",
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        "core.CompanyProfile",
        on_delete=models.CASCADE,
        related_name="payroll_bonus_rules",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payroll_bonus_rules_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    name = models.CharField(max_length=255)
    bonus_type = models.CharField(max_length=20, choices=BONUS_TYPE_CHOICES)
    percentage_of_basic = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00")
    )
    is_active = models.BooleanField(default=True)

    objects = TenantOwnedManager()

    class Meta:
        ordering = ["name"]
        verbose_name = "Bonus Rule"
        verbose_name_plural = "Bonus Rules"

    def __str__(self) -> str:
        return self.name


class EmployeeBonus(SyncMixin, models.Model):
    """
    Actual bonus instances applied to employees (can be manual or from rules).
    """

    account = models.ForeignKey(
        "core.Account",
        on_delete=models.CASCADE,
        related_name="employee_bonuses",
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        "core.CompanyProfile",
        on_delete=models.CASCADE,
        related_name="employee_bonuses",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee_bonuses_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    employee = models.ForeignKey(
        "hr_staff.Employee",
        on_delete=models.CASCADE,
        related_name="bonuses",
    )
    rule = models.ForeignKey(
        BonusRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee_bonuses",
    )
    payroll_run = models.ForeignKey(
        PayrollRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee_bonuses",
    )
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    bonus_type = models.CharField(
        max_length=20,
        choices=BonusRule.BONUS_TYPE_CHOICES,
        default="manual_bonus",
    )

    objects = TenantOwnedManager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Employee Bonus"
        verbose_name_plural = "Employee Bonuses"

    def __str__(self) -> str:
        return f"{self.employee} – {self.amount}"


class EmployeeLoan(SyncMixin, models.Model):
    """
    Employee loan definition – balances are deducted via payroll.
    """

    STATUS_CHOICES = [
        ("active", "Active"),
        ("paid", "Paid"),
        ("defaulted", "Defaulted"),
    ]

    account = models.ForeignKey(
        "core.Account",
        on_delete=models.CASCADE,
        related_name="employee_loans",
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        "core.CompanyProfile",
        on_delete=models.CASCADE,
        related_name="employee_loans",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee_loans_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    employee = models.ForeignKey(
        "hr_staff.Employee",
        on_delete=models.CASCADE,
        related_name="loans",
    )
    principal_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    outstanding_balance = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    monthly_repayment_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    start_date = models.DateField()
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="active"
    )

    objects = TenantOwnedManager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Employee Loan"
        verbose_name_plural = "Employee Loans"

    def __str__(self) -> str:
        return f"{self.employee} – {self.principal_amount}"


class LoanRepayment(SyncMixin, models.Model):
    """
    Individual loan repayment (usually generated from payroll).
    """

    account = models.ForeignKey(
        "core.Account",
        on_delete=models.CASCADE,
        related_name="loan_repayments",
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        "core.CompanyProfile",
        on_delete=models.CASCADE,
        related_name="loan_repayments",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="loan_repayments_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    loan = models.ForeignKey(
        EmployeeLoan,
        on_delete=models.CASCADE,
        related_name="repayments",
    )
    payroll_item = models.ForeignKey(
        PayrollItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="loan_repayments",
    )
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    date = models.DateField()

    objects = TenantOwnedManager()

    class Meta:
        ordering = ["-date"]
        verbose_name = "Loan Repayment"
        verbose_name_plural = "Loan Repayments"

    def __str__(self) -> str:
        return f"{self.loan} – {self.amount} on {self.date}"


class SalaryAdvance(SyncMixin, models.Model):
    """
    Salary advance requests which are later deducted via payroll.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("deducted", "Deducted"),
    ]

    account = models.ForeignKey(
        "core.Account",
        on_delete=models.CASCADE,
        related_name="salary_advances",
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        "core.CompanyProfile",
        on_delete=models.CASCADE,
        related_name="salary_advances",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="salary_advances_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    employee = models.ForeignKey(
        "hr_staff.Employee",
        on_delete=models.CASCADE,
        related_name="salary_advances",
    )
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="pending"
    )
    payroll_item = models.ForeignKey(
        PayrollItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="salary_advances",
    )

    objects = TenantOwnedManager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Salary Advance"
        verbose_name_plural = "Salary Advances"

    def __str__(self) -> str:
        return f"{self.employee} – {self.amount} ({self.status})"


class FileCategory(SyncMixin, models.Model):
    """
    Categories for organizing payroll files (e.g., Payslips, Reports, Contracts, etc.)
    """

    CATEGORY_CHOICES = [
        ("payslip", "Payslips"),
        ("report", "Reports"),
        ("contract", "Contracts"),
        ("tax_document", "Tax Documents"),
        ("bank_details", "Bank Details"),
        ("pension", "Pension Documents"),
        ("nhf", "NHF Documents"),
        ("loan_document", "Loan Documents"),
        ("bonus", "Bonus Documents"),
        ("advance", "Advance Documents"),
        ("other", "Other"),
    ]

    account = models.ForeignKey(
        "core.Account",
        on_delete=models.CASCADE,
        related_name="payroll_file_categories",
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        "core.CompanyProfile",
        on_delete=models.CASCADE,
        related_name="payroll_file_categories",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payroll_file_categories_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    name = models.CharField(max_length=100)
    category_type = models.CharField(
        max_length=20, choices=CATEGORY_CHOICES, default="other", unique=True
    )
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    color = models.CharField(max_length=7, default="#1e88e5")

    objects = TenantOwnedManager()

    class Meta:
        ordering = ["name"]
        verbose_name = "File Category"
        verbose_name_plural = "File Categories"

    def __str__(self) -> str:
        return self.name


class PayrollFile(SyncMixin, models.Model):
    """
    Stores uploaded payroll files with smart organization and categorization.
    Supports any file type: images, Excel, PDF, documents, etc.
    """

    FILE_TYPE_CHOICES = [
        ("pdf", "PDF"),
        ("excel", "Excel"),
        ("image", "Image"),
        ("word", "Word Document"),
        ("csv", "CSV"),
        ("text", "Text"),
        ("zip", "ZIP Archive"),
        ("other", "Other"),
    ]

    account = models.ForeignKey(
        "core.Account",
        on_delete=models.CASCADE,
        related_name="payroll_files",
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        "core.CompanyProfile",
        on_delete=models.CASCADE,
        related_name="payroll_files",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payroll_files_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    file = models.FileField(
        upload_to="payroll/files/%Y/%m/",
        max_length=500,
    )
    original_filename = models.CharField(max_length=255)
    file_type = models.CharField(
        max_length=10, choices=FILE_TYPE_CHOICES, default="other"
    )
    mime_type = models.CharField(max_length=100, blank=True, default="")
    file_size = models.BigIntegerField(default=0)

    title = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")

    category = models.ForeignKey(
        FileCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="files",
    )

    employee = models.ForeignKey(
        "hr_staff.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payroll_files",
    )
    payroll_period = models.ForeignKey(
        PayrollPeriod,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="files",
    )
    payroll_run = models.ForeignKey(
        PayrollRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="files",
    )

    month = models.PositiveSmallIntegerField(null=True, blank=True)
    year = models.PositiveSmallIntegerField(null=True, blank=True)

    tags = models.CharField(max_length=500, blank=True, default="")

    is_starred = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    is_public = models.BooleanField(default=False)

    view_count = models.PositiveIntegerField(default=0)
    download_count = models.PositiveIntegerField(default=0)

    objects = TenantOwnedManager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Payroll File"
        verbose_name_plural = "Payroll Files"
        permissions = [
            ("upload_payroll_file", "Upload payroll files"),
            ("delete_payroll_file", "Delete payroll files"),
            ("manage_payroll_files", "Manage all payroll files"),
        ]

    def __str__(self) -> str:
        return self.title or self.original_filename

    @property
    def file_extension(self) -> str:
        import os
        name = self.original_filename or self.file.name
        ext = os.path.splitext(name)[1]
        return ext.lower().replace(".", "")

    @property
    def file_size_display(self) -> str:
        size = self.file_size
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        return f"{size / (1024 * 1024 * 1024):.1f} GB"

    @property
    def period_display(self) -> str:
        if self.month and self.year:
            from datetime import date
            try:
                d = date(self.year, self.month, 1)
                return d.strftime("%B %Y")
            except:
                pass
        if self.payroll_period:
            return str(self.payroll_period)
        return "N/A"


class FileAccessLog(SyncMixin, models.Model):
    """
    Tracks access history for payroll files.
    """

    ACTION_CHOICES = [
        ("view", "View"),
        ("download", "Download"),
        ("share", "Share"),
        ("delete", "Delete"),
    ]

    account = models.ForeignKey(
        "core.Account",
        on_delete=models.CASCADE,
        related_name="file_access_logs",
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        "core.CompanyProfile",
        on_delete=models.CASCADE,
        related_name="file_access_logs",
        null=True,
        blank=True,
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="file_access_logs",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    file = models.ForeignKey(
        PayrollFile,
        on_delete=models.CASCADE,
        related_name="access_logs",
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True, default="")

    objects = TenantOwnedManager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "File Access Log"
        verbose_name_plural = "File Access Logs"

    def __str__(self) -> str:
        return f"{self.user} - {self.action} - {self.file}"


class ExcelData(SyncMixin, models.Model):
    """
    Stores extracted data from Excel files with multiple sheets.
    Each Excel upload can have multiple sheets, and each sheet contains rows of data.
    """

    account = models.ForeignKey(
        "core.Account",
        on_delete=models.CASCADE,
        related_name="excel_datas",
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        "core.CompanyProfile",
        on_delete=models.CASCADE,
        related_name="excel_datas",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="excel_datas_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    payroll_file = models.ForeignKey(
        PayrollFile,
        on_delete=models.CASCADE,
        related_name="excel_data",
        null=True,
        blank=True,
    )
    sheet_name = models.CharField(max_length=255)
    sheet_index = models.PositiveSmallIntegerField(default=0)
    
    employee = models.ForeignKey(
        "hr_staff.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="excel_datas",
    )
    
    period_month = models.PositiveSmallIntegerField(null=True, blank=True)
    period_year = models.PositiveSmallIntegerField(null=True, blank=True)
    
    data = models.JSONField(default=dict, help_text="Row data as JSON")
    headers = models.JSONField(default=list, help_text="Column headers")
    
    row_number = models.PositiveIntegerField(default=0)
    is_processed = models.BooleanField(default=False)
    notes = models.TextField(blank=True, default="")

    objects = TenantOwnedManager()

    class Meta:
        ordering = ["-created_at", "sheet_index", "row_number"]
        verbose_name = "Excel Data"
        verbose_name_plural = "Excel Data"
        indexes = [
            models.Index(fields=["payroll_file", "sheet_name"]),
            models.Index(fields=["period_year", "period_month"]),
            models.Index(fields=["employee", "period_year", "period_month"]),
        ]

    def __str__(self) -> str:
        return f"{self.sheet_name} - Row {self.row_number}"

    @property
    def period_display(self) -> str:
        if self.period_month and self.period_year:
            from datetime import date
            try:
                d = date(self.period_year, self.period_month, 1)
                return d.strftime("%B %Y")
            except:
                pass
        return "N/A"


class ExtractedPayrollRecord(SyncMixin, models.Model):
    """
    Stores structured payroll data extracted from Excel files.
    This allows the system to parse and store payroll data for each employee.
    """

    account = models.ForeignKey(
        "core.Account",
        on_delete=models.CASCADE,
        related_name="extracted_payroll_records",
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        "core.CompanyProfile",
        on_delete=models.CASCADE,
        related_name="extracted_payroll_records",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="extracted_payroll_records_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    excel_data = models.ForeignKey(
        ExcelData,
        on_delete=models.CASCADE,
        related_name="payroll_records",
        null=True,
        blank=True,
    )
    payroll_file = models.ForeignKey(
        PayrollFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="extracted_records",
    )
    
    employee = models.ForeignKey(
        "hr_staff.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="extracted_payroll_records",
    )
    employee_name = models.CharField(max_length=255, blank=True, default="")
    employee_identifier = models.CharField(max_length=100, blank=True, default="", help_text="Employee ID from source file")
    
    period_month = models.PositiveSmallIntegerField(null=True, blank=True)
    period_year = models.PositiveSmallIntegerField(null=True, blank=True)
    
    basic_salary = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    allowances = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    bonuses = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    overtime = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    gross_salary = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    
    pension = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    nhf = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    tax = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    
    loan_deduction = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    other_deductions = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    net_salary = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    
    raw_data = models.JSONField(default=dict, help_text="Raw extracted data")
    is_linked_to_employee = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    notes = models.TextField(blank=True, default="")

    objects = TenantOwnedManager()

    class Meta:
        ordering = ["-period_year", "-period_month", "employee_name"]
        verbose_name = "Extracted Payroll Record"
        verbose_name_plural = "Extracted Payroll Records"
        indexes = [
            models.Index(fields=["period_year", "period_month"]),
            models.Index(fields=["employee", "period_year", "period_month"]),
        ]

    def __str__(self) -> str:
        return f"{self.employee_name} - {self.period_display}"

    @property
    def period_display(self) -> str:
        if self.period_month and self.period_year:
            from datetime import date
            try:
                d = date(self.period_year, self.period_month, 1)
                return d.strftime("%B %Y")
            except:
                pass
        return f"{self.period_month}/{self.period_year}" if self.period_month else "N/A"


class PayrollTemplate(SyncMixin, models.Model):
    """
    Stores detected payroll template structures from Excel files.
    The system learns from uploaded files to create dynamic forms.
    """

    FIELD_TYPES = [
        ("text", "Text"),
        ("number", "Number"),
        ("decimal", "Decimal/Amount"),
        ("integer", "Integer"),
        ("date", "Date"),
        ("select", "Dropdown"),
        ("boolean", "Yes/No"),
    ]

    CATEGORY_CHOICES = [
        ("employee_info", "Employee Information"),
        ("earnings", "Earnings"),
        ("deductions", "Deductions"),
        ("net_pay", "Net Pay"),
        ("custom", "Custom"),
    ]

    account = models.ForeignKey(
        "core.Account",
        on_delete=models.CASCADE,
        related_name="payroll_templates",
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        "core.CompanyProfile",
        on_delete=models.CASCADE,
        related_name="payroll_templates",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payroll_templates_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    
    columns = models.JSONField(default=list, help_text="Detected columns configuration")
    column_order = models.JSONField(default=list, help_text="Order of columns")
    sample_data = models.JSONField(default=list, help_text="Sample data rows")
    
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    usage_count = models.PositiveIntegerField(default=0)
    
    min_rows = models.PositiveIntegerField(default=0)
    max_rows = models.PositiveIntegerField(default=0)
    
    detected_from_file = models.ForeignKey(
        PayrollFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="detected_templates",
    )

    objects = TenantOwnedManager()

    class Meta:
        ordering = ["-usage_count", "-created_at"]
        verbose_name = "Payroll Template"
        verbose_name_plural = "Payroll Templates"
        permissions = [
            ("use_payroll_template", "Use payroll template"),
            ("manage_payroll_template", "Manage payroll templates"),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def column_count(self) -> int:
        return len(self.columns)


class PayrollEntry(SyncMixin, models.Model):
    """
    Stores payroll entries created from templates.
    Users can fill in data online or continue from existing records.
    """

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
        ("submitted", "Submitted"),
        ("approved", "Approved"),
    ]

    account = models.ForeignKey(
        "core.Account",
        on_delete=models.CASCADE,
        related_name="payroll_entries",
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        "core.CompanyProfile",
        on_delete=models.CASCADE,
        related_name="payroll_entries",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payroll_entries_created",
    )
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payroll_entries_updated",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    template = models.ForeignKey(
        PayrollTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entries",
    )
    source_file = models.ForeignKey(
        PayrollFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payroll_entries",
    )
    
    period_month = models.PositiveSmallIntegerField(null=True, blank=True)
    period_year = models.PositiveSmallIntegerField(null=True, blank=True)
    
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    
    data = models.JSONField(default=dict, help_text="Entry data as JSON")
    row_count = models.PositiveIntegerField(default=0)
    
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="draft"
    )
    notes = models.TextField(blank=True, default="")

    objects = TenantOwnedManager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Payroll Entry"
        verbose_name_plural = "Payroll Entries"
        indexes = [
            models.Index(fields=["period_year", "period_month"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"{self.title} - {self.period_display}"

    @property
    def period_display(self) -> str:
        if self.period_month and self.period_year:
            from datetime import date
            try:
                d = date(self.period_year, self.period_month, 1)
                return d.strftime("%B %Y")
            except:
                pass
        return f"{self.period_year}" if self.period_year else "N/A"

