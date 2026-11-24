# -*- coding: utf-8 -*-
"""
Documents app views. All querysets filtered by request.company (tenant isolation).
"""
import json
import os
import mimetypes
import urllib.parse
import base64
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, FileResponse, Http404
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.views.decorators.cache import never_cache

from apps.core.utils import get_company_profile_for_user
from apps.core.permissions import company_admin_or_permission_required
from .models import Document, DocumentPage
from .forms import DocumentUploadForm, ALLOWED_EXTENSIONS, MAX_UPLOAD_BYTES
from .services import get_documents_queryset, get_document_for_company, get_document_preview_images, build_document_structure
from .pipeline import _period_bounds, infer_document_type
from .exports import export_tables_to_excel
from .file_processor import SmartFileProcessor


def _company(request):
    """Current company for tenant isolation (request.company set by middleware)."""
    return getattr(request, 'company', None) or get_company_profile_for_user(request.user, request)


@login_required
@company_admin_or_permission_required('documents.view_document', raise_exception=True)
@require_GET
def document_list_view(request):
    """List documents for the current company. Pagination and filters: document_type, processing_status."""
    company = _company(request)
    if not company:
        return redirect('dashboard/landing/')
    qs = get_documents_queryset(company)
    # Filters (company already applied in get_documents_queryset)
    doc_type = request.GET.get('document_type', '').strip()
    if doc_type and doc_type in dict(Document.DOCUMENT_TYPE_CHOICES):
        qs = qs.filter(document_type=doc_type)
    status = request.GET.get('processing_status', '').strip()
    if status and status in dict(Document.STATUS_CHOICES):
        qs = qs.filter(processing_status=status)
    paginator = Paginator(qs, 20)
    page_number = request.GET.get('page', 1)
    try:
        page = paginator.page(int(page_number))
    except (ValueError, TypeError):
        page = paginator.page(1)
    return render(request, 'documents/document_list.html', {
        'documents': page,
        'page_obj': page,
        'paginator': paginator,
        'document_type_filter': doc_type,
        'status_filter': status,
        'document_type_choices': Document.DOCUMENT_TYPE_CHOICES,
        'status_choices': Document.STATUS_CHOICES,
    })


@login_required
@company_admin_or_permission_required('documents.add_document', raise_exception=True)
@require_http_methods(['GET', 'POST'])
def document_upload_view(request):
    """Upload a new document. POST: save and redirect; form can be submitted via AJAX (API handles that)."""
    company = _company(request)
    if not company:
        return redirect('dashboard/landing/')
    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accepts('application/json')
        try:
            files = request.FILES.getlist('file') or []

            # Helper: merge multiple image files into a single PDF for one Document.
            def _create_document_from_images(file_list):
                if not file_list:
                    raise ValidationError('Please select at least one image.')
                # Validate extensions and sizes.
                total_size = 0
                image_files = []
                for f in file_list:
                    name = getattr(f, 'name', '') or ''
                    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
                    if ext not in ALLOWED_EXTENSIONS or ext == 'pdf':
                        raise ValidationError('Multiple upload is only supported for image files (PNG, JPG, JPEG, TIFF, BMP, GIF, WebP).')
                    if f.size > MAX_UPLOAD_BYTES:
                        raise ValidationError(f'Each image must not exceed {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.')
                    total_size += getattr(f, 'size', 0) or 0
                    image_files.append(f)
                try:
                    from PIL import Image
                except ImportError:
                    raise ValidationError('Pillow (PIL) is required to combine images. Install it with "pip install Pillow".')
                from io import BytesIO
                from django.core.files.base import ContentFile

                pil_images = []
                for f in image_files:
                    img = Image.open(f)
                    if img.mode in ('RGBA', 'LA'):
                        img = img.convert('RGB')
                    elif img.mode != 'RGB':
                        img = img.convert('RGB')
                    pil_images.append(img)
                if not pil_images:
                    raise ValidationError('No valid images were provided.')
                buffer = BytesIO()
                first, rest = pil_images[0], pil_images[1:]
                first.save(buffer, format='PDF', save_all=bool(rest), append_images=rest)
                pdf_bytes = buffer.getvalue()
                buffer.close()
                content = ContentFile(pdf_bytes)
                base_name = getattr(image_files[0], 'name', 'statement').rsplit('.', 1)[0]
                merged_name = f'{base_name}_merged.pdf'

                doc = Document(company=company, uploaded_by=request.user)
                doc.file.save(merged_name, content, save=True)
                doc.file_type = 'application/pdf'
                if not doc.document_type:
                    doc.document_type = Document.DOCUMENT_TYPE_OTHER
                doc.save()
                return doc

            # If multiple files selected, treat them as pages of one logical document.
            if len(files) > 1:
                doc = _create_document_from_images(files)
            else:
                # Fallback to normal single-file form handling (PDF or single image).
                form = DocumentUploadForm(request.POST, request.FILES)
                if not form.is_valid():
                    if is_ajax:
                        return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)
                    raise ValidationError(form.errors.as_text())
                doc = form.save(commit=False)
                doc.company = company
                doc.uploaded_by = request.user
                uploaded = files[0] if files else request.FILES.get('file')
                doc.file_type = getattr(uploaded, 'content_type', '') or ''
                doc.save()

            # Run pipeline synchronously so SQLite is not locked by background threads.
            # This avoids "database is locked" errors when using SQLite in development.
            from apps.core.models import CompanyProfile
            from .pipeline import run_pipeline
            c = CompanyProfile.objects.get(pk=company.pk)
            run_pipeline(doc.id, c)
            if is_ajax:
                return JsonResponse({
                    'status': 'success',
                    'message': 'Document uploaded. Processing in background—you can view the document now.',
                    'id': doc.id,
                    'redirect_url': doc.get_absolute_url(),
                })
            return redirect('documents:detail', pk=doc.pk)
        except Exception as e:
            if is_ajax:
                return JsonResponse({
                    'status': 'error',
                    'message': getattr(e, 'message', str(e)) or 'Upload or processing failed. Check the file and try again.',
                }, status=500)
            raise
    else:
        form = DocumentUploadForm()
    
    from datetime import date
    current_year = date.today().year
    years = list(range(current_year - 5, current_year + 1))
    
    return render(request, 'documents/document_upload.html', {
        'form': form,
        'years': years,
    })


@login_required
@company_admin_or_permission_required('documents.view_document', raise_exception=True)
@require_GET
def document_detail_view(request, pk):
    """Document detail. Company-scoped."""
    company = _company(request)
    if not company:
        return redirect('dashboard/landing/')
    doc = get_document_for_company(pk, company)
    if not doc:
        messages.warning(request, 'Document not found.')
        return redirect('documents:list')
    ai_result = {}
    if doc.ai_result_json:
        try:
            ai_result = json.loads(doc.ai_result_json)
            if not isinstance(ai_result, dict):
                ai_result = {}
        except (json.JSONDecodeError, TypeError):
            pass
    raw_tables = []
    if getattr(doc, 'extracted_tables_json', ''):
        try:
            raw_tables = json.loads(doc.extracted_tables_json) or []
        except (json.JSONDecodeError, TypeError):
            raw_tables = []
    
    # Also try to get tables from complete extraction
    complete_extraction = {}
    if getattr(doc, 'complete_extraction_json', ''):
        try:
            complete_extraction = json.loads(doc.complete_extraction_json) or {}
        except (json.JSONDecodeError, TypeError):
            complete_extraction = {}
    
    # If no raw tables but we have complete tables, use those
    if not raw_tables and complete_extraction.get('complete_tables'):
        raw_tables = complete_extraction['complete_tables']
    
    # Build a structured view of the full extracted text so the template can
    # render headings and paragraphs in a layout‑aware way.
    structured_blocks = build_document_structure(doc.extracted_text_preview)
    # Raw layout lines: one line per logical line from the extracted text,
    # used by the "Raw layout view" so users can visually confirm that no
    # content was skipped or truncated by the extractor.
    raw_layout_lines = [
        ln.strip()
        for ln in (doc.extracted_text_preview or '').split('\n')
        if ln.strip()
    ]
    # Page-aware view: fetch per-page records so very large documents can be
    # browsed page by page. We paginate at one page per view.
    pages_qs = DocumentPage.objects.filter(document=doc).order_by('page_number')
    page_param = request.GET.get('page', '1')
    try:
        current_page_number = int(page_param)
    except (TypeError, ValueError):
        current_page_number = 1
    page_paginator = Paginator(pages_qs, 1)
    try:
        page_obj = page_paginator.page(current_page_number)
    except Exception:
        page_obj = page_paginator.page(1)
    current_page = page_obj.object_list[0] if page_obj.object_list else None
    # Raw layout lines: one line per logical line from the extracted text,
    # used by the "Raw layout view" so users can visually confirm that no
    # content was skipped or truncated by the extractor.
    raw_layout_lines = [
        ln.strip()
        for ln in (doc.extracted_text_preview or '').split('\n')
        if ln.strip()
    ]
    
    # Complete extraction data for full fidelity display
    complete_extraction = {}
    if getattr(doc, 'complete_extraction_json', ''):
        try:
            complete_extraction = json.loads(doc.complete_extraction_json) or {}
        except (json.JSONDecodeError, TypeError):
            complete_extraction = {}
    
    from apps.finance_engine.models import FinancialTransaction
    transactions = list(FinancialTransaction.objects.filter(company=company, document=doc).order_by('transaction_type', 'id'))
    # Visual page snapshots (PDF/image preview)
    preview_images = get_document_preview_images(doc)
    return render(request, 'documents/document_detail.html', {
        'document': doc,
        'ai_result': ai_result,
        'transactions': transactions,
        'complete_extraction': complete_extraction,
        'raw_tables': raw_tables,
        'preview_images': preview_images,
        'structured_blocks': structured_blocks,
        'raw_layout_lines': raw_layout_lines,
        'page_obj': page_obj,
        'current_page': current_page,
    })


@login_required
@company_admin_or_permission_required('documents.view_document', raise_exception=True)
@require_GET
def document_contents_view(request, pk):
    """
    Dedicated page for browsing all extracted contents (headings + paragraphs)
    with pagination. Uses the rich structure from AI Engine when available,
    and falls back to the layout-aware helper for older documents.
    
    Enhanced to use complete extraction data for maximum accuracy.
    """
    company = _company(request)
    if not company:
        return redirect('dashboard/landing/')
    doc = get_document_for_company(pk, company)
    if not doc:
        messages.warning(request, 'Document not found.')
        return redirect('documents:list')

    ai_result = {}
    if doc.ai_result_json:
        try:
            ai_result = json.loads(doc.ai_result_json)
            if not isinstance(ai_result, dict):
                ai_result = {}
        except (json.JSONDecodeError, TypeError):
            ai_result = {}

    # Try to use complete extraction data first for best accuracy
    complete_extraction = {}
    if getattr(doc, 'complete_extraction_json', ''):
        try:
            complete_extraction = json.loads(doc.complete_extraction_json) or {}
        except (json.JSONDecodeError, TypeError):
            complete_extraction = {}

    # Use complete extraction text if available, otherwise fall back
    text_for_structure = complete_extraction.get('complete_text', '') or doc.extracted_text_preview or ''
    
    # Prefer the new structure from AI Engine (paragraphs + headings with positions).
    structure = ai_result.get('structure') if isinstance(ai_result, dict) else None
    paragraphs = []
    headings_outline = []

    if isinstance(structure, dict) and isinstance(structure.get('paragraphs'), list):
        # Use AI structure if available
        for p in structure['paragraphs']:
            text = (p.get('text') or '').strip()
            if not text:
                continue
            idx = int(p.get('index', len(paragraphs)))
            is_heading = bool(p.get('is_heading'))
            level = int(p.get('heading_level', 3) or 3)
            start = int(p.get('char_start', 0) or 0)
            end = int(p.get('char_end', start + len(text)))
            para = {
                'index': idx,
                'text': text,
                'is_heading': is_heading,
                'heading_level': level,
                'char_start': start,
                'char_end': end,
            }
            paragraphs.append(para)
            if is_heading:
                headings_outline.append({
                    'title': text,
                    'index': idx,
                    'level': level,
                })
    else:
        # Fallback: use the enhanced structure builder with complete text
        # Try to get layout lines from complete extraction
        layout_lines = complete_extraction.get('complete_layout_lines', [])
        
        if layout_lines:
            # Use layout lines for better structure
            for idx, line in enumerate(layout_lines):
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                
                # Use the structure analyzer for this line
                from apps.ai_engine.structure_analyzer import analyze_document_structure
                
                # Check if this looks like a heading
                is_heading = False
                level = 3
                
                # Simple heuristics for standalone lines
                if line_stripped.isupper() and len(line_stripped.split()) <= 8:
                    is_heading = True
                    level = 1
                elif line_stripped.istitle() and len(line_stripped.split()) <= 8:
                    is_heading = True
                    level = 2
                elif len(line_stripped.split()) <= 6 and any(c.isupper() for c in line_stripped):
                    # Check if mostly uppercase
                    upper_count = sum(1 for c in line_stripped if c.isupper())
                    alpha_count = sum(1 for c in line_stripped if c.isalpha())
                    if alpha_count > 0 and upper_count / alpha_count >= 0.6:
                        is_heading = True
                        level = 2
                
                para = {
                    'index': idx,
                    'text': line_stripped,
                    'is_heading': is_heading,
                    'heading_level': level,
                    'char_start': idx * 100,  # Approximate
                    'char_end': idx * 100 + len(line_stripped),
                }
                paragraphs.append(para)
                if is_heading:
                    headings_outline.append({
                        'title': line_stripped,
                        'index': idx,
                        'level': level,
                    })
        else:
            # Final fallback to basic structure builder
            structured_blocks = build_document_structure(text_for_structure)
            for idx, block in enumerate(structured_blocks):
                text = (block.get('text') or '').strip()
                if not text:
                    continue
                is_heading = block.get('type') == 'heading'
                level = 1 if is_heading else 3
                para = {
                    'index': idx,
                    'text': text,
                    'is_heading': is_heading,
                    'heading_level': level,
                    'char_start': 0,
                    'char_end': 0,
                }
                paragraphs.append(para)
                if is_heading:
                    headings_outline.append({
                        'title': text,
                        'index': idx,
                        'level': level,
                    })

    # Increase items per page for better viewing
    paginator = Paginator(paragraphs, 50)
    page_number = request.GET.get('page', '1')
    try:
        page_obj = paginator.page(int(page_number))
    except Exception:
        page_obj = paginator.page(1)

    return render(request, 'documents/document_contents.html', {
        'document': doc,
        'paragraph_page': page_obj,
        'page_obj': page_obj,
        'headings_outline': headings_outline,
        'total_items': len(paragraphs),
        'complete_extraction': complete_extraction,
    })


@login_required
@company_admin_or_permission_required('documents.change_document', raise_exception=True)
@require_POST
def document_update_tables_view(request, pk):
    """
    Save edited tables for a document. Expects a JSON string in tables_json
    representing list[list[list[str]]].
    """
    company = _company(request)
    if not company:
        return redirect('dashboard/landing/')
    doc = get_document_for_company(pk, company)
    if not doc:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'status': 'error', 'message': 'Document not found'}, status=404)
        messages.warning(request, 'Document not found.')
        return redirect('documents:list')
    tables_json = request.POST.get('tables_json', '').strip()
    if not tables_json:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'status': 'error', 'message': 'No table data submitted'}, status=400)
        messages.warning(request, 'No table data submitted.')
        return redirect('documents:detail', pk=pk)
    try:
        tables = json.loads(tables_json)
        if not isinstance(tables, list):
            raise ValueError('Invalid tables format')
        doc.cleaned_tables_json = json.dumps(tables)
        doc.save(update_fields=['cleaned_tables_json', 'updated_at'])
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'status': 'error', 'message': 'Invalid table JSON'}, status=400)
        messages.error(request, 'Invalid table data. Changes were not saved.')
        return redirect('documents:detail', pk=pk)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'status': 'success'})
    messages.success(request, 'Edited tables saved.')
    return redirect('documents:detail', pk=pk)


@login_required
@company_admin_or_permission_required('documents.change_document', raise_exception=True)
@require_POST
def document_reprocess_from_tables_view(request, pk):
    """
    Re-run AI/finance/tax using the saved tables (cleaned if present, else raw).
    Does NOT re-run OCR; it trusts the edited grid.
    """
    company = _company(request)
    if not company:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'status': 'error', 'message': 'No company'}, status=403)
        return redirect('dashboard/landing/')
    doc = get_document_for_company(pk, company)
    if not doc:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'status': 'error', 'message': 'Document not found'}, status=404)
        return redirect('documents:list')
    # Choose tables: cleaned first, then raw.
    tables = []
    src = ''
    if getattr(doc, 'cleaned_tables_json', ''):
        try:
            tables = json.loads(doc.cleaned_tables_json) or []
            src = 'cleaned'
        except (json.JSONDecodeError, TypeError):
            tables = []
    if not tables and getattr(doc, 'extracted_tables_json', ''):
        try:
            tables = json.loads(doc.extracted_tables_json) or []
            src = 'raw'
        except (json.JSONDecodeError, TypeError):
            tables = []
    text = (doc.extracted_text_preview or '').strip()
    layout_lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
    from apps.ai_engine.services import analyze_document_text_service
    ai_result = analyze_document_text_service(
        text,
        tables=tables,
        layout_lines=layout_lines,
        document_name=getattr(doc.file, 'name', '') or '',
    )
    # Replace existing transactions for this document.
    from apps.finance_engine.models import FinancialTransaction
    from apps.finance_engine.services import transaction_extraction_service, transaction_extraction_from_statement
    deleted, _ = FinancialTransaction.objects.filter(company=company, document=doc).delete()
    if ai_result.get('transactions'):
        created = transaction_extraction_from_statement(company, doc, ai_result)
    else:
        created = transaction_extraction_service(company, doc, ai_result)
    # Recompute tax for current month.
    from apps.tax_engine.services import compute_tax
    period_start, period_end = _period_bounds('monthly')
    compute_tax(company, 'monthly', period_start, period_end)
    # Store AI result back on document.
    doc.document_type = infer_document_type(text, ai_result)
    doc.ai_result_json = json.dumps(ai_result) if ai_result else ''
    doc.processing_status = Document.STATUS_COMPLETED
    doc.processing_error = ''
    doc.save(update_fields=['document_type', 'ai_result_json', 'processing_status', 'processing_error', 'updated_at'])
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'status': 'success',
            'tables_source': src or 'none',
            'transactions_created': len(created),
        })
    messages.success(request, f'Re-processed from {src or "saved"} tables. {len(created)} transactions created.')
    return redirect('documents:detail', pk=pk)


@login_required
@company_admin_or_permission_required('documents.view_document', raise_exception=True)
@require_GET
def document_export_tables_excel_view(request, pk):
    """
    Export this document's tables (cleaned if present, else raw) to an Excel file.
    """
    company = _company(request)
    if not company:
        return redirect('dashboard/landing/')
    doc = get_document_for_company(pk, company)
    if not doc:
        messages.warning(request, 'Document not found.')
        return redirect('documents:list')
    return export_tables_to_excel(doc)


@login_required
@company_admin_or_permission_required('documents.change_document', raise_exception=True)
@require_POST
def document_delete_view(request, pk):
    """Soft delete a document. Company-scoped. Returns redirect or JSON for AJAX."""
    company = _company(request)
    if not company:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'status': 'error', 'message': 'No company'}, status=403)
        return redirect('dashboard/landing/')
    doc = get_document_for_company(pk, company)
    if not doc:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'status': 'error', 'message': 'Document not found'}, status=404)
        messages.warning(request, 'Document not found.')
        return redirect('documents:list')
    
    # Soft delete
    doc.is_deleted = True
    doc.save(update_fields=['is_deleted', 'updated_at'])
    
    # Only return JSON for explicit AJAX requests; normal browser visits should redirect.
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'status': 'success', 'message': 'Document deleted'})
    messages.success(request, 'Document deleted successfully.')
    return redirect('documents:list')


@login_required
@company_admin_or_permission_required('documents.view_document', raise_exception=True)
@require_GET
def document_processing_status_page(request, pk):
    """Page that shows processing status (with polling via AJAX)."""
    company = _company(request)
    if not company:
        return redirect('dashboard/landing/')
    doc = get_document_for_company(pk, company)
    if not doc:
        messages.warning(request, 'Document not found.')
        return redirect('documents:list')
    return render(request, 'documents/document_processing_status.html', {
        'document_id': doc.id,
        'status': doc.processing_status,
        'status_url': f'/documents/{doc.id}/status/',
    })


@login_required
@company_admin_or_permission_required('documents.change_document', raise_exception=True)
@require_POST
def document_reprocess_view(request, pk):
    """Re-run the pipeline for this document (extraction → AI → finance → tax). Deletes existing transactions for doc first."""
    company = _company(request)
    if not company:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'status': 'error', 'message': 'No company'}, status=403)
        return redirect('dashboard/landing/')
    doc = get_document_for_company(pk, company)
    if not doc:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'status': 'error', 'message': 'Document not found'}, status=404)
        return redirect('documents:list')
    from apps.finance_engine.models import FinancialTransaction
    deleted, _ = FinancialTransaction.objects.filter(company=company, document=doc).delete()
    doc.extracted_text_preview = ''
    doc.ai_result_json = ''
    doc.save(update_fields=['extracted_text_preview', 'ai_result_json', 'updated_at'])
    from .pipeline import run_pipeline
    result = run_pipeline(doc.id, company)
    # Only return JSON for explicit AJAX requests; normal browser submits should redirect.
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'status': 'success' if result.get('success') else 'error',
            'message': result.get('message', 'Re-process completed'),
            'transactions_created': result.get('transactions_created', 0),
        } if result.get('success') else {'status': 'error', 'message': result.get('message', 'Re-process failed')})
    return redirect('documents:detail', pk=pk)


@login_required
@company_admin_or_permission_required('documents.view_document', raise_exception=True)
@require_GET
def ajax_document_processing_status(request, pk):
    """AJAX: return JSON with document processing status (for polling)."""
    company = _company(request)
    if not company:
        return JsonResponse({'status': 'error', 'message': 'No company'}, status=403)
    doc = get_document_for_company(pk, company)
    if not doc:
        return JsonResponse({'status': 'error', 'message': 'Document not found'}, status=404)
    return JsonResponse({
        'status': 'success',
        'document_id': doc.id,
        'processing_status': doc.processing_status,
        'processing_error': doc.processing_error or '',
    })


@login_required
@never_cache
@company_admin_or_permission_required('documents.view_document', raise_exception=True)
def document_preview_view(request, pk):
    """
    Preview document file in browser.
    Supports multiple file types with appropriate preview methods.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")
    
    doc = get_document_for_company(pk, company)
    if not doc:
        messages.warning(request, 'Document not found.')
        return redirect('documents:list')
    
    if not doc.file:
        raise Http404("File not found")
    
    doc.increment_view_count()
    
    file_url = request.build_absolute_uri(doc.file.url)
    is_local = '127.0.0.1' in file_url or 'localhost' in file_url.lower()
    encoded_url = urllib.parse.quote(file_url, safe='')
    
    context = {
        'document': doc,
        'file_url': file_url,
        'download_url': f'/documents/{doc.id}/download/',
        'preview_url': None,
        'preview_type': 'none',
        'embed_url': None,
        'is_local': is_local,
        'file_data': None,
    }
    
    if is_local and doc.file_type in ['excel', 'csv', 'pdf', 'image', 'word']:
        try:
            with open(doc.file.path, 'rb') as f:
                file_content = f.read()
                context['file_data'] = base64.b64encode(file_content).decode('utf-8')
        except Exception as e:
            pass
    
    if doc.file_type == 'excel':
        if is_local and context.get('file_data'):
            context['preview_type'] = 'client_side'
        else:
            context['preview_type'] = 'none'
            
    elif doc.file_type == 'pdf':
        if is_local and context.get('file_data'):
            context['preview_type'] = 'client_side'
        else:
            context['preview_type'] = 'iframe_data'
            context['file_url'] = f'/documents/{doc.id}/file-data/'
            
    elif doc.file_type == 'image':
        if context.get('file_data'):
            context['preview_type'] = 'image_data'
        else:
            context['preview_type'] = 'native'
            context['file_url'] = doc.file.url
        
    elif doc.file_type == 'word':
        if is_local:
            context['preview_type'] = 'client_side'
        else:
            office_url = f'https://view.officeapps.live.com/op/view.aspx?src={encoded_url}'
            context['preview_type'] = 'google_docs'
            context['preview_url'] = office_url
        
    elif doc.file_type == 'csv':
        context['preview_type'] = 'client_side'
        
    else:
        context['preview_type'] = 'none'
    
    return render(request, 'documents/document_preview.html', context)


@login_required
@never_cache
@company_admin_or_permission_required('documents.view_document', raise_exception=True)
def document_download_view(request, pk):
    """Download document file."""
    company = _company(request)
    if not company:
        raise Http404("Company not found")
    
    doc = get_document_for_company(pk, company)
    if not doc:
        messages.warning(request, 'Document not found.')
        return redirect('documents:list')
    
    if not doc.file:
        raise Http404("File not found")
    
    doc.increment_download_count()
    
    file_path = doc.file.path
    file_name = doc.original_filename or os.path.basename(file_path)
    
    mime_type = doc.mime_type
    if not mime_type:
        mime_type, _ = mimetypes.guess_type(file_path)
        mime_type = mime_type or 'application/octet-stream'
    
    response = FileResponse(
        open(file_path, 'rb'),
        content_type=mime_type
    )
    response['Content-Disposition'] = f'attachment; filename="{file_name}"'
    response['Content-Length'] = doc.file_size
    
    return response


@login_required
@company_admin_or_permission_required('documents.change_document', raise_exception=True)
@require_POST
def document_toggle_star_view(request, pk):
    """Toggle star status of a document."""
    company = _company(request)
    if not company:
        return JsonResponse({'error': 'Company not found'}, status=404)
    
    doc = get_document_for_company(pk, company)
    if not doc:
        return JsonResponse({'error': 'Document not found'}, status=404)
    
    doc.is_starred = not doc.is_starred
    doc.save(update_fields=['is_starred', 'updated_at'])
    
    return JsonResponse({
        'is_starred': doc.is_starred
    })


@login_required
@company_admin_or_permission_required('documents.change_document', raise_exception=True)
@require_POST
def document_toggle_archive_view(request, pk):
    """Toggle archive status of a document."""
    company = _company(request)
    if not company:
        return JsonResponse({'error': 'Company not found'}, status=404)
    
    doc = get_document_for_company(pk, company)
    if not doc:
        return JsonResponse({'error': 'Document not found'}, status=404)
    
    doc.is_archived = not doc.is_archived
    doc.save(update_fields=['is_archived', 'updated_at'])
    
    return JsonResponse({
        'is_archived': doc.is_archived
    })


@login_required
@never_cache
@company_admin_or_permission_required('documents.view_document', raise_exception=True)
def document_file_data_view(request, pk):
    """Serve file data for client-side preview."""
    company = _company(request)
    if not company:
        raise Http404("Company not found")
    
    doc = get_document_for_company(pk, company)
    if not doc:
        raise Http404("Document not found")
    
    if not doc.file:
        raise Http404("File not found")
    
    file_path = doc.file.path
    
    mime_type = doc.mime_type
    if not mime_type:
        mime_type, _ = mimetypes.guess_type(file_path)
        mime_type = mime_type or 'application/octet-stream'
    
    response = FileResponse(
        open(file_path, 'rb'),
        content_type=mime_type
    )
    response['Content-Disposition'] = f'inline; filename="{doc.original_filename}"'
    
    return response
