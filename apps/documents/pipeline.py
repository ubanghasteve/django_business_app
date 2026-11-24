# -*- coding: utf-8 -*-
"""
Document processing pipeline: after upload:
1. Document saved
2. OCR extraction runs
3. Text analyzed by NLP
4. Financial fields extracted -> transactions saved
5. Tax recalculated
6. Store extraction preview and AI result on document for detail view
All company-scoped. No Celery/Redis: runs synchronously.
"""
from datetime import date
import calendar
import json
from decimal import InvalidOperation, DecimalException

from apps.documents.models import Document, DocumentPage
from apps.documents.services import get_document_for_company, set_document_status
from apps.extraction.services import run_extraction
from apps.ai_engine.services import analyze_document_text_service
from apps.finance_engine.services import transaction_extraction_service, transaction_extraction_from_statement
from apps.tax_engine.services import compute_tax


def _period_bounds(period_type='monthly', year=None, month=None):
    today = date.today()
    y = year or today.year
    m = month or today.month
    if period_type == 'yearly':
        return date(y, 1, 1), date(y, 12, 31)
    if period_type == 'quarterly':
        q = (m - 1) // 3 + 1
        start_m = (q - 1) * 3 + 1
        end_m = q * 3
        _, end_d = calendar.monthrange(y, end_m)
        return date(y, start_m, 1), date(y, end_m, end_d)
    _, last_d = calendar.monthrange(y, m)
    return date(y, m, 1), date(y, m, last_d)


def infer_document_type(text, ai_result):
    """
    Auto-detect document type from extracted text and AI result.
    Returns one of Document.DOCUMENT_TYPE_* so the system can classify without user input.
    """
    r = ai_result or {}
    if r.get('statement_type') == 'bank_statement':
        return Document.DOCUMENT_TYPE_BANK_STATEMENT
    if r.get('statement_type') == 'accounting_statement':
        return Document.DOCUMENT_TYPE_ACCOUNTING_STATEMENT

    t = (text or '').lower()
    has_invoice_number = bool((r.get('invoice_number') or '').strip())
    has_total = bool((r.get('total') or '').strip()) or bool((r.get('vat_amount') or '').strip())
    has_supplier = bool((r.get('supplier') or '').strip())

    # Strong signals from content
    if 'tax return' in t or 'vat return' in t or 'tax form' in t or 'tax assessment' in t:
        return Document.DOCUMENT_TYPE_TAX_FORM
    if 'receipt' in t and ('thank you' in t or 'payment received' in t or 'paid' in t):
        return Document.DOCUMENT_TYPE_RECEIPT
    if 'invoice' in t or 'inv no' in t or 'inv. no' in t or 'bill to' in t:
        return Document.DOCUMENT_TYPE_INVOICE
    if has_invoice_number and (has_total or has_supplier):
        return Document.DOCUMENT_TYPE_INVOICE
    if 'receipt' in t or 'receipt no' in t:
        return Document.DOCUMENT_TYPE_RECEIPT

    return Document.DOCUMENT_TYPE_OTHER


def run_pipeline(document_id, company):
    """
    Run full pipeline for a document: extraction -> AI -> finance -> tax.
    Returns: dict with success, message, extraction, ai_result, transactions_created.
    """
    doc = get_document_for_company(document_id, company)
    if not doc:
        return {'success': False, 'message': 'Document not found'}
    set_document_status(doc, Document.STATUS_PROCESSING, '')
    try:
        if not doc.file:
            set_document_status(doc, Document.STATUS_FAILED, 'No file attached')
            return {'success': False, 'message': 'No file attached'}
        # 2. OCR extraction
        extraction = run_extraction(doc.file)
        if extraction.get('error'):
            set_document_status(doc, Document.STATUS_FAILED, extraction['error'])
            return {'success': False, 'message': extraction['error'], 'extraction': extraction}
        text = extraction.get('text', '')
        tables = extraction.get('tables') or []
        layout_lines = extraction.get('layout_lines') or []
        pages = extraction.get('pages') or []
        
        # Log extraction details for debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Document {doc.id}: Extracted {len(text)} chars, {len(tables)} tables, {len(layout_lines)} layout lines")
        for i, table in enumerate(tables):
            logger.info(f"  Table {i+1}: {len(table)} rows")
        
        for table in tables:
            for row in table:
                for cell in row:
                    if cell and isinstance(cell, str) and cell.strip():
                        text = text + '\n' + cell.strip()
        text = (text or '').strip()

        # Persist per-page content so the UI can paginate large documents and
        # users can see exactly which content belongs to which page.
        try:
            DocumentPage.objects.filter(document=doc).delete()
            page_objects = []
            if pages:
                for p in pages:
                    page_number = int(p.get('page_number') or 1)
                    page_text = (p.get('text') or '').strip()
                    page_tables = p.get('tables') or []
                    try:
                        tables_json = json.dumps(page_tables)
                    except TypeError:
                        tables_json = ''
                    page_objects.append(DocumentPage(
                        document=doc,
                        page_number=page_number,
                        text=page_text,
                        tables_json=tables_json,
                    ))
            else:
                # Fallback: single logical page with all text/tables when the
                # extractor did not provide per-page information.
                try:
                    tables_json = json.dumps(tables or [])
                except TypeError:
                    tables_json = ''
                page_objects.append(DocumentPage(
                    document=doc,
                    page_number=1,
                    text=text,
                    tables_json=tables_json,
                ))
            if page_objects:
                DocumentPage.objects.bulk_create(page_objects)
        except Exception:
            # Per-page persistence should never break the main pipeline; errors
            # here are swallowed so extraction/AI/tax can still succeed.
            pass
        # 3. Smart analyze: layout-aware, auto-detect type, validate (pass filename for statement hint)
        document_name = getattr(doc.file, 'name', '') or ''
        ai_result = analyze_document_text_service(
            text, tables=tables, layout_lines=layout_lines, document_name=document_name
        )
        # 4. Financial transactions (statement lines or invoice totals)
        if ai_result.get('transactions'):
            created = transaction_extraction_from_statement(company, doc, ai_result)
        else:
            created = transaction_extraction_service(company, doc, ai_result)
        # 5. Tax recalculated (current month)
        period_start, period_end = _period_bounds('monthly')
        compute_tax(company, 'monthly', period_start, period_end)
        # 6. Auto-detect document type and store for detail view.
        # Store the full extracted text instead of a short preview so that
        # downstream views can reconstruct the document layout (headings,
        # paragraphs, etc.) without losing any content.
        doc.document_type = infer_document_type(text, ai_result)
        doc.extracted_text_preview = (text or '')
        
        # Store complete extraction data including raw_json for full fidelity
        raw_json = extraction.get('raw_json', '{}')
        if raw_json:
            try:
                # If raw_json is a string, parse it; otherwise use as-is
                if isinstance(raw_json, str):
                    raw_data = json.loads(raw_json)
                else:
                    raw_data = raw_json
                
                # Add complete text and tables to raw_data for complete preservation
                raw_data['complete_text'] = text
                raw_data['complete_tables'] = tables
                raw_data['complete_layout_lines'] = layout_lines
                raw_data['extraction_method'] = raw_data.get('type', 'unknown')
                
                # Store as complete_extraction_json for full document view
                doc.complete_extraction_json = json.dumps(raw_data)
            except:
                doc.complete_extraction_json = json.dumps({
                    'complete_text': text,
                    'complete_tables': tables,
                    'complete_layout_lines': layout_lines,
                    'error': 'Could not parse raw extraction'
                })
        else:
            doc.complete_extraction_json = json.dumps({
                'complete_text': text,
                'complete_tables': tables,
                'complete_layout_lines': layout_lines,
            })
        
        doc.ai_result_json = json.dumps(ai_result) if ai_result else ''
        # Store raw tables so we can display the exact extracted grid layout on the detail page.
        try:
            doc.extracted_tables_json = json.dumps(tables or [])
        except TypeError:
            doc.extracted_tables_json = ''
        doc.processing_status = Document.STATUS_COMPLETED
        doc.processing_error = ''
        doc.save(update_fields=['document_type', 'extracted_text_preview', 'ai_result_json', 'extracted_tables_json', 'processing_status', 'processing_error', 'updated_at', 'complete_extraction_json'])
        return {
            'success': True,
            'message': 'Pipeline completed',
            'extraction': extraction,
            'ai_result': ai_result,
            'transactions_created': len(created),
        }
    except (InvalidOperation, DecimalException, ArithmeticError) as e:
        set_document_status(
            doc, Document.STATUS_FAILED,
            'Invalid number in document. The system could not parse some amounts; we\'ve improved handling—please try Re-process.'
        )
        return {'success': False, 'message': 'Invalid number in document. Please try Re-process.'}
    except Exception as e:
        err_msg = str(e).strip()
        if not err_msg or err_msg.startswith('<class ') or 'InvalidOperation' in err_msg:
            err_msg = 'Processing error. If the document has unusual number formats, try Re-process.'
        set_document_status(doc, Document.STATUS_FAILED, err_msg)
        return {'success': False, 'message': err_msg}
