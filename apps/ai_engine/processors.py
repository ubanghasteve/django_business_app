# -*- coding: utf-8 -*-
"""
AI Engine - NLP-based text processors (regex + optional spaCy).
Extracts structured fields from document text: invoice_number, supplier, date, total, vat_amount.
Uses robust number parsing (European/US formats, currency symbols) via number_parser.
"""
import re
from decimal import Decimal, InvalidOperation
from datetime import datetime

from .number_parser import extract_amount_candidates, parse_amount_to_decimal


def _safe_decimal(raw):
    """Parse string to Decimal; uses robust parser for any format. Return None if invalid."""
    return parse_amount_to_decimal(raw) if raw else None


def _extract_amounts(text):
    """Find numeric amounts (currency). Handles European/US, symbols, tables. Returns list of (value, context)."""
    return extract_amount_candidates(text or '')


def _extract_dates(text):
    """Find date-like strings. Returns list of parsed dates or (year, month, day) tuples."""
    dates = []
    # DD/MM/YYYY or DD-MM-YYYY or YYYY-MM-DD
    for m in re.finditer(r'(\d{1,4})[-/](\d{1,2})[-/](\d{1,4})', text):
        g = m.groups()
        try:
            if len(g[0]) == 4:  # YYYY-MM-DD
                y, mo, d = int(g[0]), int(g[1]), int(g[2])
            else:
                d, mo, y = int(g[0]), int(g[1]), int(g[2])
                if y < 100:
                    y += 2000
            if 1 <= mo <= 12 and 1 <= d <= 31 and 1900 <= y <= 2100:
                dates.append((y, mo, d))
        except (ValueError, IndexError):
            pass
    return dates


def _extract_invoice_number(text):
    """Heuristic: look for 'invoice #', 'inv no', 'number:', digits/id pattern."""
    text_lower = text.lower()
    patterns = [
        r'invoice\s*#?\s*:?\s*([A-Z0-9\-/]+)',
        r'inv\.?\s*no\.?\s*:?\s*([A-Z0-9\-/]+)',
        r'(?:invoice|bill)\s+number\s*:?\s*([A-Z0-9\-/]+)',
        r'#\s*([A-Z0-9\-]{4,})',
    ]
    for pat in patterns:
        m = re.search(pat, text_lower, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ''


def _extract_supplier_simple(text):
    """
    Simple heuristic: first line or block that looks like a name (no digits)
    and is not obviously instructional UI text (e.g. "Delivery quantity",
    "Add one row per product", "e.g. 500kg, 300kg").
    """
    lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
    skip_phrases = [
        'delivery quantity',
        'add one row per product',
        'add one row per delivery',
        'remaining balance is calculated automatically',
        'enter total and delivered quantities',
        'balance will update automatically',
        'product / description (optional)',
        'e.g.',
        'example',
        'optional',
    ]
    for line in lines[:10]:
        lower = line.lower()
        if any(p in lower for p in skip_phrases):
            continue
        if len(line) > 2 and len(line) < 80 and not re.search(r'^\d+[\d,.\s]*$', line):
            # Skip lines that are mostly numbers
            if not re.match(r'^[\d\s.,]+$', line):
                return line[:200]
    return ''


def analyze_document_text_simple(text):
    """
    Rule-based extraction without spaCy. Returns structured dict.
    """
    if not (text and text.strip()):
        return {
            'invoice_number': '',
            'supplier': '',
            'date': None,
            'total': None,
            'vat_amount': None,
            'raw_dates': [],
            'raw_amounts': [],
        }
    amounts = _extract_amounts(text)
    dates = _extract_dates(text)

    total = None
    vat_amount = None

    # ---- Smarter total / VAT detection using context ----
    # 1) Prefer amounts on lines mentioning "total", "grand total", etc.
    # 2) Prefer amounts on lines mentioning "vat", "tax" for vat_amount.
    # 3) Fallback: largest amount = total, smaller positive = vat_amount.
    total_candidates = []
    vat_candidates = []
    for val, ctx in amounts:
        ctx_lower = (ctx or '').lower()
        if any(k in ctx_lower for k in ('grand total', 'invoice total', 'total amount', 'total due', 'amount due')):
            total_candidates.append(val)
        elif 'total' in ctx_lower and not any(k in ctx_lower for k in ('sub-total', 'subtotal')):
            total_candidates.append(val)
        if any(k in ctx_lower for k in ('vat', 'v.a.t', 'tax', 'sales tax', 'value added tax')):
            vat_candidates.append(val)

    try:
        if total_candidates:
            total = max(total_candidates)
        if vat_candidates:
            # VAT is usually smaller positive amount
            vat_pos = [v for v in vat_candidates if v is not None and v > 0]
            if vat_pos:
                vat_amount = min(vat_pos)
        # Fallback heuristics if context-based detection failed
        if total is None and amounts:
            sorted_amounts = sorted(amounts, key=lambda x: x[0], reverse=True)
            total = sorted_amounts[0][0]
        if vat_amount is None and total is not None and amounts:
            for a, _ in sorted(amounts, key=lambda x: x[0], reverse=True)[1:]:
                if a is not None and a > 0 and a < total:
                    vat_amount = a
                    break
    except (InvalidOperation, TypeError, ValueError, ArithmeticError):
        total = None
        vat_amount = None
    date_parsed = None
    if dates:
        y, mo, d = dates[0]
        date_parsed = f'{y}-{mo:02d}-{d:02d}'
    def _safe_str_amount(a):
        try:
            return str(a) if a is not None else None
        except (InvalidOperation, TypeError):
            return None

    return {
        'invoice_number': _extract_invoice_number(text),
        'supplier': _extract_supplier_simple(text),
        'date': date_parsed,
        'total': _safe_str_amount(total),
        'vat_amount': _safe_str_amount(vat_amount),
        'raw_dates': dates,
        'raw_amounts': [(_safe_str_amount(a), c) for a, c in amounts if _safe_str_amount(a) is not None],
    }


def analyze_document_text(text):
    """
    Analyze document text and return structured fields.
    Uses spaCy if available for NER (org, dates, money); otherwise fallback to rule-based.
    Outputs: invoice_number, supplier, date, total, vat_amount.
    """
    try:
        import spacy
        nlp = spacy.load('en_core_web_sm')
    except Exception:
        return analyze_document_text_simple(text)

    if not (text and text.strip()):
        return {
            'invoice_number': '',
            'supplier': '',
            'date': None,
            'total': None,
            'vat_amount': None,
        }

    doc = nlp(text[:100000])  # limit length
    supplier = ''
    date_vals = []
    for ent in doc.ents:
        if ent.label_ == 'ORG' and not supplier:
            supplier = ent.text
        if ent.label_ in ('DATE', 'TIME'):
            date_vals.append(ent.text)

    # Merge with simple extractions
    simple = analyze_document_text_simple(text)
    if supplier:
        simple['supplier'] = supplier
    if date_vals and not simple.get('date'):
        simple['date'] = date_vals[0][:10] if len(date_vals[0]) >= 10 else date_vals[0]
    return simple
