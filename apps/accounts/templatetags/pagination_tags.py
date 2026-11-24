from django import template

register = template.Library()


@register.filter(name='make_range')
def make_range(start, end):
    """
    Create a range from start to end.
    Usage: {% for i in start|make_range:end %}
    """
    try:
        start = int(start)
        end = int(end)
        return range(start, end)
    except (ValueError, TypeError):
        return range(0)


@register.simple_tag
def serial_number(counter, page, per_page):
    """
    Calculate serial number based on pagination.
    Usage: {% serial_number forloop.counter page per_page %}
    """
    try:
        counter = int(counter)
        page = int(page)
        per_page = int(per_page)
        return (page - 1) * per_page + counter
    except (ValueError, TypeError):
        return counter
