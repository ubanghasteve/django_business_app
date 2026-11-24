# -*- coding: utf-8 -*-
"""
Extraction API: POST /api/extraction/run/ with document_id. Company-scoped, returns JSON.
"""
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse

from apps.core.utils import get_company_profile_for_user
from apps.core.permissions import company_admin_or_permission_required
from apps.documents.services import get_document_for_company
from .tasks import run_extraction_for_document


def _company(request):
    return getattr(request, 'company', None) or get_company_profile_for_user(request.user, request)


@login_required
@company_admin_or_permission_required('documents.view_document', raise_exception=True)
@require_POST
def api_run(request):
    """POST document_id=. Run OCR/PDF extraction for document. Returns JSON."""
    company = _company(request)
    if not company:
        return JsonResponse({'status': 'error', 'message': 'No company'}, status=403)
    try:
        document_id = int(request.POST.get('document_id') or request.GET.get('document_id') or 0)
    except (TypeError, ValueError):
        return JsonResponse({'status': 'error', 'message': 'document_id required'}, status=400)
    result = run_extraction_for_document(document_id, company)
    if not result.get('success'):
        return JsonResponse({
            'status': 'error',
            'message': result.get('error', 'Extraction failed'),
            'extraction': result.get('extraction'),
        }, status=400)
    ext = result.get('extraction', {})
    doc = result.get('document')
    return JsonResponse({
        'status': 'success',
        'message': 'Extraction completed',
        'document_id': document_id,
        'processing_status': getattr(doc, 'processing_status', 'completed') if doc else 'completed',
        'text_length': len(ext.get('text', '')),
        'tables_count': len(ext.get('tables', [])),
    })


