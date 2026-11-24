# -*- coding: utf-8 -*-
"""
Finance engine - convert AI-extracted data into FinancialTransaction records.
All operations are company-scoped. Uses robust number parsing (European/US, currency symbols).
"""
from decimal import Decimal, InvalidOperation
from datetime import datetime

from .models import FinancialTransaction, Account, JournalEntry, JournalLine

try:
    from apps.ai_engine.number_parser import parse_amount_to_decimal
except ImportError:
    parse_amount_to_decimal = None


def _decimal(value, default=Decimal('0')):
    """Parse value to Decimal; handles European/US formats and currency symbols. Return default on error."""
    if value is None:
        return default
    s = str(value).strip()
    if not s or s in ('.', 'NaN', '-', '+'):
        return default
    if parse_amount_to_decimal:
        d = parse_amount_to_decimal(s)
        if d is not None:
            try:
                return d.quantize(Decimal('0.01'))
            except (InvalidOperation, ArithmeticError):
                return default
    try:
        d = Decimal(s)
        if d.is_nan() or d.is_infinite():
            return default
        return d.quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError, TypeError, ArithmeticError):
        return default


def _parse_date(value):
    if not value:
        return None
    if hasattr(value, 'date'):
        return value.date() if hasattr(value, 'date') else value
    s = str(value).strip()[:10]
    try:
        return datetime.strptime(s, '%Y-%m-%d').date()
    except Exception:
        pass
    try:
        return datetime.strptime(s, '%d/%m/%Y').date()
    except Exception:
        return None


def _get_or_create_default_accounts(company):
    """
    Return a dict of core accounts for the company, creating them if needed.
    This provides a minimal chart of accounts that we can post transactions to.
    """
    if not company:
        return {}
    mappings = {}
    # Bank (asset)
    bank, _ = Account.objects.get_or_create(
        company=company,
        code='1000',
        name='Bank',
        defaults={'account_type': Account.TYPE_ASSET},
    )
    # Revenue
    revenue, _ = Account.objects.get_or_create(
        company=company,
        code='4000',
        name='Revenue',
        defaults={'account_type': Account.TYPE_INCOME},
    )
    # Expense
    expense, _ = Account.objects.get_or_create(
        company=company,
        code='5000',
        name='Expenses',
        defaults={'account_type': Account.TYPE_EXPENSE},
    )
    # VAT input (asset)
    vat_input, _ = Account.objects.get_or_create(
        company=company,
        code='1510',
        name='VAT Input',
        defaults={'account_type': Account.TYPE_ASSET},
    )
    # VAT output (liability)
    vat_output, _ = Account.objects.get_or_create(
        company=company,
        code='2310',
        name='VAT Output',
        defaults={'account_type': Account.TYPE_LIABILITY},
    )
    mappings['bank'] = bank
    mappings['revenue'] = revenue
    mappings['expense'] = expense
    mappings['vat_input'] = vat_input
    mappings['vat_output'] = vat_output
    return mappings


def _app_sync_reference(source_app, source_id):
    """Unique reference for app-sourced transactions to avoid duplicates."""
    return f"{source_app}:{source_id}"


def sync_app_transaction_to_finance(
    *,
    company,
    source_app,
    source_id,
    transaction_type,
    amount,
    transaction_date,
    description='',
    reference=None,
    vat_amount=None,
):
    """
    Create or skip a FinancialTransaction for an app-sourced event (invoice, receipt,
    job order, waybill, expense, inventory) so tax engine and reports see it.
    Uses reference "{source_app}:{source_id}" to avoid duplicates.
    Returns the FinancialTransaction (existing or created), or None.
    """
    if not company or not amount or amount <= 0:
        return None
    ref = _app_sync_reference(source_app, source_id)
    existing = FinancialTransaction.objects.filter(
        company=company,
        reference=ref,
    ).first()
    if existing:
        return existing
    try:
        amount_safe = Decimal(str(amount)).quantize(Decimal('0.01'))
    except (InvalidOperation, ArithmeticError, TypeError, ValueError):
        return None
    if amount_safe <= 0:
        return None
    trans_type = transaction_type
    if trans_type not in (
        FinancialTransaction.TRANSACTION_REVENUE,
        FinancialTransaction.TRANSACTION_EXPENSE,
        FinancialTransaction.TRANSACTION_PURCHASE,
    ):
        trans_type = (
            FinancialTransaction.TRANSACTION_REVENUE
            if trans_type == 'income'
            else FinancialTransaction.TRANSACTION_EXPENSE
        )
    date_val = transaction_date
    if hasattr(date_val, 'date'):
        date_val = date_val.date()
    ft = FinancialTransaction.objects.create(
        company=company,
        document=None,
        transaction_type=trans_type,
        amount=amount_safe,
        vat_amount=Decimal(str(vat_amount or 0)).quantize(Decimal('0.01')) if vat_amount is not None else None,
        transaction_date=date_val,
        description=(description or '')[:500],
        reference=ref,
    )
    post_transaction_to_ledger(ft)
    return ft


def remove_app_transaction_from_finance(company, source_app, source_id):
    """
    Remove the FinancialTransaction (and its journal entries via CASCADE) for an
    app-sourced event when the source is deleted, so tax/reports stay consistent.
    """
    ref = _app_sync_reference(source_app, source_id)
    FinancialTransaction.objects.filter(company=company, reference=ref).delete()


def post_transaction_to_ledger(transaction):
    """
    Create a minimal double-entry journal for a FinancialTransaction.
    This keeps the ledger in sync so we can build P&L and Balance Sheet.
    """
    company = getattr(transaction, 'company', None)
    if not company or not transaction.amount or transaction.amount <= 0:
        return None
    accounts = _get_or_create_default_accounts(company)
    bank = accounts.get('bank')
    revenue = accounts.get('revenue')
    expense = accounts.get('expense')
    vat_input = accounts.get('vat_input')
    vat_output = accounts.get('vat_output')
    if not bank or not revenue or not expense:
        return None

    amount = transaction.amount
    vat_amount = transaction.vat_amount or Decimal('0')
    date_val = transaction.transaction_date
    desc = transaction.description or ''
    ref = transaction.reference or ''

    je = JournalEntry.objects.create(
        company=company,
        transaction=transaction,
        entry_date=date_val,
        description=desc[:255],
        reference=ref[:100],
    )

    # Map FinancialTransaction types to double-entry postings.
    if transaction.transaction_type == FinancialTransaction.TRANSACTION_REVENUE:
        # Customer paid into Bank: Dr Bank, Cr Revenue
        JournalLine.objects.bulk_create([
            JournalLine(entry=je, account=bank, debit=amount, credit=Decimal('0')),
            JournalLine(entry=je, account=revenue, debit=Decimal('0'), credit=amount),
        ])
    elif transaction.transaction_type in (FinancialTransaction.TRANSACTION_EXPENSE, FinancialTransaction.TRANSACTION_PURCHASE):
        # Company paid from Bank: Dr Expense, Cr Bank
        JournalLine.objects.bulk_create([
            JournalLine(entry=je, account=expense, debit=amount, credit=Decimal('0')),
            JournalLine(entry=je, account=bank, debit=Decimal('0'), credit=amount),
        ])
    elif transaction.transaction_type == FinancialTransaction.TRANSACTION_VAT_INPUT and vat_input:
        # VAT we can reclaim: Dr VAT Input, Cr Bank
        JournalLine.objects.bulk_create([
            JournalLine(entry=je, account=vat_input, debit=amount, credit=Decimal('0')),
            JournalLine(entry=je, account=bank, debit=Decimal('0'), credit=amount),
        ])
    elif transaction.transaction_type == FinancialTransaction.TRANSACTION_VAT_OUTPUT and vat_output:
        # VAT we owe: Dr Bank, Cr VAT Output
        JournalLine.objects.bulk_create([
            JournalLine(entry=je, account=bank, debit=amount, credit=Decimal('0')),
            JournalLine(entry=je, account=vat_output, debit=Decimal('0'), credit=amount),
        ])
    else:
        # If type is unknown, at least post to Bank vs Expenses as a fallback.
        JournalLine.objects.bulk_create([
            JournalLine(entry=je, account=expense, debit=amount, credit=Decimal('0')),
            JournalLine(entry=je, account=bank, debit=Decimal('0'), credit=amount),
        ])
    return je


def transaction_extraction_service(company, document, ai_result):
    """
    Convert AI-analyzed document result into financial transactions and save.
    ai_result: dict from ai_engine (invoice_number, supplier, date, total, vat_amount).
    Creates revenue/expense and vat_input/vat_output as appropriate for an invoice/receipt.
    Returns: list of created FinancialTransaction instances.
    """
    if not company:
        return []
    created = []
    total = _decimal(ai_result.get('total'))
    vat_amount = _decimal(ai_result.get('vat_amount'))
    trans_date = _parse_date(ai_result.get('date'))
    ref = (ai_result.get('invoice_number') or '')[:100]
    desc = (ai_result.get('supplier') or '')[:500]

    # Treat as purchase/expense with VAT input when we have a supplier (incoming invoice)
    # Ensure amounts are safe for DB (2 decimal places, non-negative for display)
    try:
        total_safe = total.quantize(Decimal('0.01')) if total is not None else Decimal('0')
    except (InvalidOperation, ArithmeticError, AttributeError):
        total_safe = Decimal('0')
    try:
        vat_safe = vat_amount.quantize(Decimal('0.01')) if vat_amount is not None else None
        if vat_safe is not None and (vat_safe.is_nan() or vat_safe.is_infinite() or vat_safe < 0):
            vat_safe = None
    except (InvalidOperation, ArithmeticError, AttributeError):
        vat_safe = None

    if total_safe > 0:
        t1 = FinancialTransaction(
            company=company,
            document=document,
            transaction_type=FinancialTransaction.TRANSACTION_EXPENSE,
            amount=total_safe,
            vat_amount=vat_safe,
            transaction_date=trans_date,
            description=desc or 'Document extraction',
            reference=ref,
        )
        t1.save()
        post_transaction_to_ledger(t1)
        created.append(t1)
        if vat_safe and vat_safe > 0:
            t2 = FinancialTransaction(
                company=company,
                document=document,
                transaction_type=FinancialTransaction.TRANSACTION_VAT_INPUT,
                amount=vat_safe,
                vat_amount=vat_safe,
                transaction_date=trans_date,
                description=f'VAT input - {ref or "document"}',
                reference=ref,
            )
            t2.save()
            post_transaction_to_ledger(t2)
            created.append(t2)
    return created


def transaction_extraction_from_statement(company, document, ai_result):
    """
    Create financial transactions from a bank or accounting statement AI result.
    ai_result must have 'transactions': list of {date, description, debit, credit, balance}.
    Debit = outflow -> EXPENSE; Credit = inflow -> REVENUE.
    Returns: list of created FinancialTransaction instances.
    """
    if not company:
        return []
    created = []
    for row in ai_result.get('transactions') or []:
        trans_date = _parse_date(row.get('date'))
        desc = (row.get('description') or 'Statement line')[:500]
        ref = (row.get('description') or 'Statement')[:100]
        debit = _decimal(row.get('debit'))
        credit = _decimal(row.get('credit'))
        amount = None
        trans_type = None
        if debit and debit > 0:
            amount = debit
            trans_type = FinancialTransaction.TRANSACTION_EXPENSE
        elif credit and credit > 0:
            amount = credit
            trans_type = FinancialTransaction.TRANSACTION_REVENUE
        if amount is None or trans_type is None or amount <= 0:
            continue
        try:
            amount_safe = amount.quantize(Decimal('0.01'))
        except (InvalidOperation, ArithmeticError, AttributeError):
            continue
        t = FinancialTransaction(
            company=company,
            document=document,
            transaction_type=trans_type,
            amount=amount_safe,
            vat_amount=None,
            transaction_date=trans_date,
            description=desc,
            reference=ref,
        )
        t.save()
        post_transaction_to_ledger(t)
        created.append(t)
    return created
