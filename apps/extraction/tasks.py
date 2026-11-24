# -*- coding: utf-8 -*-
"""
Extraction app - pipeline tasks (run extraction and optionally trigger next steps).
No Celery/Redis: these run synchronously or can be called from API/views.
"""
from apps.documents.models import Document
from apps.documents.services import get_document_for_company, set_document_status
from .services import run_extraction


def run_extraction_for_document(document_id, company):
    """
    Run OCR/PDF extraction for a document. Updates document status.
    Call with company for tenant isolation (document must belong to company).
    Returns: dict with extraction result and updated document status.
    """
    doc = get_document_for_company(document_id, company)
    if not doc:
        return {'success': False, 'error': 'Document not found'}
    set_document_status(doc, Document.STATUS_PROCESSING, '')
    try:
        if not doc.file:
            set_document_status(doc, Document.STATUS_FAILED, 'No file attached')
            return {'success': False, 'error': 'No file attached'}
        extraction = run_extraction(doc.file)
        if extraction.get('error'):
            set_document_status(doc, Document.STATUS_FAILED, extraction['error'])
            return {'success': False, 'error': extraction['error'], 'extraction': extraction}
        set_document_status(doc, Document.STATUS_COMPLETED, '')
        return {'success': True, 'extraction': extraction, 'document': doc}
    except Exception as e:
        set_document_status(doc, Document.STATUS_FAILED, str(e))
        return {'success': False, 'error': str(e)}
