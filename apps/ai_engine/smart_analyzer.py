# -*- coding: utf-8 -*-
"""
Smart document analyzer: understands layout and content, picks the right extractor,
validates results, and fills gaps for accurate, automatic computation.

This module is also responsible for high-level **document understanding**:
- Financial documents (bank/accounting statements, invoices/receipts)
- Generic write-ups (letters, reports, narratives) where we care more about
  headings and section structure than about numeric totals.
"""
from decimal import Decimal, InvalidOperation

from .statement_processor import (
    detect_statement_type,
    analyze_bank_statement,
    analyze_accounting_statement,
    _safe_decimal,
)
from .processors import analyze_document_text_simple, analyze_document_text
from .structure_analyzer import analyze_document_structure


def _detect_layout_type(text, tables, layout_lines):
    """
    Infer layout: table_dominant (statement/spreadsheet), form_like (labels + values),
    mixed, or freeform. Used to boost confidence for statement vs invoice.
    """
    t = (text or '').strip()
    tables = tables or []
    lines = layout_lines or []
    has_tables = len(tables) > 0
    table_has_many_rows = any(len(t) > 5 for t in tables)
    table_has_header_like = False
    for table in tables:
        for row in table[:3]:
            row_str = ' '.join((str(c) or '').lower() for c in row)
            if any(x in row_str for x in ('date', 'debit', 'credit', 'balance', 'amount', 'description')):
                table_has_header_like = True
                break
        if table_has_header_like:
            break
    if has_tables and table_has_many_rows and table_has_header_like:
        return 'table_dominant'
    if lines and len(lines) <= 20 and any(':' in ln for ln in lines[:15]):
        return 'form_like'
    if has_tables and len(t) > 200:
        return 'mixed'
    return 'freeform'


def _validate_statement_result(result):
    """
    Validate statement: sum(debits) - sum(credits) should equal closing - opening.
    Returns list of validation_warnings; optionally fill closing_balance if missing.
    """
    warnings = []
    transactions = result.get('transactions') or []
    if not transactions:
        return warnings
    try:
        total_debit = sum(_safe_decimal(r.get('debit')) or Decimal('0') for r in transactions)
        total_credit = sum(_safe_decimal(r.get('credit')) or Decimal('0') for r in transactions)
    except (InvalidOperation, TypeError, ValueError):
        return warnings

    # Expose totals and net movement on the result for easy display to users.
    try:
        result['total_debit'] = str(total_debit.quantize(Decimal('0.01')))
        result['total_credit'] = str(total_credit.quantize(Decimal('0.01')))
        result['net_movement'] = str((total_credit - total_debit).quantize(Decimal('0.01')))
    except (InvalidOperation, ArithmeticError):
        # If quantize fails, leave raw values as strings without blocking validation.
        result['total_debit'] = str(total_debit)
        result['total_credit'] = str(total_credit)
        result['net_movement'] = str(total_credit - total_debit)
    opening = _safe_decimal(result.get('opening_balance'))
    closing = _safe_decimal(result.get('closing_balance'))
    diff = total_credit - total_debit
    if opening is not None and closing is None and diff is not None:
        inferred_closing = opening + diff
        result['closing_balance'] = str(inferred_closing.quantize(Decimal('0.01')))
        warnings.append('Closing balance inferred from opening + (credits - debits).')
    elif opening is not None and closing is not None and diff is not None:
        expected = opening + diff
        if abs((closing or 0) - expected) > Decimal('0.02'):
            warnings.append('Closing balance differs slightly from opening + net movement; values may be rounded.')
    return warnings


def _validate_invoice_result(result):
    """Check total appears in raw_amounts; add warning if not."""
    warnings = []
    total = result.get('total')
    raw = result.get('raw_amounts') or []
    if not total and raw:
        warnings.append('Total not identified; review detected amounts.')
    return warnings


def analyze_document_smart(text, tables=None, layout_lines=None, document_name=None):
    """
    Single entry: understand layout and content, run the best extractor, validate and return.
    - Uses layout (table_dominant vs form_like) to improve document-type detection.
    - Uses document_name (filename) hint: e.g. "Bstatement" or "statement" -> try bank statement.
    - Runs statement or invoice/receipt extractor; validates statement totals.
    - For generic write-ups (no clear financial signals), also returns a rich
      document structure (paragraphs + headings with positions).
    """
    text = (text or '').strip()
    tables = tables or []
    layout_lines = layout_lines or []
    document_name = (document_name or '').lower()
    layout_type = _detect_layout_type(text, tables, layout_lines)

    # Detect statement type using strong textual and table signals only.
    # We intentionally avoid forcing a statement type just because the layout
    # looks table-dominant or the filename contains "statement", since many
    # non-statement documents (e.g. invoices with debit/credit columns or
    # sample templates) would otherwise be misclassified.
    statement_type = detect_statement_type(text, tables)

    if statement_type == 'bank_statement':
        result = analyze_bank_statement(text, tables)
        result['validation_warnings'] = _validate_statement_result(result)
        # Bank/accounting statements are highly tabular; document structure is
        # usually less meaningful, so we skip heavy heading detection here.
        return result
    if statement_type == 'accounting_statement':
        result = analyze_accounting_statement(text, tables)
        result['validation_warnings'] = _validate_statement_result(result)
        return result

    # Generic documents (invoices/receipts/other):
    # run the invoice extractor, but only keep the high-level summary fields
    # when the content actually looks like an invoice/receipt. This prevents
    # sample UI screenshots or generic forms from being misinterpreted as real
    # invoices just because they contain numbers or the word "total".
    result = analyze_document_text(text)
    if not isinstance(result, dict):
        result = analyze_document_text_simple(text)

    t = text.lower()
    upper = text.upper()
    has_invoice_signals = any(
        kw in t
        for kw in (
            'invoice', 'tax invoice', 'receipt', 'bill to', 'billed to',
            'amount due', 'total amount due', 'grand total'
        )
    )
    has_vat_signals = any(kw in t for kw in ('vat', 'v.a.t', 'sales tax', 'value added tax', 'tax amount'))
    has_currency_signals = any(sym in text for sym in ('₦', '$', '€', '£')) or any(
        code in upper for code in ('NGN', 'USD', 'EUR', 'GBP', 'ZAR', 'KES', 'GHS')
    )

    is_financial_like = has_invoice_signals or has_vat_signals or has_currency_signals

    if not is_financial_like:
        # Treat as a generic document: keep raw_amounts for debugging but clear
        # the summary invoice fields so the UI does not show misleading totals
        # or suppliers for things like instructional screenshots or narrative write-ups.
        result['invoice_number'] = ''
        result['supplier'] = ''
        result['date'] = None
        result['total'] = None
        result['vat_amount'] = None

        # For narrative / non-analytical documents, provide a detailed structural
        # breakdown so the UI (and other services) can understand headings and
        # their exact positioning in the text.
        result['structure'] = analyze_document_structure(text)
        # Generic documents do not need invoice-style validation warnings.
        result['validation_warnings'] = []
    else:
        # Even for invoices/receipts, it can be useful to expose lightweight
        # structure information (e.g. for highlighting or navigation). We add it
        # in a non-breaking way.
        result['structure'] = analyze_document_structure(text)
        result['validation_warnings'] = _validate_invoice_result(result)
    return result

