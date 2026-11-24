# -*- coding: utf-8 -*-
"""
AI Engine - Bank statement and accounting statement analysis.
Table-aware extraction: parses PDF tables and OCR text to extract
account info, period, opening/closing balances, and transaction lines.
Handles both PDF (pdfplumber tables) and image (OCR) input.
"""
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from .number_parser import parse_amount_to_decimal, extract_amount_candidates


# ----- Helpers -----

def _safe_decimal(raw):
    if raw is None:
        return None
    return parse_amount_to_decimal(str(raw).strip())


def _parse_date_cell(cell):
    """Parse a date from a table cell. Returns YYYY-MM-DD or None."""
    if not cell or not isinstance(cell, str):
        return None
    s = cell.strip()[:20]
    # DD/MM/YYYY, DD-MM-YYYY, YYYY-MM-DD, DD.MM.YYYY
    for fmt in ('%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d', '%d.%m.%Y', '%d/%m/%y', '%d-%m-%y', '%Y/%m/%d'):
        try:
            dt = datetime.strptime(s[:10].replace('.', '-').replace('/', '-'), fmt.split('/')[0].replace('%y', '%Y') if '%y' in fmt else fmt)
            if dt.year < 100:
                dt = dt.replace(year=dt.year + 2000)
            return dt.strftime('%Y-%m-%d')
        except (ValueError, TypeError):
            pass
    # Flexible: look for 1-4 digits, 1-2, 1-4
    m = re.search(r'(\d{1,4})[-/.](\d{1,2})[-/.](\d{1,4})', s)
    if m:
        g = m.groups()
        try:
            if len(g[0]) == 4:
                y, mo, d = int(g[0]), int(g[1]), int(g[2])
            else:
                d, mo, y = int(g[0]), int(g[1]), int(g[2])
                if y < 100:
                    y += 2000
            if 1 <= mo <= 12 and 1 <= d <= 31 and 1900 <= y <= 2100:
                return f'{y}-{mo:02d}-{d:02d}'
        except (ValueError, IndexError):
            pass
    return None


def _column_index(header_row, keywords):
    """Return 0-based index of first cell that contains any of the keywords (case-insensitive)."""
    if not header_row:
        return -1
    for i, cell in enumerate(header_row):
        c = (cell or '').strip().lower()
        for kw in keywords:
            if kw in c:
                return i
    return -1


def _is_likely_header_row(row):
    """True if row looks like a header (contains words like date, description, debit, credit)."""
    if not row:
        return False
    combined = ' '.join((str(c) or '').lower() for c in row)
    return any(x in combined for x in ('date', 'description', 'debit', 'credit', 'balance', 'amount', 'particulars', 'narration', 'details', 'withdrawal', 'deposit'))


def _is_likely_data_row(row, date_idx, amount_indices):
    """True if row has at least a date or one amount and is not all empty."""
    cells = [str(c).strip() for c in row]
    if not any(cells):
        return False
    if date_idx >= 0 and date_idx < len(cells) and _parse_date_cell(cells[date_idx]):
        return True
    for i in amount_indices:
        if i >= 0 and i < len(cells) and _safe_decimal(cells[i]) is not None:
            return True
    return False


# ----- Statement type detection -----

BANK_KEYWORDS = [
    'bank statement', 'account statement', 'statement of account',
    'opening balance', 'closing balance', 'balance b/f', 'balance c/f',
    'brought forward', 'carried forward', 'available balance',
    'account number', 'account no', 'sort code', 'branch',
    'debit', 'credit', 'withdrawal', 'deposit', 'transaction'
]

ACCOUNTING_KEYWORDS = [
    # Strong, explicit accounting-report phrases only. We deliberately avoid
    # very generic words like "debit", "credit" or "balance" here because they
    # appear on many non-statement documents (e.g. invoices, receipts) and
    # would cause false positives.
    'trial balance', 'general ledger', 'ledger account', 'account summary',
    'statement of account',
    'accounting statement', 'financial statement', 'income statement',
    'balance sheet', 'profit and loss', 'p&l'
]


def detect_statement_type(text, tables):
    """
    Detect if content is a bank statement, accounting statement, or neither.
    Returns: 'bank_statement' | 'accounting_statement' | None
    """
    t = (text or '').lower()
    # Strong bank signals
    if any(k in t for k in ('bank statement', 'account statement', 'statement of account', 'opening balance', 'closing balance', 'balance b/f', 'balance c/f')):
        if any(k in t for k in ('trial balance', 'general ledger', 'ledger account')) and 'bank' not in t:
            return 'accounting_statement'
        return 'bank_statement'
    # Table shape: bank often has Date, Description, Debit, Credit, Balance
    for table in (tables or []):
        for row in table[:3]:
            row_str = ' '.join((str(c) or '').lower() for c in row)
            if 'debit' in row_str and 'credit' in row_str and ('balance' in row_str or 'date' in row_str):
                if 'bank' in t or 'account' in t or 'statement' in t:
                    return 'bank_statement'
                if any(k in t for k in ACCOUNTING_KEYWORDS):
                    return 'accounting_statement'
                return 'bank_statement'  # default table with debit/credit to bank
    if any(k in t for k in ACCOUNTING_KEYWORDS):
        return 'accounting_statement'
    return None


# ----- Balance and account extraction from text -----

def _extract_balance_labels(text):
    """Extract opening and closing balance from body text. Returns (opening_str, closing_str)."""
    t = (text or '').replace('\n', ' ')
    opening = closing = None
    # Opening
    for pattern in [
        r'opening\s+balance[:\s]+([\d\s.,\-\(\)€$£]+)',
        r'balance\s+b/f[:\s]+([\d\s.,\-\(\)€$£]+)',
        r'brought\s+forward[:\s]+([\d\s.,\-\(\)€$£]+)',
        r'opening\s+balance\s+brought\s+forward[:\s]+([\d\s.,\-\(\)€$£]+)',
        r'beginning\s+balance[:\s]+([\d\s.,\-\(\)€$£]+)',
    ]:
        m = re.search(pattern, t, re.IGNORECASE)
        if m:
            opening = m.group(1).strip()
            break
    # Closing
    for pattern in [
        r'closing\s+balance[:\s]+([\d\s.,\-\(\)€$£]+)',
        r'balance\s+c/f[:\s]+([\d\s.,\-\(\)€$£]+)',
        r'carried\s+forward[:\s]+([\d\s.,\-\(\)€$£]+)',
        r'closing\s+balance\s+carried\s+forward[:\s]+([\d\s.,\-\(\)€$£]+)',
        r'ending\s+balance[:\s]+([\d\s.,\-\(\)€$£]+)',
        r'available\s+balance[:\s]+([\d\s.,\-\(\)€$£]+)',
        r'current\s+balance[:\s]+([\d\s.,\-\(\)€$£]+)',
    ]:
        m = re.search(pattern, t, re.IGNORECASE)
        if m:
            closing = m.group(1).strip()
            break
    return (opening, closing)


def _extract_account_info(text):
    """Extract account name, account number, bank name from text."""
    t = (text or '') + ' '
    info = {'account_name': '', 'account_number': '', 'bank_name': ''}
    # Account number
    for pattern in [
        r'account\s+number[:\s]*([A-Z0-9\-\s]{4,30})',
        r'account\s+no\.?[:\s]*([A-Z0-9\-\s]{4,30})',
        r'a/c\s+no\.?[:\s]*([A-Z0-9\-\s]{4,30})',
    ]:
        m = re.search(pattern, t, re.IGNORECASE)
        if m:
            info['account_number'] = m.group(1).strip()[:50]
            break
    # Bank name: often at top of statement
    lines = [ln.strip() for ln in text.split('\n') if ln.strip()][:15]
    for line in lines:
        if len(line) > 3 and len(line) < 80:
            if re.search(r'bank|limited|plc|ltd|corp', line, re.IGNORECASE) and not re.match(r'^[\d\s.,\-]+$', line):
                info['bank_name'] = line[:100]
                break
    # Account name: sometimes "Account name:" or second line
    for pattern in [
        r'account\s+name[:\s]*([^\n]{2,80})',
        r'name\s+on\s+account[:\s]*([^\n]{2,80})',
    ]:
        m = re.search(pattern, t, re.IGNORECASE)
        if m:
            info['account_name'] = m.group(1).strip()[:100]
            break
    return info


def _extract_period(text):
    """Extract statement period start/end from text."""
    t = (text or '').lower()
    period_start = period_end = None
    # "Statement period: 01/01/2025 - 31/01/2025" or "From ... To ..."
    m = re.search(r'(?:period|from|date range)[:\s]*(\d{1,4})[-/.](\d{1,2})[-/.](\d{1,4})\s*(?:-|to)\s*(\d{1,4})[-/.](\d{1,2})[-/.](\d{1,4})', t, re.IGNORECASE)
    if m:
        g = m.groups()
        try:
            def to_ymd(a, b, c):
                if len(a) == 4:  # YYYY-MM-DD
                    return int(a), int(b), int(c)
                return int(c) + (2000 if int(c) < 100 else 0), int(b), int(a)
            y1, m1, d1 = to_ymd(g[0], g[1], g[2])
            y2, m2, d2 = to_ymd(g[3], g[4], g[5])
            if 1 <= m1 <= 12 and 1 <= d1 <= 31 and 1 <= m2 <= 12 and 1 <= d2 <= 31:
                period_start = f'{y1}-{m1:02d}-{d1:02d}'
                period_end = f'{y2}-{m2:02d}-{d2:02d}'
        except (ValueError, IndexError, TypeError):
            pass
    # "Month: January 2025" or "For the month of ..."
    if not period_start:
        for pattern in [
            r'(?:month|period)[:\s]*(\w+)\s+(\d{4})',
            r'for\s+(?:the\s+)?(?:month\s+of\s+)?(\w+)\s+(\d{4})',
        ]:
            m = re.search(pattern, t)
            if m:
                try:
                    month_name, year = m.group(1), int(m.group(2))
                    dt = datetime.strptime(month_name[:3], '%b')
                    period_start = f'{year}-{dt.month:02d}-01'
                    import calendar
                    _, last = calendar.monthrange(year, dt.month)
                    period_end = f'{year}-{dt.month:02d}-{last}'
                except (ValueError, TypeError):
                    pass
                break
    return (period_start, period_end)


def _extract_currency(text):
    """Detect currency from symbols or text.

    Some bank PDFs (especially OCR output) may contain multiple currencies in the
    header/footer (e.g. template text mentioning EUR) while the real currency is
    shown in a line like "Currency: NGN". To be more robust we:
    - Count occurrences of known currency codes/symbols.
    - Prefer the currency that appears most often.
    - Bias towards explicit "Currency: XXX" labels if present.
    """
    t = (text or '')
    upper = t.upper()

    # 1) Strongest signal: explicit "Currency: XXX" style label.
    m = re.search(r'currency[^A-Z0-9]{0,10}([A-Z]{3})', upper)
    if m:
        code = m.group(1)
        # Only accept codes we know; otherwise ignore and fall back.
        if code in {'NGN', 'EUR', 'USD', 'GBP', 'ZAR', 'KES', 'GHS'}:
            return code

    candidates = {
        'NGN': 0,
        'EUR': 0,
        'USD': 0,
        'GBP': 0,
        'ZAR': 0,
        'KES': 0,
        'GHS': 0,
    }
    # 2) Count raw symbol/code occurrences with smaller weight.
    if '₦' in t:
        candidates['NGN'] += t.count('₦') * 3
    for code in ['NGN', 'EUR', 'USD', 'GBP', 'ZAR', 'KES', 'GHS']:
        candidates[code] += upper.count(code)
    if '€' in t:
        candidates['EUR'] += t.count('€') * 3
    if '£' in t:
        candidates['GBP'] += t.count('£') * 3
    if '$' in t:
        candidates['USD'] += t.count('$') * 3
    # Fallback: look for "Naira" word.
    if re.search(r'\bNAIRA\b', upper):
        candidates['NGN'] += 2
    # 3) If exactly one currency has any signal, use it.
    non_zero = [code for code, score in candidates.items() if score > 0]
    if len(non_zero) == 1:
        return non_zero[0]
    # 4) Otherwise pick the highest score (still biased to NGN via symbols/labels).
    best_code, best_score = None, 0
    for code, score in candidates.items():
        if score > best_score:
            best_code, best_score = code, score
    return best_code or ''


# ----- Table parsing: find header and data rows -----

def _find_transaction_table(tables):
    """
    Find the main transaction table (has Date, Debit, Credit and/or Balance).
    Returns (header_row, data_rows) or (None, []).
    """
    for table in (tables or []):
        if len(table) < 2:
            continue
        header_idx = -1
        for i, row in enumerate(table):
            if _is_likely_header_row(row):
                header_idx = i
                break
        if header_idx < 0:
            continue
        header = [str(c).strip().lower() for c in table[header_idx]]
        date_idx = _column_index(table[header_idx], ['date', 'value date', 'posting date', 'trans date'])
        desc_idx = _column_index(table[header_idx], ['description', 'particulars', 'narration', 'details', 'reference', 'transaction', 'memo'])
        debit_idx = _column_index(table[header_idx], ['debit', 'withdrawal', 'out', 'dr'])
        credit_idx = _column_index(table[header_idx], ['credit', 'deposit', 'in', 'cr', 'payment'])
        balance_idx = _column_index(table[header_idx], ['balance', 'running balance'])
        amount_idx = _column_index(table[header_idx], ['amount'])
        if date_idx < 0:
            date_idx = 0
        if desc_idx < 0:
            desc_idx = 1 if date_idx == 0 else 0
        amount_indices = [i for i in [debit_idx, credit_idx, balance_idx, amount_idx] if i >= 0]
        if not amount_indices and debit_idx < 0 and credit_idx < 0:
            continue
        raw_rows = []
        for row in table[header_idx + 1:]:
            if not row:
                continue
            cells = [str(c).strip() if c is not None else '' for c in row]
            if not _is_likely_data_row(cells, date_idx, amount_indices or [0]):
                if data_rows and amount_indices:
                    break
                continue
            date_val = _parse_date_cell(cells[date_idx]) if date_idx < len(cells) else None
            desc = cells[desc_idx] if desc_idx < len(cells) else ''
            debit = _safe_decimal(cells[debit_idx]) if debit_idx >= 0 and debit_idx < len(cells) else None
            credit = _safe_decimal(cells[credit_idx]) if credit_idx >= 0 and credit_idx < len(cells) else None
            balance = _safe_decimal(cells[balance_idx]) if balance_idx >= 0 and balance_idx < len(cells) else None
            amount = _safe_decimal(cells[amount_idx]) if amount_idx >= 0 and amount_idx < len(cells) else None
            if amount is not None and debit is None and credit is None:
                if amount >= 0:
                    credit = amount
                else:
                    debit = abs(amount)
            raw_rows.append({
                'date': date_val,
                'description': (desc or '')[:300],
                'debit': str(debit) if debit is not None else None,
                'credit': str(credit) if credit is not None else None,
                'balance': str(balance) if balance is not None else None,
            })
        # Merge continuation lines: many bank statements wrap the description
        # over multiple physical rows where the subsequent rows have no date
        # and no amounts. Append those descriptions to the previous row instead
        # of treating them as separate transactions.
        data_rows = []
        for row in raw_rows:
            has_amount = (row.get('debit') is not None) or (row.get('credit') is not None)
            has_date = row.get('date') is not None
            desc = (row.get('description') or '').strip()
            if data_rows and not has_amount and not has_date and desc:
                prev = data_rows[-1]
                prev_desc = prev.get('description') or ''
                prev['description'] = (prev_desc + ' ' + desc).strip()[:300]
            else:
                data_rows.append(row)
        if data_rows:
            return (table[header_idx], data_rows)
    return (None, [])


def _transactions_from_text_fallback(text):
    """
    When no table is found, try to extract transaction-like lines from text:
    (1) date at start of line + description + amount at end;
    (2) any line ending with a single amount (description + amount) for OCR output.
    """
    transactions = []
    seen = set()
    skip_keywords = [
        'dummy',
        'please find below your bank statement',
        'account no',
        'account number',
        'account name',
        'account type',
        'total debit',
        'total credit',
        'opening balance',
        'closing balance',
        'period',
        'currency',
        'printed by',
        'available balance',
        'did you ?)',
        'firstadvance',
        'firstcredit',
        'dial *',
        'firstcontact',
        'page?',
    ]

    def _choose_transaction_amount(amounts):
        """
        Pick the most likely transaction amount from a list of (Decimal, raw) candidates.
        Many OCR statement lines contain both the transaction amount and the running
        balance, plus small artefacts like row numbers. Heuristic:
        - Ignore tiny numbers (< 10) which are often row indexes or noise.
        - Among remaining candidates, if there are 2+, prefer the second-largest
          absolute value (smaller is often the movement, larger the balance).
        - If there is only 1 reasonable candidate, use it.
        """
        if not amounts:
            return None
        # Filter out very small values (likely noise).
        large = []
        for val, raw in amounts:
            try:
                mag = abs(val)
            except Exception:
                try:
                    mag = val.copy_abs()
                except Exception:
                    continue
            if mag < 10:
                continue
            large.append((val, raw, mag))
        if not large:
            return None
        # Sort by absolute magnitude.
        large.sort(key=lambda x: x[2])
        if len(large) == 1:
            best = large[0]
        else:
            # Prefer the second-largest: smaller movement vs larger running balance.
            best = large[-2]
        return best[0], best[1]

    def _extract_date_from_line(raw_line):
        """Try to extract a date from anywhere in the line (numeric or with month names)."""
        # First, reuse the flexible numeric parser.
        d = _parse_date_cell(raw_line)
        if d:
            return d, None
        # Look for DD-MMM-YY or DD-MMM-YYYY patterns (e.g. 21-Oct-2025).
        m = re.search(r'(\d{1,2})[-\s/]?([A-Za-z]{3,})[-\s/]?(\d{2,4})', raw_line)
        if m:
            day, month_name, year = m.group(1), m.group(2), m.group(3)
            try:
                dt = datetime.strptime(month_name[:3].title(), '%b')
                y = int(year)
                if y < 100:
                    y += 2000
                ymd = f'{y:04d}-{dt.month:02d}-{int(day):02d}'
                # Remove the matched substring from the line when building description.
                span_start, span_end = m.span()
                return ymd, (span_start, span_end)
            except (ValueError, TypeError):
                return None, None
        return None, None

    for line in (text or '').split('\n'):
        line = line.strip()
        if len(line) < 6:
            continue
        lower_line = line.lower()
        if any(kw in lower_line for kw in skip_keywords):
            # Header / meta lines from the statement body, not actual transactions.
            continue
        # Date at start: DD/MM/YYYY or DD-MM-YYYY
        m = re.match(r'(\d{1,4})[-/.](\d{1,2})[-/.](\d{1,4})\s+(.+)$', line)
        if m:
            date_str = _parse_date_cell(f'{m.group(1)}-{m.group(2)}-{m.group(3)}')
            rest = m.group(4).strip()
            amounts = extract_amount_candidates(rest)
            chosen = _choose_transaction_amount(amounts)
            amt = chosen[0] if chosen else None
            desc = rest
            if chosen:
                desc = rest.replace(chosen[1], '').strip()
            key = (date_str, desc[:50], str(amt) if amt else '')
            if key not in seen:
                seen.add(key)
                transactions.append({
                    'date': date_str,
                    'description': desc[:300],
                    'debit': str(abs(amt)) if amt is not None and amt < 0 else None,
                    'credit': str(amt) if amt is not None and amt > 0 else None,
                    'balance': None,
                })
            continue
        # No date at start: try to find a date anywhere, then amount at end (common in OCR statements)
        extracted_date, span = _extract_date_from_line(line)
        amounts = extract_amount_candidates(line)
        if amounts:
            chosen = _choose_transaction_amount(amounts)
            if not chosen:
                continue
            amt, raw = chosen
            desc_source = line
            if span is not None:
                # Remove the date substring so description is cleaner.
                s, e = span
                desc_source = (desc_source[:s] + ' ' + desc_source[e:]).strip()
            desc = desc_source.replace(raw, '').strip()
            if len(desc) >= 2 and desc.lower() not in ('debit', 'credit', 'balance', 'amount'):
                key = (desc[:50], str(amt))
                if key not in seen:
                    seen.add(key)
                    transactions.append({
                        'date': extracted_date,
                        'description': desc[:300],
                        'debit': str(abs(amt)) if amt < 0 else None,
                        'credit': str(amt) if amt > 0 else None,
                        'balance': None,
                    })
    return transactions


# ----- Public analyzers -----

def analyze_bank_statement(text, tables=None):
    """
    Analyze text and tables as a bank statement.
    Returns dict: statement_type='bank_statement', account_name, account_number, bank_name,
    period_start, period_end, opening_balance, closing_balance, currency,
    transactions (list of {date, description, debit, credit, balance}).
    """
    tables = tables or []
    result = {
        'statement_type': 'bank_statement',
        'account_name': '',
        'account_number': '',
        'bank_name': '',
        'period_start': None,
        'period_end': None,
        'opening_balance': None,
        'closing_balance': None,
        'currency': '',
        'transactions': [],
    }
    info = _extract_account_info(text)
    result['account_name'] = info['account_name']
    result['account_number'] = info['account_number']
    result['bank_name'] = info['bank_name']
    result['period_start'], result['period_end'] = _extract_period(text)
    result['currency'] = _extract_currency(text)
    ob, cb = _extract_balance_labels(text)
    if ob:
        d = _safe_decimal(ob)
        result['opening_balance'] = str(d) if d is not None else ob
    if cb:
        d = _safe_decimal(cb)
        result['closing_balance'] = str(d) if d is not None else cb
    _, data_rows = _find_transaction_table(tables)
    if data_rows:
        result['transactions'] = data_rows
    else:
        result['transactions'] = _transactions_from_text_fallback(text)
    return result


def analyze_accounting_statement(text, tables=None):
    """
    Analyze text and tables as an accounting statement (trial balance, ledger, etc.).
    Returns same structure as bank statement for consistency; transactions may be debit/credit rows.
    """
    tables = tables or []
    result = {
        'statement_type': 'accounting_statement',
        'account_name': '',
        'account_number': '',
        'bank_name': '',
        'period_start': None,
        'period_end': None,
        'opening_balance': None,
        'closing_balance': None,
        'currency': '',
        'transactions': [],
    }
    result['period_start'], result['period_end'] = _extract_period(text)
    result['currency'] = _extract_currency(text)
    info = _extract_account_info(text)
    result['account_name'] = info['account_name']
    result['account_number'] = info['account_number']
    result['bank_name'] = info['bank_name']
    ob, cb = _extract_balance_labels(text)
    if ob:
        d = _safe_decimal(ob)
        result['opening_balance'] = str(d) if d is not None else ob
    if cb:
        d = _safe_decimal(cb)
        result['closing_balance'] = str(d) if d is not None else cb
    _, data_rows = _find_transaction_table(tables)
    if data_rows:
        result['transactions'] = data_rows
    else:
        result['transactions'] = _transactions_from_text_fallback(text)
    return result
