# -*- coding: utf-8 -*-
"""
Tax engine API views. All filtered by request.company. JSON responses.
"""
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.http import JsonResponse
from datetime import date
import calendar

from apps.core.utils import get_company_profile_for_user
from apps.core.permissions import company_admin_or_permission_required
from .models import TaxRecord
from .services import compute_tax


def _company(request):
    return getattr(request, 'company', None) or get_company_profile_for_user(request.user, request)


@login_required
@company_admin_or_permission_required('documents.view_tax_report', raise_exception=True)
@require_GET
def api_tax_compute(request):
    """
    GET with period_type, period_start, period_end (YYYY-MM-DD).
    Computes tax for that period and returns JSON.
    """
    company = _company(request)
    if not company:
        return JsonResponse({'status': 'error', 'message': 'No company'}, status=403)
    period_type = request.GET.get('period_type', 'monthly')
    period_start_s = request.GET.get('period_start')
    period_end_s = request.GET.get('period_end')
    if not period_start_s or not period_end_s:
        return JsonResponse({'status': 'error', 'message': 'period_start and period_end required (YYYY-MM-DD)'}, status=400)
    try:
        period_start = date.fromisoformat(period_start_s)
        period_end = date.fromisoformat(period_end_s)
    except ValueError:
        return JsonResponse({'status': 'error', 'message': 'Invalid date format'}, status=400)
    record = compute_tax(company, period_type, period_start, period_end)
    if not record:
        return JsonResponse({'status': 'error', 'message': 'Could not compute'}, status=400)
    return JsonResponse({
        'status': 'success',
        'record': {
            'id': record.id,
            'period_type': record.period_type,
            'period_start': record.period_start.isoformat(),
            'period_end': record.period_end.isoformat(),
            'total_revenue': str(record.total_revenue),
            'total_expenses': str(record.total_expenses),
            'taxable_profit': str(record.taxable_profit),
            'corporate_tax': str(record.corporate_tax),
            'vat_payable': str(record.vat_payable),
        },
    })


@login_required
@company_admin_or_permission_required('documents.view_tax_report', raise_exception=True)
@require_GET
def api_tax_list(request):
    """List tax records for company (JSON)."""
    company = _company(request)
    if not company:
        return JsonResponse({'status': 'error', 'message': 'No company'}, status=403)
    qs = TaxRecord.objects.filter(company=company).order_by('-period_end')[:50]
    data = [
        {
            'id': r.id,
            'period_type': r.period_type,
            'period_start': r.period_start.isoformat(),
            'period_end': r.period_end.isoformat(),
            'total_revenue': str(r.total_revenue),
            'total_expenses': str(r.total_expenses),
            'taxable_profit': str(r.taxable_profit),
            'corporate_tax': str(r.corporate_tax),
            'vat_payable': str(r.vat_payable),
        }
        for r in qs
    ]
    return JsonResponse({'status': 'success', 'records': data})
