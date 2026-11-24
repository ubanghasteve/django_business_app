from django import template
from apps.waybills.utils.quantity_parser import extract_numeric_value

register = template.Library()

@register.filter
def extract_number(text):
    """
    Extract numeric value from text like '500kg' or '300 bags'.
    Returns 0 if text is empty or invalid.
    Usage: {{ row.total_quantity_input|extract_number }}
    """
    if text is None:
        return 0
    return extract_numeric_value(str(text))

@register.filter
def subtract(value, arg):
    """
    Subtract arg from value.
    Usage: {{ value|subtract:arg }}
    """
    try:
        return float(value) - float(arg)
    except (ValueError, TypeError):
        return 0

@register.filter
def multiply(value, arg):
    """
    Multiply value by arg.
    Usage: {{ value|multiply:arg }}
    """
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0

@register.filter
def lookup(dictionary, key):
    """
    Template filter to look up a value in a dictionary by key.
    Usage: {{ dict|lookup:key }}
    """
    if isinstance(dictionary, dict):
        return dictionary.get(key, '')
    return ''

@register.filter
def get_item(dictionary, key):
    """
    Alternative filter for dictionary lookup.
    Usage: {{ dict|get_item:key }}
    """
    if isinstance(dictionary, dict):
        return dictionary.get(key, '')
    return ''

@register.filter
def get_first_key(dictionary, keys_arg):
    """
    Return the first value for the given keys (comma-separated). Uses .get() so missing keys never raise.
    Usage: {{ item.item_data|get_first_key:"product_service,product" }}
    """
    if not isinstance(dictionary, dict):
        return ''
    keys = [k.strip() for k in str(keys_arg).split(',') if k.strip()]
    for key in keys:
        val = dictionary.get(key, '')
        if val is not None:
            return val
    return ''

@register.filter
def pluralize_custom(value, arg="s"):
    """
    Custom pluralize filter.
    Usage: {{ count|pluralize_custom:"item,items" }}
    """
    if "," in arg:
        singular, plural = arg.split(",")
        return singular if value == 1 else plural
    else:
        return "" if value == 1 else arg
