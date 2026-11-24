from django.db import models
from django.contrib.auth import get_user_model
from django.db.models import Sum, Q
from django.utils import timezone
from decimal import Decimal
import uuid

User = get_user_model()


class Transaction(models.Model):
    """Main transaction model for all financial entries"""
    TRANSACTION_TYPE = [
        ('income', 'Income'),
        ('expense', 'Expense'),
    ]
    
    SOURCE_APP_CHOICES = [
        ('manual', 'Manual Entry'),
        ('invoice', 'Invoice'),
        ('receipt', 'Receipt'),
        ('job_order', 'Job Order'),
        ('waybill', 'Waybill'),
        ('inventory', 'Inventory'),
        ('expense', 'Expense Tracker'),
    ]
    
    DISCOUNT_TYPE_CHOICES = [
        ('percentage', 'Percentage (%)'),
        ('fixed', 'Fixed Amount'),
    ]
    
    TAX_TYPE_CHOICES = [
        ('percentage', 'Percentage (%)'),
        ('fixed', 'Fixed Amount'),
    ]
    
    # Core fields
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='accounting_transactions')
    company = models.ForeignKey('core.CompanyProfile', on_delete=models.CASCADE, related_name='transactions')
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='accounting_transactions_created',
        help_text='User who created this transaction; set from user on save if missing.',
    )
    
    # Transaction details
    type = models.CharField(max_length=10, choices=TRANSACTION_TYPE)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    amount = models.DecimalField(max_digits=64, decimal_places=2)
    currency = models.CharField(max_length=10, default="₦")
    
    # Financial details with flexible types
    tax = models.DecimalField(max_digits=64, decimal_places=2, null=True, blank=True, default=0)
    tax_type = models.CharField(max_length=15, choices=TAX_TYPE_CHOICES, default='fixed', help_text="Tax calculation type")
    tax_value = models.DecimalField(max_digits=64, decimal_places=2, null=True, blank=True, default=0, help_text="Tax rate (%) or fixed amount")
    discount = models.DecimalField(max_digits=64, decimal_places=2, null=True, blank=True, default=0)
    discount_type = models.CharField(max_length=15, choices=DISCOUNT_TYPE_CHOICES, default='fixed', help_text="Discount calculation type")
    discount_value = models.DecimalField(max_digits=64, decimal_places=2, null=True, blank=True, default=0, help_text="Discount rate (%) or fixed amount")
    net_amount = models.DecimalField(max_digits=64, decimal_places=2, default=0)
    
    # Source tracking
    source_app = models.CharField(max_length=20, choices=SOURCE_APP_CHOICES, default='manual')
    reference_id = models.CharField(max_length=100, blank=True, null=True)
    reference_model = models.CharField(max_length=50, blank=True, null=True)
    
    # Metadata
    transaction_date = models.DateField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True, null=True)
    
    # Status
    is_reconciled = models.BooleanField(default=False)
    is_void = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-transaction_date', '-created_at']
        indexes = [
            models.Index(fields=['user', 'type']),
            models.Index(fields=['company', 'transaction_date']),
            models.Index(fields=['source_app', 'reference_id']),
            models.Index(fields=['type', 'transaction_date']),
        ]
    
    def __str__(self):
        return f"{self.title} ({self.type}) - {self.amount} {self.currency}"
    
    def save(self, *args, **kwargs):
        if self.user_id and not self.created_by_id:
            self.created_by_id = self.user_id
        # Calculate tax based on type
        if self.tax_value:
            if self.tax_type == 'percentage':
                self.tax = self.amount * (self.tax_value / 100)
            else:  # fixed
                self.tax = self.tax_value
        
        # Calculate discount based on type
        if self.discount_value:
            if self.discount_type == 'percentage':
                self.discount = self.amount * (self.discount_value / 100)
            else:  # fixed
                self.discount = self.discount_value
        
        # Calculate net amount
        self.net_amount = self.amount
        if self.tax:
            self.net_amount += self.tax
        if self.discount:
            self.net_amount -= self.discount
        
        super().save(*args, **kwargs)
        
        # Update ledger
        self.update_ledger()
    
    def update_ledger(self):
        """Update the ledger for this transaction's month/year"""
        if not self.is_void:
            ledger, created = Ledger.objects.get_or_create(
                company=self.company,
                year=self.transaction_date.year,
                month=self.transaction_date.month,
                defaults={
                    'total_income': 0,
                    'total_expense': 0,
                    'net_profit': 0
                }
            )
            
            # Recalculate totals for this month
            transactions = Transaction.objects.filter(
                company=self.company,
                transaction_date__year=self.transaction_date.year,
                transaction_date__month=self.transaction_date.month,
                is_void=False
            )
            
            ledger.total_income = transactions.filter(type='income').aggregate(
                total=Sum('net_amount')
            )['total'] or 0
            
            ledger.total_expense = transactions.filter(type='expense').aggregate(
                total=Sum('net_amount')
            )['total'] or 0
            
            ledger.net_profit = ledger.total_income - ledger.total_expense
            ledger.save()


class Ledger(models.Model):
    """Monthly ledger summary for financial reporting"""
    company = models.ForeignKey('core.CompanyProfile', on_delete=models.CASCADE, related_name='ledgers')
    year = models.IntegerField()
    month = models.IntegerField()
    
    # Financial totals
    total_income = models.DecimalField(max_digits=64, decimal_places=2, default=0)
    total_expense = models.DecimalField(max_digits=64, decimal_places=2, default=0)
    net_profit = models.DecimalField(max_digits=64, decimal_places=2, default=0)
    
    # Additional metrics
    outstanding_invoices = models.DecimalField(max_digits=64, decimal_places=2, default=0)
    pending_receipts = models.DecimalField(max_digits=64, decimal_places=2, default=0)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['company', 'year', 'month']
        ordering = ['-year', '-month']
        indexes = [
            models.Index(fields=['company', 'year', 'month']),
        ]
    
    def __str__(self):
        return f"{self.company.company_name} - {self.year}/{self.month:02d}"
    
    @property
    def month_name(self):
        """Get month name"""
        from datetime import datetime
        return datetime(self.year, self.month, 1).strftime('%B')
    
    def update_outstanding_amounts(self):
        """Update outstanding invoices and pending receipts"""
        from apps.invoices.models import Invoice
        from apps.receipts.models import Receipt
        
        # Outstanding invoices
        outstanding = Invoice.objects.filter(
            user=self.company.user,
            status__in=['unpaid', 'partial']
        ).aggregate(total=Sum('balance_due'))['total'] or 0
        self.outstanding_invoices = outstanding
        
        # Pending receipts (if any logic needed)
        self.pending_receipts = 0
        
        self.save()


class Account(models.Model):
    """Chart of accounts for better financial organization"""
    ACCOUNT_TYPE_CHOICES = [
        ('asset', 'Asset'),
        ('liability', 'Liability'),
        ('equity', 'Equity'),
        ('revenue', 'Revenue'),
        ('expense', 'Expense'),
    ]
    
    company = models.ForeignKey('core.CompanyProfile', on_delete=models.CASCADE, related_name='accounts')
    name = models.CharField(max_length=255)
    account_number = models.CharField(max_length=20, unique=True)
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    
    # Balance tracking
    opening_balance = models.DecimalField(max_digits=64, decimal_places=2, default=0)
    current_balance = models.DecimalField(max_digits=64, decimal_places=2, default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['account_number']
        indexes = [
            models.Index(fields=['company', 'account_type']),
            models.Index(fields=['account_number']),
        ]
    
    def __str__(self):
        return f"{self.account_number} - {self.name}"
    
    def update_balance(self):
        """Update current balance based on transactions"""
        transactions = Transaction.objects.filter(
            company=self.company,
            is_void=False
        )
        
        # This is a simplified balance calculation
        # In a real system, you'd have proper double-entry bookkeeping
        self.current_balance = self.opening_balance
        self.save()


class FinancialReport(models.Model):
    """Generated financial reports"""
    REPORT_TYPE_CHOICES = [
        ('income_statement', 'Income Statement'),
        ('balance_sheet', 'Balance Sheet'),
        ('cash_flow', 'Cash Flow Statement'),
        ('trial_balance', 'Trial Balance'),
        ('custom', 'Custom Report'),
    ]
    
    company = models.ForeignKey('core.CompanyProfile', on_delete=models.CASCADE, related_name='financial_reports')
    report_type = models.CharField(max_length=20, choices=REPORT_TYPE_CHOICES)
    title = models.CharField(max_length=255)
    
    # Date range
    start_date = models.DateField()
    end_date = models.DateField()
    
    # Report data (stored as JSON)
    report_data = models.JSONField(default=dict)
    
    # File attachments
    pdf_file = models.FileField(upload_to='reports/pdf/', blank=True, null=True)
    excel_file = models.FileField(upload_to='reports/excel/', blank=True, null=True)
    
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='generated_reports')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['company', 'report_type']),
            models.Index(fields=['start_date', 'end_date']),
        ]
    
    def __str__(self):
        return f"{self.title} - {self.start_date} to {self.end_date}"


# ======================================================================
# DOUBLE-ENTRY ACCOUNTING CORE (NON-BREAKING EXTENSION)
# These models implement a proper journal / ledger engine while
# preserving the existing Transaction/Ledger/Account models.
# ======================================================================


class AccountCategory(models.Model):
    """
    High-level grouping for accounts (Assets, Liabilities, Equity, Income, Expenses).
    This is a shared taxonomy per tenant (company/account).
    """
    CATEGORY_CHOICES = [
        ('asset', 'Asset'),
        ('liability', 'Liability'),
        ('equity', 'Equity'),
        ('income', 'Income'),
        ('expense', 'Expense'),
    ]

    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='account_categories',
    )
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=100)
    category_type = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('company', 'code')
        ordering = ['category_type', 'code']
        indexes = [
            models.Index(fields=['company', 'category_type']),
        ]

    def __str__(self):
        return f'{self.code} - {self.name}'


class AccountType(models.Model):
    """
    Finer-grained classification under a category, e.g. "Current Asset", "Bank",
    "Accounts Receivable". Used as a metadata layer for ChartOfAccount.
    """
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='account_types',
    )
    name = models.CharField(max_length=100)
    category = models.ForeignKey(
        AccountCategory,
        on_delete=models.PROTECT,
        related_name='account_types',
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('company', 'name')
        ordering = ['category__category_type', 'name']
        indexes = [
            models.Index(fields=['company', 'name']),
        ]

    def __str__(self):
        return f'{self.name} ({self.category.get_category_type_display()})'


class ChartOfAccount(models.Model):
    """
    Tenant-scoped chart of accounts.
    This complements (and can be bridged with) the existing Account model
    but is designed explicitly for double-entry posting.
    """
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='chart_of_accounts',
    )
    code = models.CharField(max_length=50)
    name = models.CharField(max_length=255)
    category = models.ForeignKey(
        AccountCategory,
        on_delete=models.PROTECT,
        related_name='chart_accounts',
    )
    account_type = models.ForeignKey(
        AccountType,
        on_delete=models.PROTECT,
        related_name='chart_accounts',
        null=True,
        blank=True,
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='children',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('company', 'code')
        ordering = ['code']
        indexes = [
            models.Index(fields=['company', 'code']),
            models.Index(fields=['company', 'category']),
        ]

    def __str__(self):
        return f'{self.code} - {self.name}'


class FiscalPeriod(models.Model):
    """
    Fiscal period/year definition per tenant.
    Used to scope journal posting windows and reporting.
    """
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='fiscal_periods',
    )
    name = models.CharField(max_length=100)  # e.g. "FY 2026", "Q1 2026"
    start_date = models.DateField()
    end_date = models.DateField()
    is_closed = models.BooleanField(default=False)

    class Meta:
        ordering = ['-start_date']
        indexes = [
            models.Index(fields=['company', 'start_date', 'end_date']),
        ]

    def __str__(self):
        return f'{self.name} ({self.start_date} - {self.end_date})'


class Currency(models.Model):
    """
    Supported currencies for a tenant. This complements CompanyProfile.currency_code/symbol
    but gives the accounting engine an explicit model for FX-enable scenarios.
    """
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='currencies',
    )
    code = models.CharField(max_length=3)  # ISO code, e.g. "NGN"
    symbol = models.CharField(max_length=5, default='₦')
    name = models.CharField(max_length=50, blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('company', 'code')
        ordering = ['code']
        indexes = [
            models.Index(fields=['company', 'code']),
        ]

    def __str__(self):
        return f'{self.code} ({self.symbol})'


class AccountingTransaction(models.Model):
    """
    Cross-app accounting transaction header.
    Each business event (Invoice paid, Expense recorded, etc.) maps to one
    AccountingTransaction, which then produces one or more JournalEntry records.
    """
    SOURCE_APP_CHOICES = Transaction.SOURCE_APP_CHOICES

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='accounting_transactions_core',
    )
    reference = models.CharField(max_length=100, help_text='Human-readable reference (e.g. INV-0001)')
    source_app = models.CharField(max_length=20, choices=SOURCE_APP_CHOICES, default='manual')
    source_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text='Primary key or unique identifier in the source app',
    )
    amount = models.DecimalField(max_digits=64, decimal_places=2)
    currency = models.CharField(max_length=10, default='₦')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['company', 'source_app', 'source_id']),
            models.Index(fields=['company', 'created_at']),
        ]

    def __str__(self):
        return f'{self.reference} - {self.amount} {self.currency}'


class JournalEntry(models.Model):
    """
    Journal entry header for double-entry postings.
    Each AccountingTransaction may produce one or more JournalEntry records
    (for example, accrual vs payment).
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('void', 'Void'),
    ]

    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='accounting_journal_entries',
    )
    transaction = models.ForeignKey(
        AccountingTransaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='journal_entries',
    )
    reference = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    date = models.DateField(default=timezone.now)
    period = models.ForeignKey(
        FiscalPeriod,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='journal_entries',
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='journal_entries_created',
    )
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='journal_entries_approved',
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-created_at']
        indexes = [
            models.Index(fields=['company', 'date']),
            models.Index(fields=['company', 'status']),
        ]

    def __str__(self):
        return self.reference or f'JE-{self.pk}'

    @property
    def total_debit(self):
        return self.lines.aggregate(total=Sum('debit'))['total'] or Decimal('0')

    @property
    def total_credit(self):
        return self.lines.aggregate(total=Sum('credit'))['total'] or Decimal('0')

    @property
    def is_balanced(self):
        return self.total_debit == self.total_credit


class JournalEntryLine(models.Model):
    """
    Individual debit/credit lines for a JournalEntry.
    """
    journal = models.ForeignKey(
        JournalEntry,
        on_delete=models.CASCADE,
        related_name='lines',
    )
    account = models.ForeignKey(
        ChartOfAccount,
        on_delete=models.PROTECT,
        related_name='journal_lines',
    )
    description = models.CharField(max_length=255, blank=True)
    debit = models.DecimalField(max_digits=64, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=64, decimal_places=2, default=0)

    class Meta:
        ordering = ['id']
        indexes = [
            models.Index(fields=['journal']),
            models.Index(fields=['account']),
        ]

    def __str__(self):
        return f'{self.account.code} ({self.debit} / {self.credit})'


class LedgerEntry(models.Model):
    """
    General ledger line (per account, per journal line).
    This is the atomic row used to build Trial Balance, P&L, and Balance Sheet.
    """
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='ledger_entries',
    )
    account = models.ForeignKey(
        ChartOfAccount,
        on_delete=models.PROTECT,
        related_name='ledger_entries',
    )
    journal_line = models.ForeignKey(
        JournalEntryLine,
        on_delete=models.CASCADE,
        related_name='ledger_entries',
    )
    date = models.DateField(default=timezone.now)
    debit = models.DecimalField(max_digits=64, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=64, decimal_places=2, default=0)
    balance = models.DecimalField(
        max_digits=64,
        decimal_places=2,
        default=0,
        help_text='Running balance for this account (as of this entry).',
    )
    transaction = models.ForeignKey(
        AccountingTransaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ledger_entries',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date', 'id']
        indexes = [
            models.Index(fields=['company', 'account', 'date']),
        ]

    def __str__(self):
        return f'{self.account.code} {self.date} ({self.debit}/{self.credit})'

