import re
from decimal import Decimal, InvalidOperation
from typing import Optional, Union


def parse_number(value: Union[str, int, float, Decimal]) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    value = re.sub(r'[^\d.-]', '', value)
    if value.count('.') > 1:
        parts = value.split('.')
        value = ''.join(parts[:-1]) + '.' + parts[-1]
    if value.count('-') > 1:
        value = value.replace('-', '')
        value = '-' + value
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


def format_currency(amount: Union[Decimal, float, int], currency: str = 'USD') -> str:
    if amount is None:
        return f"$0.00"
    amount_decimal = parse_number(amount)
    if amount_decimal is None:
        return f"$0.00"
    currency_symbols = {'USD': '$', 'EUR': '€', 'GBP': '£', 'NGN': '₦'}
    symbol = currency_symbols.get(currency, '$')
    return f"{symbol}{amount_decimal:,.2f}"


def format_number(value: Union[Decimal, float, int]) -> str:
    if value is None:
        return "0"
    value_decimal = parse_number(value)
    if value_decimal is None:
        return "0"
    if value_decimal == value_decimal.to_integral():
        return f"{value_decimal:,.0f}"
    return f"{value_decimal:,.2f}"


def sanitize_sku(sku: str) -> str:
    if not sku:
        return ""
    sanitized = re.sub(r'[^a-zA-Z0-9\-_]', '', str(sku))
    return sanitized.upper()


def generate_sku_code(prefix: str = "SKU", length: int = 8) -> str:
    import random
    import string
    random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
    return f"{prefix}-{random_part}"


def validate_email(email: str) -> bool:
    if not email:
        return False
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def validate_url(url: str) -> bool:
    if not url:
        return False
    pattern = r'^https?://(?:[-\w.])+(?:[:\d]+)?(?:/(?:[\w/_.])*(?:\?(?:[\w&=%.])*)?(?:#(?:[\w.])*)?)?$'
    return bool(re.match(pattern, url))


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    if not text or len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def safe_int(value: Union[str, int, float, Decimal], default: int = 0) -> int:
    try:
        if isinstance(value, (int, float, Decimal)):
            return int(value)
        if isinstance(value, str):
            return int(float(value))
        return default
    except (ValueError, TypeError):
        return default


def safe_float(value: Union[str, int, float, Decimal], default: float = 0.0) -> float:
    try:
        if isinstance(value, (int, float, Decimal)):
            return float(value)
        if isinstance(value, str):
            return float(value)
        return default
    except (ValueError, TypeError):
        return default
