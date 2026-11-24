# -*- coding: utf-8 -*-
"""
Document services: orchestration and pipeline helpers.
All operations are company-scoped; callers must pass company from request.company.
Also contains helpers for generating visual previews (page snapshots) of documents.
"""
import os
from pathlib import Path

from django.conf import settings

from .models import Document


def get_documents_queryset(company):
    """Return documents for a company (tenant isolation), excluding deleted documents."""
    if not company:
        return Document.objects.none()
    return Document.objects.filter(company=company, is_deleted=False).select_related('uploaded_by').order_by('-created_at')


def get_document_for_company(document_id, company):
    """Get a single document by id if it belongs to company and is not deleted. Else None."""
    if not company:
        return None
    try:
        return Document.objects.get(pk=document_id, company=company, is_deleted=False)
    except Document.DoesNotExist:
        return None


def set_document_status(document, status, error_message=''):
    """Update document processing status. Used by pipeline."""
    document.processing_status = status
    if error_message:
        document.processing_error = error_message
    document.save(update_fields=['processing_status', 'processing_error', 'updated_at'])


def get_document_preview_images(document, regenerate=False):
    """
    Return a list of URLs to page snapshot images for the given document.

    - For PDFs: renders each page to PNG using PyMuPDF (fitz) and stores them under:
        MEDIA_ROOT/doc_previews/<document.id>/page_<n>.png
      The function is idempotent and will re-use existing images unless regenerate=True.
    - For image files: simply returns the original file URL as a single "page".
    """
    if not document or not document.file:
        return []

    # Single-image documents (JPEG/PNG/etc.) can just use the original file.
    name = getattr(document.file, 'name', '') or ''
    lower = name.lower()
    if lower.endswith(('.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp', '.gif', '.webp')):
        try:
            return [document.file.url]
        except Exception:
            return []

    # Only handle PDFs for now for multi-page snapshots.
    if not lower.endswith('.pdf'):
        return []

    media_root = getattr(settings, 'MEDIA_ROOT', None)
    media_url = getattr(settings, 'MEDIA_URL', None)
    if not media_root or not media_url:
        return []

    base_dir = Path(media_root) / 'doc_previews' / str(document.id)
    if not regenerate and base_dir.exists():
        files = sorted(base_dir.glob('page_*.png'))
        if files:
            return [
                f"{media_url.rstrip('/')}/doc_previews/{document.id}/{f.name}"
                for f in files
            ]

    try:
        import fitz  # PyMuPDF
    except ImportError:
        # Preview generation is optional; if PyMuPDF is missing, just skip.
        return []

    # Ensure output directory exists.
    base_dir.mkdir(parents=True, exist_ok=True)

    # Render each page at 150 DPI for a good balance of clarity and size.
    try:
        file_path = getattr(document.file, 'path', None)
        if not file_path or not os.path.isfile(file_path):
            return []
        doc_pdf = fitz.open(file_path)
        image_urls = []
        for page_number in range(len(doc_pdf)):
            page = doc_pdf.load_page(page_number)
            pix = page.get_pixmap(dpi=150, alpha=False)
            out_name = f"page_{page_number + 1}.png"
            out_path = base_dir / out_name
            pix.save(out_path.as_posix())
            image_urls.append(
                f"{media_url.rstrip('/')}/doc_previews/{document.id}/{out_name}"
            )
        doc_pdf.close()
        return image_urls
    except Exception:
        return []


def build_document_structure(text, tables=None):
    """
    Build a simple, layout‑aware structure from extracted text so that
    templates can render headings and paragraphs in a readable way.

    Returns a list of blocks:
        [{'type': 'heading', 'text': str}, {'type': 'paragraph', 'text': str}, ...]
        
    Enhanced with more heading keywords for better accuracy.
    """
    text = (text or '').strip()
    if not text:
        return []

    lines = [ln.rstrip('\n') for ln in text.split('\n')]

    # Expanded domain-specific heading keywords
    heading_keywords = [
        # Invoice/Receipt
        'invoice', 'tax invoice', 'proforma invoice', 'receipt', 'customer copy', 'supplier copy',
        # Statements
        'statement of account', 'account statement', 'bank statement', 'monthly statement',
        # CV/Resume sections
        'summary', 'professional summary', 'profile', 'career profile',
        'objective', 'career objective', 'employment objective',
        'experience', 'work experience', 'professional experience', 'employment history', 'work history',
        'education', 'educational background', 'academic background',
        'skills', 'technical skills', 'core competencies', 'key skills',
        'certifications', 'certificates', 'licenses',
        'projects', 'key projects',
        'languages', 'language skills',
        'interests', 'hobbies',
        'references', 'referees', 'personal details',
        'contact information', 'contact info', 'contact details',
        # Business
        'transaction', 'transactions', 'ledger',
        'balance', 'balance sheet',
        'customer', 'supplier', 'vendor',
        'payment', 'due date', 'terms', 'conditions',
        'total', 'subtotal', 'tax', 'vat', 'gst',
        'bill to', 'ship to',
        # Reports
        'introduction', 'overview', 'executive summary',
        'methodology', 'findings', 'results',
        'discussion', 'conclusion', 'recommendations',
    ]

    def _is_heading(line):
        s = (line or '').strip()
        if len(s) < 2:
            return False
        if len(s) > 150:
            return False
        lower = s.lower()

        # 1) Exact or prefix match on known heading keywords.
        for kw in heading_keywords:
            if lower == kw or lower.startswith(kw + ' '):
                return True
        
        # 2) Check for numbered headings
        import re
        numbered_patterns = [
            r'^\d+\.\s+',  # "1. Introduction"
            r'^\d+\.\d+\.\s+',  # "1.1 Section"
            r'^[IVX]+\.\s+',  # "I. Section"
            r'^\([a-z]\)\s+',  # "(a) item"
        ]
        for pat in numbered_patterns:
            if re.match(pat, s):
                return True

        alpha_chars = [c for c in s if c.isalpha()]
        if not alpha_chars:
            return False
        upper_ratio = sum(1 for c in alpha_chars if c.isupper()) / float(len(alpha_chars))
        
        # Heuristics:
        # - mostly uppercase OR
        # - short Title Case line OR  
        # - line ending with ':' and not containing obvious sentence punctuation
        if upper_ratio >= 0.7:
            return True
        if s.istitle() and len(s.split()) <= 10:
            return True
        if s.endswith(':') and not any(ch in s for ch in ('.', '!', '?')):
            return True
        return False

    blocks = []
    current_para = []

    def _flush_para():
        nonlocal current_para, blocks
        if current_para:
            para_text = ' '.join(seg.strip() for seg in current_para if seg.strip())
            if para_text:
                blocks.append({'type': 'paragraph', 'text': para_text})
        current_para = []

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            _flush_para()
            i += 1
            continue
        if _is_heading(line):
            _flush_para()
            blocks.append({'type': 'heading', 'text': stripped})
            i += 1
            continue
        current_para.append(stripped)
        i += 1

    _flush_para()
    return blocks
