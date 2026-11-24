# -*- coding: utf-8 -*-
"""
Finance engine API views. All filtered by request.company. JSON responses for AJAX.
"""
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.http import JsonResponse

from apps.core.utils import get_company_profile_for_user
from .models import FinancialTransaction
from .services import transaction_extraction_service


def _company(request):
    return getattr(request, 'company', None) or get_company_profile_for_user(request.user, request)


@login_required
@require_GET
def api_transaction_list(request):
    """List financial transactions for company (JSON)."""
    company = _company(request)
    if not company:
        return JsonResponse({'status': 'error', 'message': 'No company'}, status=403)
    qs = FinancialTransaction.objects.filter(company=company).select_related('document').order_by('-transaction_date')[:200]
    data = [
        {
            'id': t.id,
            'transaction_type': t.transaction_type,
            'amount': str(t.amount),
            'vat_amount': str(t.vat_amount) if t.vat_amount else None,
            'transaction_date': t.transaction_date.isoformat() if t.transaction_date else None,
            'reference': t.reference,
        }
        for t in qs
    ]
    return JsonResponse({'status': 'success', 'transactions': data})
