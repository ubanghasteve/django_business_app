# -*- coding: utf-8 -*-
"""
Finance engine - FinancialTransaction model. Company-scoped.
"""
from django.db import models
from django.conf import settings
from decimal import Decimal


class Account(models.Model):
    """
    General Ledger account (Chart of Accounts). Company-scoped.
    Used for journal entries that back all financial and tax reports.
    """
    TYPE_ASSET = 'asset'
    TYPE_LIABILITY = 'liability'
    TYPE_EQUITY = 'equity'
    TYPE_INCOME = 'income'
    TYPE_EXPENSE = 'expense'

    TYPE_CHOICES = [
        (TYPE_ASSET, 'Asset'),
        (TYPE_LIABILITY, 'Liability'),
        (TYPE_EQUITY, 'Equity'),
        (TYPE_INCOME, 'Income'),
        (TYPE_EXPENSE, 'Expense'),
    ]

    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='finance_accounts',
    )
    code = models.CharField(max_length=20, blank=True)
    name = models.CharField(max_length=100)
    account_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [['company', 'code', 'name']]
        ordering = ['account_type', 'code', 'name']
        verbose_name = 'Account'
        verbose_name_plural = 'Accounts'

    def __str__(self):
        return f'{self.name} ({self.account_type})'


class FinancialTransaction(models.Model):
    """
    Extracted financial transaction from a document. Company-scoped.
    """
    TRANSACTION_REVENUE = 'revenue'
    TRANSACTION_EXPENSE = 'expense'
    TRANSACTION_PURCHASE = 'purchase'
    TRANSACTION_VAT_INPUT = 'vat_input'
    TRANSACTION_VAT_OUTPUT = 'vat_output'
    TRANSACTION_CHOICES = [
        (TRANSACTION_REVENUE, 'Revenue'),
        (TRANSACTION_EXPENSE, 'Expense'),
        (TRANSACTION_PURCHASE, 'Purchase'),
        (TRANSACTION_VAT_INPUT, 'VAT Input'),
        (TRANSACTION_VAT_OUTPUT, 'VAT Output'),
    ]

    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='financial_transactions',
        null=False,
    )
    document = models.ForeignKey(
        'documents.Document',
        on_delete=models.CASCADE,
        related_name='financial_transactions',
        null=True,
        blank=True,
    )
    transaction_type = models.CharField(
        max_length=20,
        choices=TRANSACTION_CHOICES,
        db_index=True,
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    vat_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'), null=True, blank=True)
    transaction_date = models.DateField(null=True, blank=True)
    description = models.CharField(max_length=500, blank=True)
    reference = models.CharField(max_length=100, blank=True)  # e.g. invoice number
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-transaction_date', '-created_at']
        verbose_name = 'Financial Transaction'
        verbose_name_plural = 'Financial Transactions'

    def __str__(self):
        return f"{self.get_transaction_type_display()} {self.amount} ({self.transaction_date})"


class JournalEntry(models.Model):
    """
    General Ledger journal entry header. One or more JournalLine rows belong to it.
    """
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='journal_entries',
    )
    transaction = models.ForeignKey(
        FinancialTransaction,
        on_delete=models.CASCADE,
        related_name='journal_entries',
        null=True,
        blank=True,
    )
    entry_date = models.DateField(null=True, blank=True)
    description = models.CharField(max_length=255, blank=True)
    reference = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-entry_date', '-created_at']
        verbose_name = 'Journal Entry'
        verbose_name_plural = 'Journal Entries'

    def __str__(self):
        return f"JE {self.pk} {self.entry_date} {self.description}"


class JournalLine(models.Model):
    """
    Single debit or credit line in a journal entry.
    """
    entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.CASCADE,
        related_name='lines',
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='journal_lines',
    )
    debit = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    credit = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))

    class Meta:
        verbose_name = 'Journal Line'
        verbose_name_plural = 'Journal Lines'

    def __str__(self):
        return f"{self.account.name}: D{self.debit} C{self.credit}"
