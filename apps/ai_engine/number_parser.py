# -*- coding: utf-8 -*-
"""
Robust number/amount parsing for documents.
Handles: US (1,234.56), European (1.234,56 or 1 234,56), currency symbols, tables, extra symbols.
"""
import re
from decimal import Decimal, InvalidOperation


# Currency symbols (in regex use R not \R - \R is invalid escape in Python re)
# CURRENCY_PREFIXES / CURRENCY_PATTERN / AMOUNT_CANDIDATE_PATTERN unused below; strip_currency_and_symbols does the work


def strip_currency_and_symbols(s):
    """Remove currency symbols and common noise from a string. Leaves digits, spaces, comma, dot, minus."""
    if not s or not isinstance(s, str):
        return ''
    s = s.strip()
    # Remove common currency symbols (unicode and ascii)
    for sym in ('€', '$', '£', '¥', '₹', '₦', '₩', '₪', '₱', 'R', 'zł', 'kr', '#', 'Naira', 'NGN', 'USD', 'EUR', 'GBP', 'CAD', 'AUD', 'ZAR', 'KES', 'GHS', 'CFA', 'XAF', 'XOF'):
        s = re.sub(re.escape(sym), '', s, flags=re.IGNORECASE)
    s = re.sub(r'[^\d\s.,\-\(\)]', '', s)
    return s.strip()


def normalize_amount_string(raw):
    """
    Convert a raw amount string (US, European, or mixed) into a string safe for Decimal().
    Returns normalized string or None if invalid.
    - US: 1,234.56  -> 1234.56
    - European: 1.234,56 or 1 234,56 -> 1234.56
    - Negative: (1.234,56) or -1,234.56 -> -1234.56
    """
    if not raw or not isinstance(raw, str):
        return None
    s = strip_currency_and_symbols(raw)
    if not s:
        return None
    # Negative in parentheses
    negative = False
    if s.startswith('(') and s.endswith(')'):
        negative = True
        s = s[1:-1].strip()
    if s.startswith('-'):
        negative = True
        s = s[1:].strip()
    # Remove any remaining spaces (thousands separator in some locales)
    s = s.replace(' ', '')
    if not s or s in ('.', ',', '-', '+'):
        return None
    # Detect format: last comma or dot separates decimals?
    # European: comma is decimal (1.234,56). US: dot is decimal (1,234.56).
    last_comma = s.rfind(',')
    last_dot = s.rfind('.')
    if last_comma > last_dot:
        # European: comma is decimal separator
        s = s.replace('.', '').replace(',', '.')
    else:
        # US (or integer): dot is decimal, comma is thousands
        s = s.replace(',', '')
    if not s or s == '.':
        return None
    try:
        d = Decimal(s)
        if d.is_nan() or d.is_infinite():
            return None
        if negative:
            d = -d
        return str(d.quantize(Decimal('0.01')) if d.as_tuple().exponent < -2 else d)
    except (InvalidOperation, ValueError, TypeError, ArithmeticError):
        return None


def parse_amount_to_decimal(raw):
    """
    Parse any amount string to Decimal. Handles currencies and European/US formats.
    Returns Decimal or None.
    """
    norm = normalize_amount_string(raw)
    if norm is None:
        return None
    try:
        d = Decimal(norm)
        if d.is_nan() or d.is_infinite():
            return None
        return d
    except (InvalidOperation, ValueError, TypeError, ArithmeticError):
        return None


def extract_amount_candidates(text):
    """
    Find all substrings in text that look like monetary amounts.
    Returns list of (Decimal, original_match_str).
    Handles US (1,234.56), European (1.234,56 or 1 234,56), currency symbols, tables.
    """
    if not text:
        return []
    seen = set()
    results = []
    # Two patterns: (1) currency + digits with separators, (2) plain digits with . or ,
    for pattern in (
        r'[\€\$\£\¥\₹\₦\₩Rzł\#\s\-\(]*([\d][\d\s.,]*\d)[\€\$\£\¥\₹\₦\₩Rzł\#\s\)]*',
        r'([\d,]+\.?\d*|[\d.]+,\d+)',
    ):
        for m in re.finditer(pattern, text):
            raw = (m.group(1) or m.group(0)).strip()
            if not raw:
                continue
            full = m.group(0)
            if full.strip().startswith('(') and full.strip().endswith(')'):
                raw = '(' + raw + ')'
            key = raw[:80]
            if key in seen:
                continue
            seen.add(key)
            val = parse_amount_to_decimal(raw)
            if val is not None:
                results.append((val, raw))
    return results
