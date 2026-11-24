# -*- coding: utf-8 -*-
"""
Tax engine - compute_tax from financial transactions.
Formulas: profit = revenue - expenses; corporate_tax = profit * 0.30; vat_payable = output_vat - input_vat.
"""
from decimal import Decimal, InvalidOperation
from datetime import date
from django.db.models import Sum

from apps.finance_engine.models import FinancialTransaction
from .models import TaxRecord


def _safe_decimal(value, default=Decimal('0')):
    """Ensure value is a valid Decimal for DB; avoid InvalidOperation."""
    if value is None:
        return default
    try:
        d = Decimal(str(value))
        if d.is_nan() or d.is_infinite():
            return default
        return d.quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError, TypeError, ArithmeticError):
        return default


def compute_tax(company, period_type, period_start, period_end):
    """
    Compute tax for a company over a date range from FinancialTransaction data.
    period_type: 'monthly' | 'quarterly' | 'yearly'
    period_start, period_end: date objects.
    Returns: TaxRecord (created or updated).
    """
    if not company:
        return None
    qs = FinancialTransaction.objects.filter(
        company=company,
        transaction_date__gte=period_start,
        transaction_date__lte=period_end,
    )
    rev = _safe_decimal(qs.filter(transaction_type=FinancialTransaction.TRANSACTION_REVENUE).aggregate(s=Sum('amount'))['s'])
    exp = _safe_decimal(qs.filter(transaction_type__in=[
        FinancialTransaction.TRANSACTION_EXPENSE,
        FinancialTransaction.TRANSACTION_PURCHASE,
    ]).aggregate(s=Sum('amount'))['s'])
    vat_out = _safe_decimal(qs.filter(transaction_type=FinancialTransaction.TRANSACTION_VAT_OUTPUT).aggregate(s=Sum('amount'))['s'])
    vat_in = _safe_decimal(qs.filter(transaction_type=FinancialTransaction.TRANSACTION_VAT_INPUT).aggregate(s=Sum('amount'))['s'])

    try:
        profit = rev - exp
        if profit < 0:
            profit = Decimal('0')
        profit = profit.quantize(Decimal('0.01'))
    except (InvalidOperation, ArithmeticError, TypeError):
        profit = Decimal('0')

    try:
        corporate_tax = (profit * Decimal('0.30')).quantize(Decimal('0.01'))
    except (InvalidOperation, ArithmeticError, TypeError):
        corporate_tax = Decimal('0')

    try:
        vat_payable = (vat_out - vat_in).quantize(Decimal('0.01'))
        if vat_payable < 0:
            vat_payable = Decimal('0')
    except (InvalidOperation, ArithmeticError, TypeError):
        vat_payable = Decimal('0')

    record, _ = TaxRecord.objects.update_or_create(
        company=company,
        period_type=period_type,
        period_start=period_start,
        period_end=period_end,
        defaults={
            'total_revenue': rev,
            'total_expenses': exp,
            'taxable_profit': profit,
            'corporate_tax': corporate_tax,
            'vat_payable': vat_payable,
        },
    )
    return record
