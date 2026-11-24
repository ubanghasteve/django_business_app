# -*- coding: utf-8 -*-
"""
Tax engine - TaxRecord model. Company-scoped.
"""
from django.db import models
from decimal import Decimal


class TaxRecord(models.Model):
    """
    Computed tax record per period. Company-scoped.
    profit = revenue - expenses; corporate_tax = profit * 0.30; vat_payable = output_vat - input_vat.
    """
    PERIOD_MONTHLY = 'monthly'
    PERIOD_QUARTERLY = 'quarterly'
    PERIOD_YEARLY = 'yearly'
    PERIOD_CHOICES = [
        (PERIOD_MONTHLY, 'Monthly'),
        (PERIOD_QUARTERLY, 'Quarterly'),
        (PERIOD_YEARLY, 'Yearly'),
    ]

    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='tax_records',
        null=False,
    )
    period_type = models.CharField(max_length=20, choices=PERIOD_CHOICES, db_index=True)
    period_start = models.DateField()
    period_end = models.DateField()

    total_revenue = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    total_expenses = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    taxable_profit = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    corporate_tax = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    vat_payable = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-period_end']
        verbose_name = 'Tax Record'
        verbose_name_plural = 'Tax Records'
        unique_together = [['company', 'period_type', 'period_start', 'period_end']]

    def __str__(self):
        return f"{self.company_id} {self.period_type} {self.period_start}–{self.period_end}"
