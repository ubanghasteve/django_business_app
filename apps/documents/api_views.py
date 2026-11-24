# -*- coding: utf-8 -*-
"""
Documents API: JSON endpoints for /api/documents/upload/ and /api/documents/status/
All company-scoped. Permission checks applied for RBAC consistency.
"""
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.http import JsonResponse

from apps.core.utils import get_company_profile_for_user
from apps.core.permissions import company_admin_or_permission_required
from .forms import DocumentUploadForm
from .models import Document
from .services import get_document_for_company


def _company(request):
    return getattr(request, 'company', None) or get_company_profile_for_user(request.user, request)


@login_required
@company_admin_or_permission_required('documents.add_document', raise_exception=True)
@require_POST
def api_upload(request):
    """POST /api/documents/upload/ - multipart form with file only. Document type is auto-detected. Returns JSON."""
    company = _company(request)
    if not company:
        return JsonResponse({'status': 'error', 'message': 'No company'}, status=403)
    form = DocumentUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)
    doc = form.save(commit=False)
    doc.company = company
    doc.uploaded_by = request.user
    doc.file_type = getattr(request.FILES.get('file'), 'content_type', '') or ''
    doc.save()
    # Run pipeline in background so upload returns immediately
    import threading
    from django.db import connection
    doc_id, company_pk = doc.id, company.pk
    def _run_pipeline():
        try:
            from apps.core.models import CompanyProfile
            from .pipeline import run_pipeline
            c = CompanyProfile.objects.get(pk=company_pk)
            run_pipeline(doc_id, c)
        finally:
            connection.close()
    threading.Thread(target=_run_pipeline, daemon=True).start()
    return JsonResponse({
        'status': 'success',
        'message': 'Document uploaded',
        'id': doc.id,
        'redirect_url': doc.get_absolute_url(),
    })


@login_required
@company_admin_or_permission_required('documents.view_document', raise_exception=True)
@require_GET
def api_status(request, pk):
    """GET /api/documents/<id>/status/ - returns JSON processing status."""
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
