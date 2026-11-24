from django import template

register = template.Library()


FILE_ICONS = {
    "pdf": "fas fa-file-pdf",
    "excel": "fas fa-file-excel",
    "image": "fas fa-file-image",
    "word": "fas fa-file-word",
    "csv": "fas fa-file-csv",
    "text": "fas fa-file-alt",
    "zip": "fas fa-file-archive",
    "other": "fas fa-file",
}

FILE_COLORS = {
    "pdf": "#e74c3c",
    "excel": "#27ae60",
    "image": "#3498db",
    "word": "#2980b9",
    "csv": "#16a085",
    "text": "#7f8c8d",
    "zip": "#f39c12",
    "other": "#95a5a6",
}


@register.filter
def file_icon(file_type):
    return FILE_ICONS.get(file_type, FILE_ICONS["other"])


@register.filter
def file_color(file_type):
    return FILE_COLORS.get(file_type, FILE_COLORS["other"])


@register.filter
def file_period(payroll_file):
    if payroll_file.month and payroll_file.year:
        from datetime import date
        try:
            d = date(payroll_file.year, payroll_file.month, 1)
            return d.strftime("%B %Y")
        except:
            pass
    return "N/A"


@register.filter
def friendly_size(bytes_value):
    if bytes_value is None:
        return "0 B"
    try:
        bytes_value = int(bytes_value)
    except (ValueError, TypeError):
        return "0 B"
    if bytes_value < 1024:
        return f"{bytes_value} B"
    elif bytes_value < 1024 * 1024:
        return f"{bytes_value / 1024:.1f} KB"
    elif bytes_value < 1024 * 1024 * 1024:
        return f"{bytes_value / (1024 * 1024):.1f} MB"
    return f"{bytes_value / (1024 * 1024 * 1024):.1f} GB"


@register.filter
def split(value, delimiter=","):
    if not value:
        return []
    return str(value).split(delimiter)


@register.filter
def get_item(dictionary, key):
    if dictionary is None:
        return ""
    return dictionary.get(key, "")


@register.filter
def add(value, arg):
    try:
        return int(value) + int(arg)
    except (ValueError, TypeError):
        return value


@register.filter
def strip(value):
    if value is None:
        return ""
    return str(value).strip()


@register.filter
def file_extension(filename):
    """Extract file extension from filename."""
    if not filename:
        return ""
    import os
    ext = os.path.splitext(str(filename))[1]
    return ext.upper() if ext else ""


@register.filter
def get_row_item(row_data, key):
    if row_data is None:
        return ""
    if isinstance(row_data, dict):
        return row_data.get(key, "")
    return ""


@register.simple_tag
def payroll_file_badge_class(file_type):
    badges = {
        "pdf": "bg-danger",
        "excel": "bg-success",
        "image": "bg-info",
        "word": "bg-primary",
        "csv": "bg-secondary",
        "text": "bg-secondary",
        "zip": "bg-warning",
        "other": "bg-secondary",
    }
    return badges.get(file_type, "bg-secondary")


@register.filter
def status_badge_class(status):
    classes = {
        "draft": "bg-warning",
        "completed": "bg-success",
        "archived": "bg-secondary",
        "approved": "bg-success",
        "paid": "bg-primary",
        "pending": "bg-warning",
    }
    return classes.get(status, "bg-secondary")
