# -*- coding: utf-8 -*-
"""
AI Engine - document understanding service.
Layout-aware: uses layout_lines and tables to understand document structure,
dispatches to the right extractor, and validates for accurate computation.
"""
from .smart_analyzer import analyze_document_smart


def analyze_document_text_service(text, tables=None, layout_lines=None, document_name=None):
    """
    Analyze document with full context: text, tables, layout (line order), and optional filename.
    Automatically detects document type from layout and content; uses document_name (e.g. filename)
    to treat "statement" in name as bank statement when content is ambiguous.
    """
    return analyze_document_smart(
        text or '',
        tables=tables or [],
        layout_lines=layout_lines or [],
        document_name=document_name or '',
    )
