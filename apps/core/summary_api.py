"""
Read-only JSON summary endpoints for dashboard metrics and module summaries.
Uses request.company for tenant scope; enforces per-team-member visibility via
for_user_queryset (admin sees all, team member sees own). Returns numbers only.
No business mutations.
"""
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import never_cache
from django.db.models import Sum, Count, F, Case, When, Value
from django.db.models.functions import Least
from django.db.models.fields import DecimalField
from django.utils import timezone
from decimal import Decimal
from datetime import datetime, timedelta

from apps.core.ownership import for_user_queryset, get_account_for_user
from apps.core.utils import get_revenue_period_boundaries


def _account_id(request):
    """Tenant scope: request.company.account_id or request.user.account_id."""
    if getattr(request, 'company', None) and hasattr(request.company, 'account_id'):
        return getattr(request.company, 'account_id', None)
    return getattr(request.user, 'account_id', None)


def _company(request):
    """Company profile for expense scoping (Expense uses company FK)."""
    return getattr(request, 'company', None)


# -----------------------------------------------------------------------------
# Dashboard metrics (main dashboard)
# -----------------------------------------------------------------------------

@login_required
@require_http_methods(['GET'])
@never_cache
def dashboard_metrics(request):
    """Read-only dashboard metrics. Uses get_account_for_user (same as dashboard view and for_user_queryset).
    Returns JSON numbers only. Empty metrics (200) only when user has no account."""
    account = get_account_for_user(request.user)
    if not account:
        return JsonResponse({
            'core': {'total_invoices': 0, 'monthly_revenue': 0, 'total_clients': 0, 'outstanding_invoices': 0},
            'total_quotations': 0,
            'total_waybills': 0,
        })
    from apps.invoices.models import Invoice
    from apps.quotations.models import Quotation
    from apps.waybills.models import Waybill
    from apps.clients.models import Client
    now = timezone.now()
    today = now.date()
    current_month = now.month
    current_year = now.year
    start_of_month = datetime(current_year, current_month, 1).date()
    invoices = for_user_queryset(Invoice, request.user, request, account_lookup='account')
    quotations = for_user_queryset(Quotation, request.user, request, account_lookup='account')
    waybills = for_user_queryset(Waybill, request.user, request, account_lookup='account')
    clients = for_user_queryset(Client, request.user, request, account_lookup='company__account')
    monthly_invoices = invoices.filter(invoice_date__gte=start_of_month)
    monthly_revenue = monthly_invoices.aggregate(t=Sum('grand_total'))['t'] or 0
    outstanding = invoices.filter(status__in=['unpaid', 'partial']).aggregate(t=Sum('balance_due'))['t'] or 0
    return JsonResponse({
        'core': {
            'total_invoices': invoices.count(),
            'monthly_revenue': float(monthly_revenue),
            'total_clients': clients.count(),
            'outstanding_invoices': float(outstanding),
        },
        'total_quotations': quotations.count(),
        'total_waybills': waybills.count(),
    })


@login_required
@require_http_methods(['GET'])
@never_cache
def dashboard_full_metrics(request):
    """Full dashboard data for real-time chart and stat updates. Uses same get_cached_dashboard_stats
    and RBAC as the main dashboard view so data is accurate and consistent."""
    from apps.core.views import get_cached_dashboard_stats
    stats = get_cached_dashboard_stats(request.user, request=request)
    user = request.user
    can_view_invoice = user.has_perm('invoices.view_invoice')
    can_view_quotation = user.has_perm('quotations.view_quotation')
    can_view_waybill = user.has_perm('waybills.view_waybill')
    can_view_client = user.has_perm('clients.view_client')
    # Core stats (same as dashboard template data-realtime-key)
    core = {
        'total_invoices': stats['total_invoices'] if can_view_invoice else 0,
        'monthly_revenue': float(stats['monthly_revenue']) if can_view_invoice else 0,
        'outstanding_invoices': float(stats['outstanding_invoices']) if can_view_invoice else 0,
        'total_clients': stats['total_clients'] if can_view_client else 0,
        'today_revenue': float(stats['today_revenue']) if can_view_invoice else 0,
        'refund_due': float(stats.get('refund_due', 0)) if can_view_invoice else 0,
        'total_quotations': stats['total_quotations'] if can_view_quotation else 0,
        'total_waybills': stats['total_waybills'] if can_view_waybill else 0,
    }
    # Chart data (RBAC: only include what user can see)
    chart_overview_labels = []
    chart_overview_data = []
    if can_view_invoice:
        chart_overview_labels.append('Invoices')
        chart_overview_data.append(stats['total_invoices'])
    if can_view_quotation:
        chart_overview_labels.append('Quotations')
        chart_overview_data.append(stats['total_quotations'])
    if can_view_waybill:
        chart_overview_labels.append('Waybills')
        chart_overview_data.append(stats['total_waybills'])
    breakdown = stats.get('invoice_status_breakdown', {})
    invoice_status_pie_data = [
        int(breakdown.get('unpaid', 0)),
        int(breakdown.get('partial', 0)),
        int(breakdown.get('paid', 0)),
    ] if can_view_invoice else [0, 0, 0]
    return JsonResponse({
        'core': core,
        'revenue_trend_labels': stats.get('revenue_trend_labels', []) if can_view_invoice else [],
        'revenue_trend_data': stats.get('revenue_trend_data', []) if can_view_invoice else [],
        'chart_overview_labels': chart_overview_labels,
        'chart_overview_data': chart_overview_data,
        'invoice_status_pie_data': invoice_status_pie_data,
        'histogram_labels': stats.get('histogram_labels', []) if can_view_invoice else [],
        'histogram_data': stats.get('histogram_data', []) if can_view_invoice else [],
    })


# -----------------------------------------------------------------------------
# Invoices summary
# -----------------------------------------------------------------------------

@login_required
@require_http_methods(['GET'])
@never_cache
def invoices_summary(request):
    """Read-only invoices summary. Uses request.company; enforces view_invoice."""
    company = _company(request)
    if not company:
        return JsonResponse({'error': 'Company context required'}, status=403)
    if not request.user.has_perm('invoices.view_invoice'):
        return JsonResponse({'error': 'Forbidden'}, status=403)
    account_id = _account_id(request)
    if not account_id:
        return JsonResponse({'error': 'Company context required'}, status=403)
    from apps.invoices.models import Invoice
    qs = for_user_queryset(Invoice, request.user, request, account_lookup='account')
    agg = qs.aggregate(
        total_count=Count('id'),
        total_amount=Sum('grand_total'),
        paid_amount=Sum('amount_paid'),
    )
    total = float(agg['total_amount'] or 0)
    paid = float(agg['paid_amount'] or 0)
    # Revenue = earned only: min(amount_paid, grand_total) per invoice. Unpaid=0; part payment=amount_paid only; overpayment does not inflate.
    qs_capped = qs.annotate(rev_cap=Least(F('amount_paid'), F('grand_total')))
    revenue_generated = float(qs_capped.aggregate(s=Sum('rev_cap'))['s'] or 0)
    outstanding = float(qs.aggregate(s=Sum(Case(When(balance_due__gt=0, then=F('balance_due')), default=Value(Decimal('0')), output_field=DecimalField())))['s'] or 0)
    refund_due = float(qs.aggregate(s=Sum(Case(When(amount_paid__gt=F('grand_total'), then=F('amount_paid') - F('grand_total')), default=Value(Decimal('0')), output_field=DecimalField())))['s'] or 0)
    # Revenue by period: strict boundaries so each card shows only that period's data.
    periods = get_revenue_period_boundaries()
    rev_today = float(qs_capped.filter(invoice_date=periods['today']).aggregate(s=Sum('rev_cap'))['s'] or 0)
    rev_week = float(qs_capped.filter(
        invoice_date__gte=periods['week_start'],
        invoice_date__lte=periods['week_end']
    ).aggregate(s=Sum('rev_cap'))['s'] or 0)
    rev_month = float(qs_capped.filter(
        invoice_date__gte=periods['start_of_month'],
        invoice_date__lte=periods['end_of_month']
    ).aggregate(s=Sum('rev_cap'))['s'] or 0)
    rev_quarter = float(qs_capped.filter(
        invoice_date__gte=periods['quarter_start'],
        invoice_date__lte=periods['quarter_end']
    ).aggregate(s=Sum('rev_cap'))['s'] or 0)
    rev_year = float(qs_capped.filter(
        invoice_date__gte=periods['year_start'],
        invoice_date__lte=periods['year_end']
    ).aggregate(s=Sum('rev_cap'))['s'] or 0)
    return JsonResponse({
        'total_count': agg['total_count'] or 0,
        'total_amount': total,
        'paid_amount': paid,
        'revenue_generated': revenue_generated,
        'outstanding': outstanding,
        'refund_due': refund_due,
        'revenue_today': rev_today,
        'revenue_week': rev_week,
        'revenue_month': rev_month,
        'revenue_quarter': rev_quarter,
        'revenue_year': rev_year,
    })


# -----------------------------------------------------------------------------
# Receipts summary
# -----------------------------------------------------------------------------

@login_required
@require_http_methods(['GET'])
@never_cache
def receipts_summary(request):
    """Read-only receipts summary. Uses request.company; enforces view_receipt."""
    company = _company(request)
    if not company:
        return JsonResponse({'error': 'Company context required'}, status=403)
    if not request.user.has_perm('receipts.view_receipt'):
        return JsonResponse({'error': 'Forbidden'}, status=403)
    account_id = _account_id(request)
    if not account_id:
        return JsonResponse({'error': 'Company context required'}, status=403)
    from apps.receipts.models import Receipt
    today = timezone.now().date()
    week_start = today - timezone.timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    qs = for_user_queryset(Receipt, request.user, request, account_lookup='account')
    today_sum = qs.filter(date_received=today).aggregate(s=Sum('amount_received'))['s'] or 0
    week_sum = qs.filter(date_received__gte=week_start).aggregate(s=Sum('amount_received'))['s'] or 0
    month_sum = qs.filter(date_received__gte=month_start).aggregate(s=Sum('amount_received'))['s'] or 0
    return JsonResponse({
        'total_today': float(today_sum),
        'total_week': float(week_sum),
        'total_month': float(month_sum),
    })


# -----------------------------------------------------------------------------
# Quotations summary
# -----------------------------------------------------------------------------

@login_required
@require_http_methods(['GET'])
@never_cache
def quotations_summary(request):
    """Read-only quotations summary. Uses request.company; enforces view_quotation."""
    company = _company(request)
    if not company:
        return JsonResponse({'error': 'Company context required'}, status=403)
    if not request.user.has_perm('quotations.view_quotation'):
        return JsonResponse({'error': 'Forbidden'}, status=403)
    account_id = _account_id(request)
    if not account_id:
        return JsonResponse({'error': 'Company context required'}, status=403)
    from apps.quotations.models import Quotation
    qs = for_user_queryset(Quotation, request.user, request, account_lookup='account')
    total = qs.count()
    sent = qs.filter(status='sent').count()
    accepted = qs.filter(status='accepted').count()
    draft = qs.filter(status='draft').count()
    total_value = qs.aggregate(t=Sum('grand_total'))['t'] or 0
    return JsonResponse({
        'total_quotations': total,
        'sent_count': sent,
        'total_value': float(total_value),
        'accepted_count': accepted,
        'draft_count': draft,
    })


# -----------------------------------------------------------------------------
# Job orders summary
# -----------------------------------------------------------------------------

@login_required
@require_http_methods(['GET'])
@never_cache
def job_orders_summary(request):
    """Read-only job orders summary. Uses request.company; enforces view_product or view_order."""
    company = _company(request)
    if not company:
        return JsonResponse({'error': 'Company context required'}, status=403)
    if not (request.user.has_perm('job_orders.view_product') or request.user.has_perm('job_orders.view_order')):
        return JsonResponse({'error': 'Forbidden'}, status=403)
    account_id = _account_id(request)
    if not account_id:
        return JsonResponse({'error': 'Company context required'}, status=403)
    from apps.job_orders.models import Product, Order
    products = for_user_queryset(Product, request.user, request, account_lookup='account')
    orders = Order.objects.filter(customer__account_id=account_id)  # Order has no created_by; scope by customer account
    total_orders = orders.count()
    pending_orders = orders.filter(order_status='pending').count()
    # Active customers: distinct users who placed orders in this account
    active_customers = orders.values('customer').distinct().count()
    return JsonResponse({
        'total_products': products.count(),
        'active_customers': active_customers,
        'total_orders': total_orders,
        'pending_orders': pending_orders,
    })


# -----------------------------------------------------------------------------
# Waybills summary
# -----------------------------------------------------------------------------

@login_required
@require_http_methods(['GET'])
@never_cache
def waybills_summary(request):
    """Read-only waybills summary. Uses request.company; enforces view_waybill."""
    company = _company(request)
    if not company:
        return JsonResponse({'error': 'Company context required'}, status=403)
    if not request.user.has_perm('waybills.view_waybill'):
        return JsonResponse({'error': 'Forbidden'}, status=403)
    account_id = _account_id(request)
    if not account_id:
        return JsonResponse({'error': 'Company context required'}, status=403)
    from apps.waybills.models import Waybill
    qs = for_user_queryset(Waybill, request.user, request, account_lookup='account')
    total = qs.count()
    pending = qs.filter(status='pending').count()
    in_transit = qs.filter(status='dispatched').count()
    delivered = qs.filter(status='delivered').count()
    return JsonResponse({
        'total_waybills': total,
        'pending_count': pending,
        'in_transit_count': in_transit,
        'delivered_count': delivered,
    })
