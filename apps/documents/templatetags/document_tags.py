from django import template

register = template.Library()


FILE_ICONS = {
    "pdf": "fas fa-file-pdf",
    "excel": "fas fa-file-excel",
    "image": "fas fa-file-image",
    "word": "fas fa-file-word",
    "csv": "fas fa-file-csv",
    "text": "fas fa-file-alt",
    "other": "fas fa-file",
}

FILE_COLORS = {
    "pdf": "#e74c3c",
    "excel": "#27ae60",
    "image": "#3498db",
    "word": "#2980b9",
    "csv": "#16a085",
    "text": "#7f8c8d",
    "other": "#95a5a6",
}


@register.filter
def file_icon(file_type):
    return FILE_ICONS.get(file_type, FILE_ICONS["other"])


@register.filter
def file_color(file_type):
    return FILE_COLORS.get(file_type, FILE_COLORS["other"])


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
def file_extension(filename):
    if not filename:
        return ""
    import os
    ext = os.path.splitext(str(filename))[1]
    return ext.upper() if ext else ""


@register.filter
def strip(value):
    if value is None:
        return ""
    return str(value).strip()


@register.simple_tag
def document_status_badge_class(status):
    badges = {
        "pending": "bg-secondary",
        "processing": "bg-info",
        "completed": "bg-success",
        "failed": "bg-danger",
    }
    return badges.get(status, "bg-secondary")


@register.simple_tag
def document_file_badge_class(file_type):
    badges = {
        "pdf": "bg-danger",
        "excel": "bg-success",
        "image": "bg-info",
        "word": "bg-primary",
        "csv": "bg-secondary",
        "text": "bg-secondary",
        "other": "bg-secondary",
    }
    return badges.get(file_type, "bg-secondary")
