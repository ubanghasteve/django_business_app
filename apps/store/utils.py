# -*- coding: utf-8 -*-
"""
Store app utilities.
"""
from decimal import Decimal


def _decimal_safe(value, default=Decimal('0')):
    """Safely convert a value to Decimal, returning default on failure."""
    if value is None:
        return default
    try:
        d = Decimal(str(value))
        return d if not (d.is_nan() or d.is_infinite()) else default
    except Exception:
        return default


def format_currency_store(value, currency_symbol='₦'):
    """Format a decimal value as currency."""
    if value is None:
        value = Decimal('0')
    try:
        return f"{currency_symbol}{float(value):,.2f}"
    except Exception:
        return f"{currency_symbol}0.00"


def format_quantity_store(value):
    """Format a decimal value as quantity with thousands separator."""
    if value is None:
        value = Decimal('0')
    try:
        return f"{int(value):,}"
    except Exception:
        return "0"
