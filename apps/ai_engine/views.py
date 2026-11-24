# -*- coding: utf-8 -*-
"""
AI Engine API: POST /api/ai/analyze/ with text= or document_id=. Returns JSON structured fields.
"""
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse

from apps.core.utils import get_company_profile_for_user
from apps.core.permissions import company_admin_or_permission_required
from apps.documents.services import get_document_for_company
from apps.extraction.services import run_extraction
from .services import analyze_document_text_service


def _company(request):
    return getattr(request, 'company', None) or get_company_profile_for_user(request.user, request)


@login_required
@company_admin_or_permission_required('documents.view_document', raise_exception=True)
@require_POST
def api_analyze(request):
    """
    POST text=... or document_id=.
    If document_id: load document (company-scoped), run extraction, then analyze text.
    Returns: invoice_number, supplier, date, total, vat_amount.
    """
    company = _company(request)
    if not company:
        return JsonResponse({'status': 'error', 'message': 'No company'}, status=403)
    text = request.POST.get('text') or request.GET.get('text')
    document_id = request.POST.get('document_id') or request.GET.get('document_id')
    if document_id and not text:
        try:
            doc_id = int(document_id)
        except (TypeError, ValueError):
            return JsonResponse({'status': 'error', 'message': 'Invalid document_id'}, status=400)
        doc = get_document_for_company(doc_id, company)
        if not doc or not doc.file:
            return JsonResponse({'status': 'error', 'message': 'Document not found or no file'}, status=404)
        extraction = run_extraction(doc.file)
        text = extraction.get('text', '')
    if not text:
        return JsonResponse({'status': 'error', 'message': 'Provide text= or document_id='}, status=400)
    result = analyze_document_text_service(text)
    return JsonResponse({'status': 'success', 'result': result})
