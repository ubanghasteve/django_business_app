# -*- coding: utf-8 -*-
"""
Finance API: POST /api/finance/extract/ with document_id. Runs extraction + AI + transaction creation. Returns JSON.
"""
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse

from apps.core.utils import get_company_profile_for_user
from apps.core.permissions import company_admin_or_permission_required
from apps.documents.services import get_document_for_company
from apps.extraction.services import run_extraction
from apps.ai_engine.services import analyze_document_text_service
from .services import transaction_extraction_service


def _company(request):
    return getattr(request, 'company', None) or get_company_profile_for_user(request.user, request)


@login_required
@company_admin_or_permission_required('documents.view_document', raise_exception=True)
@require_POST
def api_extract(request):
    """
    POST document_id=. For the document: run extraction -> AI analyze -> create FinancialTransactions.
    Returns JSON with created transaction count.
    """
    company = _company(request)
    if not company:
        return JsonResponse({'status': 'error', 'message': 'No company'}, status=403)
    try:
        document_id = int(request.POST.get('document_id') or request.GET.get('document_id') or 0)
    except (TypeError, ValueError):
        return JsonResponse({'status': 'error', 'message': 'document_id required'}, status=400)
    doc = get_document_for_company(document_id, company)
    if not doc or not doc.file:
        return JsonResponse({'status': 'error', 'message': 'Document not found or no file'}, status=404)
    extraction = run_extraction(doc.file)
    text = extraction.get('text', '')
    ai_result = analyze_document_text_service(text)
    created = transaction_extraction_service(company, doc, ai_result)
    return JsonResponse({
        'status': 'success',
        'message': f'{len(created)} transaction(s) created',
        'document_id': document_id,
        'created_count': len(created),
    })
