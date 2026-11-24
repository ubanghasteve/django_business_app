from django import template
from django.conf import settings
import json
register = template.Library()

@register.filter
def get_custom_field(fields, col):
    return fields.get(f'custom_{col}')

@register.filter
def json_loads(value):
    try:
        return json.loads(value)
    except Exception:
        return []

@register.filter
def get_item(dictionary, key):
    if isinstance(dictionary, dict):
        return dictionary.get(key, '')
    return ''

@register.filter
def get_form_field(form, field_name):
    """Get a form field by name"""
    if hasattr(form, 'fields') and field_name in form.fields:
        return form[field_name]
    return None

@register.filter
def currency_format_with_symbol(value, company_profile=None):
    """
    Format a value as currency using the company profile's currency symbol
    This is a fallback filter to ensure currency formatting works
    
    Usage:
    {{ amount|currency_format_with_symbol:company_profile }}
    """
    if value is None:
        value = 0
    
    try:
        # Get currency symbol
        if company_profile and hasattr(company_profile, 'currency_symbol'):
            symbol = company_profile.currency_symbol
        else:
            symbol = getattr(settings, 'DEFAULT_CURRENCY_SYMBOL', '$')
        
        # Format the currency
        formatted_amount = f"{float(value):,.2f}"
        return f"{symbol}{formatted_amount}"
    except Exception:
        # Ultimate fallback
        try:
            return f"${float(value):,.2f}"
        except:
            return str(value) 