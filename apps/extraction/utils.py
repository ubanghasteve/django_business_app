# -*- coding: utf-8 -*-
"""
Extraction app - utility helpers (file type detection, safe paths).
"""
import os


def get_file_extension(filename):
    """Return lowercased extension without dot."""
    if not filename:
        return ''
    _, ext = os.path.splitext(filename)
    return ext.lstrip('.').lower() if ext else ''


def is_pdf_path(path_or_name):
    """Return True if path/name looks like a PDF."""
    ext = get_file_extension(path_or_name if isinstance(path_or_name, str) else getattr(path_or_name, 'name', ''))
    return ext == 'pdf'


# All image extensions we can OCR with Tesseract (Pillow-supported).
IMAGE_EXTENSIONS = ('png', 'jpg', 'jpeg', 'tiff', 'tif', 'bmp', 'gif', 'webp')

# All document extensions we support (PDF + images).
ALLOWED_DOCUMENT_EXTENSIONS = ('pdf',) + IMAGE_EXTENSIONS


def is_image_path(path_or_name):
    """Return True if path/name looks like an image (for OCR)."""
    ext = get_file_extension(path_or_name if isinstance(path_or_name, str) else getattr(path_or_name, 'name', ''))
    return ext in IMAGE_EXTENSIONS
