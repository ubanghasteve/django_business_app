# -*- coding: utf-8 -*-
from django import template
from django.utils.safestring import mark_safe
from decimal import Decimal

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Get item from dictionary by key."""
    if dictionary is None:
        return ''
    return dictionary.get(key, '')


@register.filter
def split(value, arg):
    """Split string by delimiter."""
    if value is None:
        return []
    return str(value).split(arg)


@register.filter
def strip(value):
    """Strip whitespace from value."""
    if value is None:
        return ''
    return str(value).strip()


@register.filter
def format_currency(value, currency_symbol='₦'):
    """Format decimal as currency."""
    if value is None:
        value = Decimal('0')
    try:
        return f"{currency_symbol}{float(value):,.2f}"
    except Exception:
        return f"{currency_symbol}0.00"


@register.filter
def format_number(value):
    """Format number with thousands separator."""
    if value is None:
        return '0'
    try:
        return f"{int(value):,}"
    except Exception:
        try:
            return f"{float(value):,.2f}"
        except Exception:
            return str(value)


@register.filter
def yes_no(value):
    """Convert boolean to Yes/No string."""
    return 'Yes' if value else 'No'


@register.filter
def check_mark(value):
    """Convert boolean to checkmark/X."""
    return '✓' if value else '✗'


@register.filter
def get_field(form, field_name):
    """Get form field by name."""
    if form is None:
        return ''
    return form.fields.get(field_name, '')


@register.filter
def get_field_id(form, field_name):
    """Get form field ID."""
    if form is None:
        return ''
    field = form.fields.get(field_name)
    if field:
        return form[field_name].id_for_label
    return ''


@register.filter
def get_field_errors(form, field_name):
    """Get form field errors."""
    if form is None:
        return []
    if field_name not in form.errors:
        return []
    return form.errors[field_name]


@register.filter
def has_field(form, field_name):
    """Check if form has a field."""
    if form is None:
        return False
    return field_name in form.fields


@register.filter
def multiply(value, arg):
    """Multiply two numbers."""
    try:
        return float(value) * float(arg)
    except Exception:
        return 0


@register.filter
def get_field_value(item, field_name):
    """Get field value from model instance."""
    if item is None:
        return ''
    return getattr(item, field_name, '')


@register.filter
def serial_number(item, forloop_counter):
    """Generate serial number."""
    return forloop_counter


@register.filter
def format_currency_dynamic(value, request):
    """Format currency dynamically based on request."""
    currency_symbol = '₦'
    if request and hasattr(request, 'session'):
        currency_symbol = request.session.get('currency_symbol', '₦')
    return format_currency(value, currency_symbol)


@register.filter
def format_currency_with_symbol(context, value):
    """Format currency with symbol from context."""
    currency_symbol = '₦'
    if context and isinstance(context, dict):
        currency_symbol = context.get('user_currency_symbol', '₦')
    return format_currency(value, currency_symbol)


@register.simple_tag
def store_get_item(dictionary, key):
    """Get item from dictionary as a template tag."""
    if dictionary is None:
        return ''
    return dictionary.get(key, '')
