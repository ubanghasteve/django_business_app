from django import template
from apps.core.utils import format_decimal_amount

register = template.Library()


@register.filter
def currency(value):
    """Format currency with commas (Decimal-safe for large amounts)."""
    try:
        return format_decimal_amount(value, 2)
    except Exception:
        return value
