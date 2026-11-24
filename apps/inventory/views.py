# -*- coding: utf-8 -*-
"""
Inventory views: dashboard, list (with cache), create, update, delete, detail, print, PDF, AJAX.
All querysets scoped via for_user_queryset(Inventory, request.user, request, account_lookup='account').
Cache key: inventory_list_{company_id}; cleared on create/update/delete/status_change.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count, Case, When, IntegerField
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.core.cache import cache
from datetime import date, timedelta
import calendar
import logging

logger = logging.getLogger(__name__)

from apps.core.permissions import company_admin_or_permission_required
from apps.core.ownership import for_user_queryset, get_account_for_user, is_company_admin
from apps.core.utils import get_company_profile_for_user, apply_no_cache_headers
from .models import (
    Inventory,
    InventoryMovement,
    WasteLog,
    InventoryIssue,
    InventoryReceipt,
    LEGACY_ISSUE_REMARK,
    LEGACY_RECEIPT_REMARK,
    LEGACY_WASTE_REMARK,
    _decimal_safe,
    _floor_zero,
    format_quantity_number,
    over_issue_message,
    over_waste_message,
)
from apps.waybills.utils.quantity_parser import extract_numeric_value
from .ledger_sync import sync_inventory_row, prepare_inventory_for_panel
from .models import compose_total_quantity_input, normalize_quantity_input, normalize_unit_price_input

INVENTORY_LIST_PAGE_SIZE = 10


def _inventory_queryset(request):
    """Queryset for current user: account-scoped, plus records with no account but same company (so counts show). Exclude soft-deleted (offline sync)."""
    base = for_user_queryset(
        Inventory, request.user, request, account_lookup='account'
    ).filter(is_deleted=False).select_related('company', 'created_by')
    account = get_account_for_user(request.user)
    company = get_company_profile_for_user(request.user, request)
    if account and company:
        from django.db.models import Q
        extra = Inventory.objects.filter(account__isnull=True, company=company, is_deleted=False).select_related('company', 'created_by')
        if not is_company_admin(request.user, request):
            extra = extra.filter(created_by=request.user)
        base = (base | extra).distinct()
    elif not account and company:
        base = Inventory.objects.filter(company=company, is_deleted=False).select_related('company', 'created_by')
        if not is_company_admin(request.user, request):
            base = base.filter(created_by=request.user)
    return base


def _clear_inventory_list_cache(request):
    company = get_company_profile_for_user(request.user, request)
    if company:
        cache.delete(f"inventory_list_{company.id}")


def _inventory_document_context(request, obj):
    """Context for inventory detail/print/PDF: company details and theme, no signature."""
    company = get_company_profile_for_user(request.user, request)
    company_logo = None
    if company and getattr(company, 'logo', None) and company.logo:
        company_logo = company.logo.url
    theme_primary = getattr(company, 'primary_color', '#1976d2') if company else '#1976d2'
    theme_secondary = getattr(company, 'secondary_color', '#f8f9fa') if company else '#f8f9fa'
    theme_accent = getattr(company, 'accent_color', '#e9ecef') if company else '#e9ecef'
    theme_text = getattr(company, 'text_color', '#333333') if company else '#333333'
    currency_symbol = getattr(company, 'currency_symbol', '₦') if company else '₦'
    return {
        'object': obj,
        'company_profile': company,
        'company_logo': company_logo,
        'theme_primary_color': theme_primary,
        'theme_secondary_color': theme_secondary,
        'theme_accent_color': theme_accent,
        'theme_text_color': theme_text,
        'user_currency_symbol': currency_symbol,
    }


def _parse_inventory_list_date_range(request):
    """
    Parse GET params: range_type (all, day, week, month, quarter, year, custom),
    period_date (YYYY-MM-DD for day/week/month/quarter/year), date_from, date_to (for custom).
    Returns (queryset_filter_kwargs, date_label).
    queryset_filter_kwargs: dict for .filter(created_at__date__gte=..., created_at__date__lte=...)
    or {} for no filter. date_label: human-readable range description.
    """
    range_type = (request.GET.get('range_type') or 'all').strip().lower()
    today = timezone.now().date()
    filter_kwargs = {}
    date_label = 'All records'

    if range_type == 'all':
        return {}, 'All records'

    if range_type == 'custom':
        date_from_s = (request.GET.get('date_from') or '').strip()
        date_to_s = (request.GET.get('date_to') or '').strip()
        try:
            if date_from_s:
                d_from = date.fromisoformat(date_from_s)
                filter_kwargs['created_at__date__gte'] = d_from
            if date_to_s:
                d_to = date.fromisoformat(date_to_s)
                filter_kwargs['created_at__date__lte'] = d_to
            if date_from_s and date_to_s:
                date_label = f"{d_from.strftime('%d %b %Y')} – {d_to.strftime('%d %b %Y')}"
            elif date_from_s:
                date_label = f"From {d_from.strftime('%d %b %Y')}"
            elif date_to_s:
                date_label = f"Up to {d_to.strftime('%d %b %Y')}"
        except ValueError:
            pass
        return filter_kwargs, date_label

    period_date_s = (request.GET.get('period_date') or '').strip()
    try:
        ref = date.fromisoformat(period_date_s) if period_date_s else today
    except ValueError:
        ref = today

    if range_type == 'day':
        filter_kwargs['created_at__date'] = ref
        date_label = ref.strftime('%d %b %Y')
    elif range_type == 'week':
        week_start = ref - timedelta(days=ref.weekday())
        week_end = week_start + timedelta(days=6)
        filter_kwargs['created_at__date__gte'] = week_start
        filter_kwargs['created_at__date__lte'] = week_end
        date_label = f"{week_start.strftime('%d %b %Y')} – {week_end.strftime('%d %b %Y')} (Week)"
    elif range_type == 'month':
        start_of_month = ref.replace(day=1)
        _, last_day = calendar.monthrange(ref.year, ref.month)
        end_of_month = ref.replace(day=last_day)
        filter_kwargs['created_at__date__gte'] = start_of_month
        filter_kwargs['created_at__date__lte'] = end_of_month
        date_label = ref.strftime('%B %Y')
    elif range_type == 'quarter':
        quarter = (ref.month - 1) // 3 + 1
        quarter_start = date(ref.year, (quarter - 1) * 3 + 1, 1)
        quarter_end_month = quarter * 3
        _, qlast = calendar.monthrange(ref.year, quarter_end_month)
        quarter_end = date(ref.year, quarter_end_month, qlast)
        filter_kwargs['created_at__date__gte'] = quarter_start
        filter_kwargs['created_at__date__lte'] = quarter_end
        date_label = f"Q{quarter} {ref.year}"
    elif range_type == 'year':
        year_start = date(ref.year, 1, 1)
        year_end = date(ref.year, 12, 31)
        filter_kwargs['created_at__date__gte'] = year_start
        filter_kwargs['created_at__date__lte'] = year_end
        date_label = str(ref.year)
    else:
        return {}, 'All records'

    return filter_kwargs, date_label


# Report categories aligned with inventory dashboard cards (print / PDF / list metric filter).
INVENTORY_REPORT_CATEGORIES = [
    ('all', 'All records (Total Products)'),
    ('quantity_in', 'Total Quantity In'),
    ('quantity_out', 'Total Quantity Out'),
    ('balance', 'Grand Total Balance'),
    ('stock_value', 'Stock Value Remaining'),
    ('draft', 'Draft'),
    ('pending', 'Pending'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
    ('waste', 'Total Waste'),
    ('in_stock', 'In Stock'),
    ('low_stock', 'Low Stock'),
    ('out_of_stock', 'Out of Stock'),
]
_INVENTORY_REPORT_CATEGORY_LABELS = dict(INVENTORY_REPORT_CATEGORIES)
_INVENTORY_STOCK_CATEGORIES = {'in_stock', 'low_stock', 'out_of_stock'}
_INVENTORY_APPROVAL_CATEGORIES = {'draft', 'pending', 'approved', 'rejected'}


def _resolve_inventory_report_category(request):
    """
    Resolve report category from GET.
    Prefer explicit `category`; otherwise derive from list filters
    (`stock_status`, `approval_status`, `metric`) so filtered list pages print correctly.
    """
    raw = (request.GET.get('category') or '').strip().lower()
    if raw in _INVENTORY_REPORT_CATEGORY_LABELS:
        return raw
    stock = (request.GET.get('stock_status') or '').strip().lower()
    if stock in _INVENTORY_STOCK_CATEGORIES:
        return stock
    approval = (request.GET.get('approval_status') or '').strip().lower()
    if approval in _INVENTORY_APPROVAL_CATEGORIES:
        return approval
    metric = (request.GET.get('metric') or '').strip().lower()
    if metric in _INVENTORY_REPORT_CATEGORY_LABELS:
        return metric
    return 'all'


def _apply_inventory_report_category(qs, category):
    """
    Filter inventory queryset by dashboard-card category.
    Returns (queryset, category_label).
    """
    category = (category or 'all').strip().lower()
    if category not in _INVENTORY_REPORT_CATEGORY_LABELS:
        category = 'all'
    label = _INVENTORY_REPORT_CATEGORY_LABELS[category]

    if category == 'all':
        return qs, label
    if category == 'quantity_in':
        return qs.filter(quantity_in__gt=0), label
    if category == 'quantity_out':
        return qs.filter(quantity_out__gt=0), label
    if category == 'balance':
        return qs.filter(total_amount__gt=0), label
    if category == 'stock_value':
        return qs.filter(stock_balance_remaining__gt=0), label
    if category == 'waste':
        return qs.filter(waste__gt=0), label
    if category in _INVENTORY_STOCK_CATEGORIES:
        return qs.filter(stock_status=category), label
    if category in _INVENTORY_APPROVAL_CATEGORIES:
        return qs.filter(approval_status=category), label
    return qs, label


def _inventory_list_document_context(request, object_list, date_label, category_label=''):
    """Context for inventory list print/PDF: company details, logo, theme, object_list, no signature."""
    company = get_company_profile_for_user(request.user, request)
    company_logo = None
    if company and getattr(company, 'logo', None) and company.logo:
        company_logo = company.logo.url
    theme_primary = getattr(company, 'primary_color', '#1976d2') if company else '#1976d2'
    theme_secondary = getattr(company, 'secondary_color', '#f8f9fa') if company else '#f8f9fa'
    theme_accent = getattr(company, 'accent_color', '#e9ecef') if company else '#e9ecef'
    theme_text = getattr(company, 'text_color', '#333333') if company else '#333333'
    currency_symbol = getattr(company, 'currency_symbol', '₦') if company else '₦'
    show_category = bool(category_label) and not str(category_label).lower().startswith('all records')
    if show_category and date_label:
        report_period_label = f'{category_label} · {date_label}'
    elif show_category:
        report_period_label = category_label
    else:
        report_period_label = date_label or 'All records'
    return {
        'object_list': object_list,
        'date_label': date_label,
        'category_label': category_label,
        'report_period_label': report_period_label,
        'company_profile': company,
        'company_logo': company_logo,
        'theme_primary_color': theme_primary,
        'theme_secondary_color': theme_secondary,
        'theme_accent_color': theme_accent,
        'theme_text_color': theme_text,
        'user_currency_symbol': currency_symbol,
    }


@login_required
@company_admin_or_permission_required('inventory.view_inventory', raise_exception=True)
@never_cache
def inventory_dashboard(request):
    """Dashboard with summary cards: total products, total quantity in, total quantity out, stock value remaining."""
    company = get_company_profile_for_user(request.user, request)
    qs = _inventory_queryset(request)
    total_products = qs.count()
    agg = qs.aggregate(
        total_in=Sum('quantity_in'),
        total_out=Sum('quantity_out'),
        total_waste=Sum('waste'),
        total_stock_value_remaining=Sum('stock_balance_remaining'),
    )
    total_quantity_in = agg.get('total_in') or 0
    total_quantity_out = agg.get('total_out') or 0
    total_waste = agg.get('total_waste') or 0
    total_stock_value_remaining = agg.get('total_stock_value_remaining') or 0
    approval_counts = {
        'draft': qs.filter(approval_status='draft').count(),
        'pending': qs.filter(approval_status='pending').count(),
        'approved': qs.filter(approval_status='approved').count(),
        'rejected': qs.filter(approval_status='rejected').count(),
    }
    currency_symbol = getattr(company, 'currency_symbol', '₦') if company else '₦'
    context = {
        'total_products': total_products,
        'total_quantity_in': total_quantity_in,
        'total_quantity_out': total_quantity_out,
        'total_waste': total_waste,
        'total_stock_value_remaining': total_stock_value_remaining,
        'user_currency_symbol': currency_symbol,
        'approval_counts': approval_counts,
    }
    response = render(request, 'inventory/dashboard.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('inventory.view_inventory', raise_exception=True)
@never_cache
def dashboard_stats_json(request):
    """JSON endpoint for dashboard card stats. No-cache so modals always get fresh counts."""
    company = get_company_profile_for_user(request.user, request)
    currency_symbol = getattr(company, 'currency_symbol', '₦') if company else '₦'
    currency_code = getattr(company, 'currency_code', 'NGN') if company else 'NGN'
    qs = _inventory_queryset(request)
    agg = qs.aggregate(
        total_in=Sum('quantity_in'),
        total_out=Sum('quantity_out'),
        total_waste=Sum('waste'),
        total_balance=Sum('total_amount'),
        total_stock_value_remaining=Sum('stock_balance_remaining'),
    )
    total_balance = agg.get('total_balance')
    if total_balance is None:
        total_balance = 0
    total_stock_value_remaining = agg.get('total_stock_value_remaining')
    if total_stock_value_remaining is None:
        total_stock_value_remaining = 0
    resp = JsonResponse({
        'total_products': qs.count(),
        'total_quantity_in': int(agg.get('total_in') or 0),
        'total_quantity_out': int(agg.get('total_out') or 0),
        'total_waste': int(agg.get('total_waste') or 0),
        'total_balance': float(total_balance),
        'total_stock_value_remaining': float(total_stock_value_remaining),
        'currency_symbol': currency_symbol,
        'currency_code': currency_code,
        'approval_counts': {
            'draft': qs.filter(approval_status='draft').count(),
            'pending': qs.filter(approval_status='pending').count(),
            'approved': qs.filter(approval_status='approved').count(),
            'rejected': qs.filter(approval_status='rejected').count(),
        },
        'stock_counts': {
            'in_stock': qs.filter(stock_status='in_stock').count(),
            'low_stock': qs.filter(stock_status='low_stock').count(),
            'out_of_stock': qs.filter(stock_status='out_of_stock').count(),
        },
    })
    apply_no_cache_headers(resp)
    return resp


@login_required
@company_admin_or_permission_required('inventory.view_inventory', raise_exception=True)
@never_cache
def inventory_list(request):
    """List with search, filter, pagination. Card stats from full dataset; table from filtered.
    GET responses are cacheable by the browser for 60s (pagination, filters) for faster back/forward."""
    company = get_company_profile_for_user(request.user, request)
    base_qs = _inventory_queryset(request).order_by('sn')
    # Card stats + approval/stock counts in 2 queries (was 8+)
    card_agg = base_qs.aggregate(
        total_in=Sum('quantity_in'),
        total_out=Sum('quantity_out'),
        total_waste=Sum('waste'),
        total_balance=Sum('total_amount'),
        total_stock_value_remaining=Sum('stock_balance_remaining'),
    )
    status_counts = base_qs.aggregate(
        total_products=Count('id'),
        draft=Count(Case(When(approval_status='draft', then=1), output_field=IntegerField())),
        pending=Count(Case(When(approval_status='pending', then=1), output_field=IntegerField())),
        approved=Count(Case(When(approval_status='approved', then=1), output_field=IntegerField())),
        rejected=Count(Case(When(approval_status='rejected', then=1), output_field=IntegerField())),
        in_stock=Count(Case(When(stock_status='in_stock', then=1), output_field=IntegerField())),
        low_stock=Count(Case(When(stock_status='low_stock', then=1), output_field=IntegerField())),
        out_of_stock=Count(Case(When(stock_status='out_of_stock', then=1), output_field=IntegerField())),
    )
    approval_counts = {
        'draft': status_counts.get('draft', 0),
        'pending': status_counts.get('pending', 0),
        'approved': status_counts.get('approved', 0),
        'rejected': status_counts.get('rejected', 0),
    }
    stock_counts = {
        'in_stock': status_counts.get('in_stock', 0),
        'low_stock': status_counts.get('low_stock', 0),
        'out_of_stock': status_counts.get('out_of_stock', 0),
    }
    qs = base_qs
    search = (request.GET.get('search') or '').strip()
    approval_status = request.GET.get('approval_status', '').strip()
    stock_status = request.GET.get('stock_status', '').strip()
    workflow_status = request.GET.get('workflow_status', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    metric = (request.GET.get('metric') or '').strip().lower()
    if search:
        # Multi-word: each word must appear in at least one field (AND of terms).
        # Single letter/word: matches any field containing that text (icontains).
        # Search across all text fields + optional S/N for numeric terms.
        terms = [t.strip() for t in search.split() if t.strip()]
        if not terms:
            terms = [search]
        for term in terms:
            q_term = (
                Q(product_name__icontains=term) |
                Q(category__icontains=term) |
                Q(company_name__icontains=term) |
                Q(vendor__icontains=term) |
                Q(stock_location__icontains=term) |
                Q(phone_number__icontains=term) |
                Q(transaction_id__icontains=term) |
                Q(remark__icontains=term)
            )
            try:
                sn_val = int(term)
                q_term = q_term | Q(sn=sn_val)
            except (ValueError, TypeError):
                pass
            qs = qs.filter(q_term)
    if approval_status:
        qs = qs.filter(approval_status=approval_status)
    if stock_status:
        qs = qs.filter(stock_status=stock_status)
    if workflow_status:
        qs = qs.filter(workflow_status=workflow_status)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    # Metric filters from dashboard cards (Quantity In / Out, Waste, balances).
    if metric and metric not in _INVENTORY_STOCK_CATEGORIES and metric not in _INVENTORY_APPROVAL_CATEGORIES:
        qs, _ = _apply_inventory_report_category(qs, metric)
    qs = qs.annotate(
        issue_count=Count('issues'),
        receipt_count=Count('receipts'),
        waste_log_count=Count('waste_logs'),
    )
    paginator = Paginator(qs, INVENTORY_LIST_PAGE_SIZE)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    get_copy = request.GET.copy()
    if 'page' in get_copy:
        get_copy.pop('page', None)
    pagination_base_query = get_copy.urlencode()
    # Currency from company admin settings (so list and AJAX partials use same source)
    currency_symbol = getattr(company, 'currency_symbol', '₦') if company else '₦'
    currency_code = getattr(company, 'currency_code', 'NGN') if company else 'NGN'
    admin_flag = is_company_admin(request.user, request)
    can_approve_inventory = admin_flag or request.user.has_perm('inventory.can_approve_inventory')
    can_change_inventory = admin_flag or request.user.has_perm('inventory.change_inventory')
    context = {
        'page_obj': page_obj,
        'pagination_base_query': pagination_base_query,
        'object_list': page_obj.object_list,
        'total_products': status_counts.get('total_products', 0),
        'total_quantity_in': card_agg.get('total_in') or 0,
        'total_quantity_out': card_agg.get('total_out') or 0,
        'total_waste': card_agg.get('total_waste') or 0,
        'total_balance': card_agg.get('total_balance') or 0,
        'total_stock_value_remaining': card_agg.get('total_stock_value_remaining') or 0,
        'approval_counts': approval_counts,
        'stock_counts': stock_counts,
        'search': search,
        'approval_status': approval_status,
        'stock_status': stock_status,
        'workflow_status': workflow_status,
        'date_from': date_from,
        'date_to': date_to,
        'metric': metric if metric in _INVENTORY_REPORT_CATEGORY_LABELS else '',
        'report_category': _resolve_inventory_report_category(request),
        'report_categories': INVENTORY_REPORT_CATEGORIES,
        'approval_choices': Inventory.APPROVAL_STATUS_CHOICES,
        'stock_choices': Inventory.STOCK_STATUS_CHOICES,
        'workflow_choices': Inventory.WORKFLOW_STATUS_CHOICES,
        'user_currency_symbol': currency_symbol,
        'user_currency_code': currency_code,
        'can_approve_inventory': can_approve_inventory,
        'can_change_inventory': can_change_inventory,
    }
    if request.headers.get('X-Pagination-Ajax') == '1':
        rows_html = render_to_string(
            'inventory/inventory_list_rows_partial.html',
            context,
            request=request,
        )
        pagination_html = render_to_string(
            'inventory/inventory_list_pagination_partial.html',
            context,
            request=request,
        )
        return JsonResponse({'rows_html': rows_html, 'pagination_html': pagination_html})
    response = render(request, 'inventory/inventory_list.html', context)
    response['Cache-Control'] = 'private, max-age=60'
    return response


@login_required
@company_admin_or_permission_required('inventory.add_inventory', raise_exception=True)
@never_cache
def inventory_create(request):
    if request.method == 'POST':
        company = get_company_profile_for_user(request.user, request)
        if not company:
            messages.error(request, 'Company profile is required to create inventory.')
            resp = redirect('inventory:list')
            apply_no_cache_headers(resp)
            return resp
        from .forms import InventoryForm
        form = InventoryForm(request.POST, user=request.user)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.created_by = request.user
            obj.save()
            _clear_inventory_list_cache(request)
            messages.success(request, 'Inventory record created.')
            resp = redirect('inventory:list')
            apply_no_cache_headers(resp)
            return resp
    else:
        from .forms import InventoryForm
        form = InventoryForm(user=request.user)
    response = render(request, 'inventory/inventory_form.html', {'form': form, 'is_edit': False})
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('inventory.change_inventory', raise_exception=True)
@never_cache
def inventory_update(request, pk):
    qs = _inventory_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    if request.method == 'POST':
        from .forms import InventoryForm
        form = InventoryForm(request.POST, instance=obj, user=request.user)
        if form.is_valid():
            form.save()
            _clear_inventory_list_cache(request)
            messages.success(request, 'Inventory updated.')
            resp = redirect('inventory:list')
            apply_no_cache_headers(resp)
            return resp
    else:
        from .forms import InventoryForm
        form = InventoryForm(instance=obj, user=request.user)
    response = render(request, 'inventory/inventory_form.html', {'form': form, 'object': obj, 'is_edit': True})
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('inventory.delete_inventory', raise_exception=True)
@require_POST
def inventory_delete(request, pk):
    qs = _inventory_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    company_id = obj.company_id
    try:
        obj.delete()
    except Exception as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
        messages.error(request, f'Error deleting record: {e}')
        return redirect('inventory:list')
    Inventory.renumber_sn_for_company(company_id)
    _clear_inventory_list_cache(request)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    messages.success(request, 'Inventory record deleted.')
    resp = redirect('inventory:list')
    apply_no_cache_headers(resp)
    return resp


@login_required
@company_admin_or_permission_required('inventory.view_inventory', raise_exception=True)
@never_cache
def inventory_detail(request, pk):
    qs = _inventory_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    context = _inventory_document_context(request, obj)
    response = render(request, 'inventory/inventory_detail.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('inventory.view_inventory', raise_exception=True)
@never_cache
def inventory_product_report(request, pk):
    """Product ledger / report: full movement history for one inventory record with totals."""
    qs = _inventory_queryset(request)
    product = get_object_or_404(qs, pk=pk)
    # Show most recent movements first in the report (newest at the top).
    # Only select columns used by the template/filters to keep this endpoint fast.
    movements = (
        product.movements.all()
        .select_related('created_by')
        .only(
            'id',
            'product_id',
            'created_at',
            'created_by__first_name',
            'created_by__last_name',
            'created_by__email',
            'quantity_in',
            'quantity_out',
            'waste',
            'quantity_after',
            'unit_price',
            'balance',
            'stock_balance_remaining',
            'stock_status',
            'approval_status',
            'remark',
        )
        .order_by('-created_at', '-pk')
    )
    # --- Filters & search for movements (accurate, multi-field) ---
    search = (request.GET.get('search') or '').strip()
    approval_filter = (request.GET.get('approval_status') or '').strip()
    stock_filter = (request.GET.get('stock_status') or '').strip()
    date_from = (request.GET.get('date_from') or '').strip()
    date_to = (request.GET.get('date_to') or '').strip()
    min_quantity = (request.GET.get('min_quantity') or '').strip()
    max_quantity = (request.GET.get('max_quantity') or '').strip()

    if approval_filter and approval_filter in dict(Inventory.APPROVAL_STATUS_CHOICES):
        movements = movements.filter(approval_status=approval_filter)
    if stock_filter and stock_filter in dict(Inventory.STOCK_STATUS_CHOICES):
        movements = movements.filter(stock_status=stock_filter)
    if date_from:
        movements = movements.filter(created_at__date__gte=date_from)
    if date_to:
        movements = movements.filter(created_at__date__lte=date_to)
    if min_quantity:
        try:
            from decimal import Decimal as _D
            movements = movements.filter(quantity_after__gte=_D(str(min_quantity).replace(',', '')))
        except Exception:
            pass
    if max_quantity:
        try:
            from decimal import Decimal as _D
            movements = movements.filter(quantity_after__lte=_D(str(max_quantity).replace(',', '')))
        except Exception:
            pass
    if search:
        # Text search across remarks and creator identity; very forgiving.
        terms = [t.strip() for t in search.split() if t.strip()]
        if not terms:
            terms = [search]
        for term in terms:
            q_term = (
                Q(remark__icontains=term)
                | Q(created_by__first_name__icontains=term)
                | Q(created_by__last_name__icontains=term)
                | Q(created_by__email__icontains=term)
                | Q(approval_status__icontains=term)
                | Q(stock_status__icontains=term)
            )
            movements = movements.filter(q_term)

    issue_recipient = (request.GET.get('issue_recipient') or '').strip()
    issue_date_from = (request.GET.get('issue_date_from') or '').strip()
    issue_date_to = (request.GET.get('issue_date_to') or '').strip()
    receipt_supplier = (request.GET.get('receipt_supplier') or '').strip()
    receipt_date_from = (request.GET.get('receipt_date_from') or '').strip()
    receipt_date_to = (request.GET.get('receipt_date_to') or '').strip()
    waste_reason = (request.GET.get('waste_reason') or '').strip()
    waste_date_from = (request.GET.get('waste_date_from') or '').strip()
    waste_date_to = (request.GET.get('waste_date_to') or '').strip()

    product = prepare_inventory_for_panel(product.pk) or product
    product.refresh_from_db()

    receipts = (
        _inventory_receipt_queryset(request)
        .filter(inventory_id=product.pk)
        .select_related('created_by')
        .order_by('-received_at', '-pk')
    )
    if receipt_supplier:
        receipts = receipts.filter(supplier_name__icontains=receipt_supplier)
    if receipt_date_from:
        receipts = receipts.filter(received_at__date__gte=receipt_date_from)
    if receipt_date_to:
        receipts = receipts.filter(received_at__date__lte=receipt_date_to)

    waste_logs = (
        _inventory_waste_log_queryset(request)
        .filter(inventory_id=product.pk)
        .select_related('created_by')
        .order_by('-waste_date', '-created_at', '-pk')
    )
    if waste_reason and waste_reason in dict(WasteLog.WASTE_REASON_CHOICES):
        waste_logs = waste_logs.filter(reason=waste_reason)
    if waste_date_from:
        waste_logs = waste_logs.filter(waste_date__gte=waste_date_from)
    if waste_date_to:
        waste_logs = waste_logs.filter(waste_date__lte=waste_date_to)

    issues = (
        _inventory_issue_queryset(request)
        .filter(inventory_id=product.pk)
        .select_related('created_by')
        .order_by('-issued_at', '-pk')
    )
    if issue_recipient:
        issues = issues.filter(recipient_name__icontains=issue_recipient)
    if issue_date_from:
        issues = issues.filter(issued_at__date__gte=issue_date_from)
    if issue_date_to:
        issues = issues.filter(issued_at__date__lte=issue_date_to)

    receipts_meta = _receipts_list_payload(product, receipts)[:500]
    waste_meta = _waste_logs_list_payload(product, waste_logs)[:500]
    issues_meta = _issues_list_payload(product, issues)[:500]
    issue_count = getattr(product, 'issue_count', None)
    receipt_count = getattr(product, 'receipt_count', None)
    waste_log_count = getattr(product, 'waste_log_count', None)
    if issue_count is None:
        issue_count = InventoryIssue.objects.filter(inventory_id=product.pk).count()
    if receipt_count is None:
        receipt_count = InventoryReceipt.objects.filter(inventory_id=product.pk).count()
    if waste_log_count is None:
        waste_log_count = WasteLog.objects.filter(inventory_id=product.pk).count()
    # Paginate movements so very long histories don't block page load.
    # 100 rows per page keeps the ledger fast while still showing a rich history.
    paginator = Paginator(movements, 100)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    movements_page = page_obj.object_list

    # Totals match the main inventory row (ledger sums synced via prepare_inventory_for_panel).
    total_qty_in = product.quantity_in
    total_qty_out = product.quantity_out
    total_waste = product.waste
    actual_quantity = product.actual_quantity  # Qty In − Waste
    net_quantity = product.net_quantity  # Qty In − Waste − Qty Out
    balance_quantity = product.balance_quantity  # same as net on list screen
    current_stock = net_quantity
    total_stock_value_remaining = product.stock_balance_remaining
    total_waste_value = product.waste_value

    # Preserve current filters in pagination links (except the page number itself).
    get_copy = request.GET.copy()
    if 'page' in get_copy:
        get_copy.pop('page', None)
    pagination_base_query = get_copy.urlencode()
    company = get_company_profile_for_user(request.user, request)
    currency_symbol = getattr(company, 'currency_symbol', '₦') if company else '₦'
    context = {
        'product': product,
        'movements': movements_page,
        'page_obj': page_obj,
        'pagination_base_query': pagination_base_query,
        'total_qty_in': total_qty_in,
        'total_qty_out': total_qty_out,
        'total_waste': total_waste,
        'actual_quantity': actual_quantity,
        'net_quantity': net_quantity,
        'balance_quantity': balance_quantity,
        'current_stock': current_stock,
        'total_stock_value_remaining': total_stock_value_remaining,
        'total_waste_value': total_waste_value,
        'user_currency_symbol': currency_symbol,
        'stock_formula': 'Net Qty = Quantity In − Waste − Quantity Out',
        'balance_note': 'Balance qty is the available stock (same as Net Qty on the inventory list).',
        'receipts_meta': receipts_meta,
        'waste_meta': waste_meta,
        'issues_meta': issues_meta,
        'issue_count': issue_count,
        'receipt_count': receipt_count,
        'waste_log_count': waste_log_count,
        'waste_reason_choices': WasteLog.WASTE_REASON_CHOICES,
        'receipt_supplier': receipt_supplier,
        'receipt_date_from': receipt_date_from,
        'receipt_date_to': receipt_date_to,
        'waste_reason': waste_reason,
        'waste_date_from': waste_date_from,
        'waste_date_to': waste_date_to,
        'approval_choices': Inventory.APPROVAL_STATUS_CHOICES,
        'stock_choices': Inventory.STOCK_STATUS_CHOICES,
        'search': search,
        'approval_status_filter': approval_filter,
        'stock_status_filter': stock_filter,
        'date_from': date_from,
        'date_to': date_to,
        'min_quantity': min_quantity,
        'max_quantity': max_quantity,
        'issues': issues[:500],
        'issue_recipient': issue_recipient,
        'issue_date_from': issue_date_from,
        'issue_date_to': issue_date_to,
    }
    # AJAX refresh (for realtime-like updates without full page reload)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' and request.GET.get('format') == 'json':
        rows_html = render_to_string(
            'inventory/product_report_rows_partial.html',
            context,
            request=request,
        )
        issues_html = render_to_string(
            'inventory/product_report_issues_partial.html',
            {'issues_meta': issues_meta},
            request=request,
        )
        receipts_html = render_to_string(
            'inventory/product_report_receipts_partial.html',
            {'receipts_meta': receipts_meta},
            request=request,
        )
        waste_html = render_to_string(
            'inventory/product_report_waste_partial.html',
            {'waste_meta': waste_meta},
            request=request,
        )
        resp = JsonResponse({
            'success': True,
            'rows_html': rows_html,
            'issues_html': issues_html,
            'receipts_html': receipts_html,
            'waste_html': waste_html,
            'issue_count': issue_count,
            'receipt_count': receipt_count,
            'waste_log_count': waste_log_count,
            'total_qty_in': str(total_qty_in),
            'total_qty_out': str(total_qty_out),
            'total_waste': str(total_waste),
            'actual_quantity': str(actual_quantity),
            'net_quantity': str(net_quantity),
            'balance_quantity': str(balance_quantity),
            'current_stock': str(current_stock),
            'total_stock_value_remaining': str(total_stock_value_remaining),
            'total_waste_value': str(total_waste_value),
            'waste': str(product.waste),
            'waste_value': str(product.waste_value),
            'total_amount': str(product.total_amount),
            'unit_price': str(product.unit_price),
            'low_stock_threshold': str(product.low_stock_threshold),
            'approval_status': getattr(product, 'approval_status', ''),
            'approval_status_display': product.get_approval_status_display() if product else '',
            'stock_status': getattr(product, 'stock_status', ''),
            'stock_status_display': product.get_stock_status_display() if product else '',
            'quantity_in_input': getattr(product, 'quantity_in_input', ''),
            'quantity_out_input': getattr(product, 'quantity_out_input', ''),
            'unit_price_input': getattr(product, 'unit_price_input', ''),
            'low_stock_threshold_input': getattr(product, 'low_stock_threshold_input', ''),
            'unit_label': getattr(product, 'unit_label', ''),
        })
        apply_no_cache_headers(resp)
        return resp
    response = render(request, 'inventory/product_report.html', context)
    apply_no_cache_headers(response)
    return response


def _remap_created_at_date_filters(filter_kwargs, field_name, *, is_date_field=False):
    """
    Remap _parse_inventory_list_date_range kwargs (created_at__date*) onto another field.
    DateTime fields use field__date__gte; DateFields use field__gte.
    """
    out = {}
    for key, val in (filter_kwargs or {}).items():
        if key == 'created_at__date':
            out[field_name if is_date_field else f'{field_name}__date'] = val
        elif key.startswith('created_at__date__'):
            suffix = key[len('created_at__date'):]  # __gte / __lte
            if is_date_field:
                out[f'{field_name}{suffix}'] = val
            else:
                out[f'{field_name}__date{suffix}'] = val
    return out


def _product_report_print_context(request, pk):
    """Full product ledger context for print/PDF (no pagination), with optional date range."""
    qs = _inventory_queryset(request)
    product = get_object_or_404(qs, pk=pk)
    product = prepare_inventory_for_panel(product.pk) or product
    product.refresh_from_db()

    filter_kwargs, date_label = _parse_inventory_list_date_range(request)

    movements = (
        product.movements.all()
        .select_related('created_by')
        .order_by('-created_at', '-pk')
    )
    if filter_kwargs:
        movements = movements.filter(**filter_kwargs)

    receipts = (
        _inventory_receipt_queryset(request)
        .filter(inventory_id=product.pk)
        .select_related('created_by')
        .order_by('-received_at', '-pk')
    )
    waste_logs = (
        _inventory_waste_log_queryset(request)
        .filter(inventory_id=product.pk)
        .select_related('created_by')
        .order_by('-waste_date', '-created_at', '-pk')
    )
    issues = (
        _inventory_issue_queryset(request)
        .filter(inventory_id=product.pk)
        .select_related('created_by')
        .order_by('-issued_at', '-pk')
    )
    if filter_kwargs:
        receipts = receipts.filter(**_remap_created_at_date_filters(filter_kwargs, 'received_at'))
        waste_logs = waste_logs.filter(**_remap_created_at_date_filters(filter_kwargs, 'waste_date', is_date_field=True))
        issues = issues.filter(**_remap_created_at_date_filters(filter_kwargs, 'issued_at'))

    receipts_meta = _receipts_list_payload(product, receipts)[:2000]
    waste_meta = _waste_logs_list_payload(product, waste_logs)[:2000]
    issues_meta = _issues_list_payload(product, issues)[:2000]
    movements_list = list(movements[:2000])

    company = get_company_profile_for_user(request.user, request)
    company_logo = None
    if company and getattr(company, 'logo', None) and company.logo:
        company_logo = company.logo.url
    currency_symbol = getattr(company, 'currency_symbol', '₦') if company else '₦'

    return {
        'product': product,
        'movements': movements_list,
        'receipts_meta': receipts_meta,
        'waste_meta': waste_meta,
        'issues_meta': issues_meta,
        'receipt_count': len(receipts_meta),
        'waste_log_count': len(waste_meta),
        'issue_count': len(issues_meta),
        'date_label': date_label,
        'report_period_label': date_label,
        'company_profile': company,
        'company_logo': company_logo,
        'theme_primary_color': getattr(company, 'primary_color', '#1976d2') if company else '#1976d2',
        'theme_secondary_color': getattr(company, 'secondary_color', '#f8f9fa') if company else '#f8f9fa',
        'theme_accent_color': getattr(company, 'accent_color', '#e9ecef') if company else '#e9ecef',
        'theme_text_color': getattr(company, 'text_color', '#333333') if company else '#333333',
        'user_currency_symbol': currency_symbol,
        'stock_formula': 'Net Qty = Quantity In − Waste − Quantity Out',
        'total_qty_in': product.quantity_in,
        'total_qty_out': product.quantity_out,
        'total_waste': product.waste,
        'actual_quantity': product.actual_quantity,
        'net_quantity': product.net_quantity,
        'balance_quantity': product.balance_quantity,
        'total_stock_value_remaining': product.stock_balance_remaining,
        'total_waste_value': product.waste_value,
    }


@login_required
@company_admin_or_permission_required('inventory.print_inventory', raise_exception=True)
@never_cache
def inventory_product_report_print(request, pk):
    """Printable product ledger/report (A4), optional date range. Same layout as Save as PDF."""
    context = _product_report_print_context(request, pk)
    response = render(request, 'inventory/product_report_print.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('inventory.download_inventory', raise_exception=True)
@never_cache
def inventory_product_report_pdf(request, pk):
    """Download product ledger/report as PDF (falls back to print view if WeasyPrint missing)."""
    context = _product_report_print_context(request, pk)
    try:
        from django.template.loader import get_template
        from weasyprint import HTML
        if context.get('company_logo'):
            context['company_logo'] = request.build_absolute_uri(context['company_logo'])
        template = get_template('inventory/product_report_print.html')
        html_str = template.render(context, request)
        html = HTML(string=html_str)
        pdf_file = html.write_pdf()
        product = context['product']
        slug = (product.product_name or f'product-{pk}')[:40].replace(' ', '-')
        filename = f"product-report-{slug}-{timezone.now().strftime('%Y%m%d-%H%M')}.pdf"
        response = HttpResponse(pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        apply_no_cache_headers(response)
        return response
    except ImportError:
        from django.urls import reverse
        url = reverse('inventory:product_report_print', args=[pk])
        if request.GET:
            url += '?' + request.GET.urlencode()
        return redirect(url)


@login_required
@company_admin_or_permission_required('inventory.print_inventory', raise_exception=True)
@never_cache
def inventory_print(request, pk):
    qs = _inventory_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    context = _inventory_document_context(request, obj)
    response = render(request, 'inventory/inventory_print.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('inventory.download_inventory', raise_exception=True)
@never_cache
def inventory_pdf(request, pk):
    qs = _inventory_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    try:
        from django.template.loader import get_template
        from weasyprint import HTML
        context = _inventory_document_context(request, obj)
        if context.get('company_logo'):
            context['company_logo'] = request.build_absolute_uri(context['company_logo'])
        template = get_template('inventory/inventory_print.html')
        html_str = template.render(context, request)
        html = HTML(string=html_str)
        pdf_file = html.write_pdf()
        response = HttpResponse(pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="inventory-{obj.transaction_id}.pdf"'
        apply_no_cache_headers(response)
        return response
    except ImportError:
        resp = redirect('inventory:print', pk=pk)
        apply_no_cache_headers(resp)
        return resp


@login_required
@company_admin_or_permission_required('inventory.print_inventory', raise_exception=True)
@never_cache
def inventory_list_print(request):
    """Print inventory table with optional category (dashboard cards) + date range. Company details + logo, no signature."""
    qs = _inventory_queryset(request).order_by('sn')
    category = _resolve_inventory_report_category(request)
    qs, category_label = _apply_inventory_report_category(qs, category)
    filter_kwargs, date_label = _parse_inventory_list_date_range(request)
    if filter_kwargs:
        qs = qs.filter(**filter_kwargs)
    object_list = list(qs)
    context = _inventory_list_document_context(request, object_list, date_label, category_label)
    context['approval_choices'] = Inventory.APPROVAL_STATUS_CHOICES
    response = render(request, 'inventory/inventory_list_print.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('inventory.download_inventory', raise_exception=True)
@never_cache
def inventory_list_pdf(request):
    """Download inventory table as PDF with optional category + date range. Same layout as print (A4, text wrap)."""
    qs = _inventory_queryset(request).order_by('sn')
    category = _resolve_inventory_report_category(request)
    qs, category_label = _apply_inventory_report_category(qs, category)
    filter_kwargs, date_label = _parse_inventory_list_date_range(request)
    if filter_kwargs:
        qs = qs.filter(**filter_kwargs)
    object_list = list(qs)
    try:
        from django.template.loader import get_template
        from weasyprint import HTML
        context = _inventory_list_document_context(request, object_list, date_label, category_label)
        context['approval_choices'] = Inventory.APPROVAL_STATUS_CHOICES
        if context.get('company_logo'):
            context['company_logo'] = request.build_absolute_uri(context['company_logo'])
        template = get_template('inventory/inventory_list_print.html')
        html_str = template.render(context, request)
        html = HTML(string=html_str)
        pdf_file = html.write_pdf()
        slug = category if category != 'all' else 'all'
        filename = f"inventory-{slug}-{timezone.now().strftime('%Y%m%d-%H%M')}.pdf"
        response = HttpResponse(pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        apply_no_cache_headers(response)
        return response
    except ImportError:
        from django.urls import reverse
        url = reverse('inventory:list_print') + ('?' + request.GET.urlencode() if request.GET else '')
        return redirect(url)


# ----- AJAX: auto-save on blur (spreadsheet-like UX) -----

@login_required
@company_admin_or_permission_required('inventory.add_inventory', raise_exception=True)
@require_POST
def ajax_create(request):
    """Create one inventory record from POST (table Add row). Returns JSON for row insert."""
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return JsonResponse({'success': False, 'message': 'Company profile is required.'}, status=400)
    from decimal import Decimal
    from .forms import InventoryForm
    data = {
        'product_name': (request.POST.get('product_name') or '').strip() or None,
        'category': (request.POST.get('category') or '').strip() or '',
        'company_name': (request.POST.get('company_name') or '').strip() or '',
        'vendor': (request.POST.get('vendor') or '').strip() or '',
        'stock_location': (request.POST.get('stock_location') or '').strip() or '',
        'phone_number': (request.POST.get('phone_number') or '').strip() or '',
        'quantity_in': request.POST.get('quantity_in', '0'),
        'quantity_out': request.POST.get('quantity_out', '0'),
        'unit_price': request.POST.get('unit_price', '0'),
        'remark': (request.POST.get('remark') or '').strip() or '',
        'approval_status': 'draft',
        'workflow_status': 'draft',
        'low_stock_threshold': request.POST.get('low_stock_threshold', '10'),
    }
    if not data['product_name']:
        return JsonResponse({'success': False, 'message': 'Product name is required.'}, status=400)
    form = InventoryForm(data, user=request.user)
    if not form.is_valid():
        err = next(iter(form.errors.values()), ['Invalid data'])[0]
        return JsonResponse({'success': False, 'message': err}, status=400)
    obj = form.save(commit=False)
    obj.created_by = request.user
    if not obj.account_id:
        acc = get_account_for_user(request.user)
        if acc:
            obj.account_id = acc.id
    if not obj.company_id:
        obj.company_id = company.id
    obj.save()
    _clear_inventory_list_cache(request)
    created_by_display = (obj.created_by.get_full_name() or obj.created_by.email or '—') if obj.created_by else '—'
    resp = JsonResponse({
        'success': True,
        'id': obj.pk,
        'sn': obj.sn,
        'transaction_id': obj.transaction_id,
        'product_name': obj.product_name,
        'category': obj.category or '',
        'company_name': (obj.company_name or '').strip(),
        'vendor': obj.vendor or '',
        'stock_location': obj.stock_location or '',
        'phone_number': obj.phone_number or '',
        'quantity_in': str(obj.quantity_in),
        'quantity_out': str(obj.quantity_out),
        'remaining_quantity': str(obj.remaining_quantity),
        'unit_price': str(obj.unit_price),
        'total_amount': str(obj.total_amount),
        'stock_balance_remaining': str(obj.stock_balance_remaining),
        'balance_quantity': str(obj.balance_quantity),
        'stock_status': obj.stock_status,
        'stock_status_display': obj.get_stock_status_display(),
        'approval_status': obj.approval_status,
        'approval_status_display': obj.get_approval_status_display(),
        'remark': (obj.remark or '')[:50],
        'low_stock_threshold': str(obj.low_stock_threshold),
        # Include raw input strings so UI can show mixed text+numbers immediately.
        'quantity_in_input': getattr(obj, 'quantity_in_input', ''),
        'quantity_out_input': getattr(obj, 'quantity_out_input', ''),
        'unit_price_input': getattr(obj, 'unit_price_input', ''),
        'low_stock_threshold_input': getattr(obj, 'low_stock_threshold_input', ''),
        'unit_label': getattr(obj, 'unit_label', '') or '',
        'created_by_display': created_by_display,
        'created_at': obj.created_at.strftime('%Y-%m-%d %I:%M:%S %p'),
    })
    resp['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    return resp


@login_required
@company_admin_or_permission_required('inventory.change_inventory', raise_exception=True)
@require_POST
def ajax_update_field(request):
    """Update a single field; recalc on backend; return JSON. No page reload.
    Full save() recomputes balance_quantity and stock_status (IN STOCK / LOW / OUT)
    so the response always returns current stock_status_display for the badge."""
    pk = request.POST.get('id') or request.POST.get('pk')
    field = (request.POST.get('field') or '').strip()
    value = request.POST.get('value', '')
    if not pk or not field:
        return JsonResponse({'success': False, 'message': 'Missing id or field'}, status=400)
    qs = _inventory_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    editable = {'product_name', 'category', 'company_name', 'vendor', 'stock_location', 'phone_number',
                'quantity_in', 'quantity_out', 'waste', 'unit_price', 'low_stock_threshold',
                'approval_status', 'workflow_status', 'remark'}
    if field not in editable:
        return JsonResponse({'success': False, 'message': 'Field not editable'}, status=400)
    if field in ('quantity_in', 'quantity_out', 'waste', 'unit_price', 'low_stock_threshold'):
        from decimal import Decimal
        raw_text = str(value)
        # Store the original mixed text on the *_input fields so it persists.
        if field == 'quantity_in':
            if InventoryReceipt.objects.filter(inventory_id=obj.pk).exists():
                return JsonResponse({
                    'success': False,
                    'message': (
                        'Quantity In is managed by stock receipts. '
                        'Use "Receive stock" to add each delivery, or delete receipts first to edit manually.'
                    ),
                }, status=400)
            obj.quantity_in_input = raw_text
        elif field == 'quantity_out':
            if InventoryIssue.objects.filter(inventory_id=obj.pk).exists():
                return JsonResponse({
                    'success': False,
                    'message': (
                        'Quantity Out is managed by stock issues. '
                        'Use "Issue stock" to record each withdrawal, or delete issues first to edit manually.'
                    ),
                }, status=400)
            obj.quantity_out_input = raw_text
        elif field == 'waste':
            if WasteLog.objects.filter(inventory_id=obj.pk).exists():
                return JsonResponse({
                    'success': False,
                    'message': (
                        'Waste is managed by waste logs. '
                        'Use "Record waste" for each incident, or delete waste logs first to edit manually.'
                    ),
                }, status=400)
        elif field == 'unit_price':
            obj.unit_price_input = normalize_unit_price_input(raw_text)
        elif field == 'low_stock_threshold':
            obj.low_stock_threshold_input = raw_text

        # Parse out the numeric portion using the shared quantity parser.
        try:
            # Empty threshold = keep current value so we don't accidentally set 0
            if field == 'low_stock_threshold' and (not raw_text or str(raw_text).strip() == ''):
                value = getattr(obj, 'low_stock_threshold', Decimal('10'))
            else:
                numeric = extract_numeric_value(raw_text)
                value = Decimal(str(numeric))
                # For price/threshold/waste, guard against negative values.
                if field in ('unit_price', 'low_stock_threshold', 'waste') and value < 0:
                    value = Decimal('0')
        except Exception:
            # Fall back to existing value so we never accidentally zero threshold
            # (which would make every positive balance show "In Stock").
            if field == 'low_stock_threshold':
                value = getattr(obj, 'low_stock_threshold', Decimal('10'))
            elif field == 'unit_price':
                value = getattr(obj, 'unit_price', Decimal('0'))
            else:
                value = getattr(obj, field, Decimal('0'))
        if field == 'quantity_out':
            cap = _decimal_safe(obj.quantity_in) - _decimal_safe(obj.waste)
            if value > cap:
                return JsonResponse({
                    'success': False,
                    'message': over_issue_message(value, cap, obj.quantity_in, obj.waste),
                }, status=400)
        elif field == 'quantity_in':
            committed = _decimal_safe(obj.quantity_out) + _decimal_safe(obj.waste)
            if value < committed:
                return JsonResponse({
                    'success': False,
                    'message': (
                        f'Quantity in cannot be less than quantity already taken out plus waste '
                        f'({format_quantity_number(committed)}). Add more stock, or reduce withdrawals first.'
                    ),
                }, status=400)
        elif field == 'waste':
            cap = _decimal_safe(obj.quantity_in) - _decimal_safe(obj.quantity_out)
            if value > cap:
                return JsonResponse({
                    'success': False,
                    'message': over_waste_message(value, cap, obj.quantity_in),
                }, status=400)
    if field in ('approval_status', 'workflow_status'):
        # Only company admin or users with explicit approval permission may
        # change approval/workflow status via this generic field updater.
        if not (is_company_admin(request.user, request) or request.user.has_perm('inventory.can_approve_inventory')):
            return JsonResponse(
                {'success': False, 'message': 'You do not have permission to approve inventory records.'},
                status=403,
            )
        if field == 'approval_status' and value not in dict(Inventory.APPROVAL_STATUS_CHOICES):
            value = obj.approval_status
        elif field == 'workflow_status' and value not in dict(Inventory.WORKFLOW_STATUS_CHOICES):
            value = obj.workflow_status
    setattr(obj, field, value)
    obj.save()
    obj = sync_inventory_row(obj.pk, repair=True)
    _clear_inventory_list_cache(request)
    resp_data = {
        'success': True,
        'remaining_quantity': str(obj.remaining_quantity),
        'actual_quantity': str(obj.actual_quantity),
        'net_quantity': str(obj.net_quantity),
        'total_amount': _money_str(obj.total_amount),
        'stock_balance_remaining': _money_str(obj.stock_balance_remaining),
        'balance_quantity': str(obj.balance_quantity),
        'waste': str(obj.waste),
        'waste_value': _money_str(obj.waste_value),
        'stock_status': obj.stock_status,
        'stock_status_display': obj.get_stock_status_display(),
        'unit_price': _money_str(obj.unit_price),
        'quantity_in': str(obj.quantity_in),
        'quantity_out': str(obj.quantity_out),
        'low_stock_threshold': str(obj.low_stock_threshold),
        # Echo back the raw mixed-input text so the frontend can keep showing
        # exactly what the user typed even after recomputations.
        'quantity_in_input': getattr(obj, 'quantity_in_input', ''),
        'quantity_out_input': getattr(obj, 'quantity_out_input', ''),
        'unit_price_input': getattr(obj, 'unit_price_input', ''),
        'low_stock_threshold_input': getattr(obj, 'low_stock_threshold_input', ''),
        'unit_label': getattr(obj, 'unit_label', '') or '',
    }
    if field in ('approval_status', 'workflow_status'):
        resp_data['approval_status'] = obj.approval_status
        resp_data['approval_status_display'] = obj.get_approval_status_display()
        resp_data['workflow_status'] = obj.workflow_status
        resp_data['workflow_status_display'] = obj.get_workflow_status_display()
    resp = JsonResponse(resp_data)
    apply_no_cache_headers(resp)
    return resp


@login_required
@company_admin_or_permission_required('inventory.can_approve_inventory', raise_exception=True)
@require_POST
def ajax_status_update(request):
    """Update approval_status and/or workflow_status; return JSON. Persists to DB immediately."""
    raw_pk = request.POST.get('id') or request.POST.get('pk')
    if not raw_pk:
        return JsonResponse({'success': False, 'message': 'Missing id'}, status=400)
    try:
        pk = int(raw_pk)
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'message': 'Invalid id'}, status=400)
    approval = (request.POST.get('approval_status') or '').strip()
    workflow = (request.POST.get('workflow_status') or '').strip()
    qs = _inventory_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    if approval and approval in dict(Inventory.APPROVAL_STATUS_CHOICES):
        obj.approval_status = approval
        if approval == 'approved':
            obj.approved_by = request.user
            obj.approved_at = timezone.now()
        else:
            obj.approved_by = None
            obj.approved_at = None
    if workflow and workflow in dict(Inventory.WORKFLOW_STATUS_CHOICES):
        obj.workflow_status = workflow
    save_fields = ['approval_status', 'workflow_status', 'updated_at']
    if approval and approval in dict(Inventory.APPROVAL_STATUS_CHOICES):
        save_fields.extend(['approved_by', 'approved_at'])
    obj.save(update_fields=save_fields)
    _clear_inventory_list_cache(request)
    resp = JsonResponse({
        'success': True,
        'approval_status': obj.approval_status,
        'approval_status_display': obj.get_approval_status_display(),
        'workflow_status': obj.workflow_status,
        'workflow_status_display': obj.get_workflow_status_display(),
    })
    resp['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    return resp


def _waste_log_queryset(request):
    """Queryset for current user: account-scoped, exclude soft-deleted."""
    base = for_user_queryset(
        WasteLog, request.user, request, account_lookup='account'
    ).select_related('inventory', 'created_by')
    account = get_account_for_user(request.user)
    company = get_company_profile_for_user(request.user, request)
    if account and company:
        from django.db.models import Q
        extra = WasteLog.objects.filter(account__isnull=True, company=company).select_related('inventory', 'created_by')
        base = (base | extra).distinct()
    elif not account and company:
        base = WasteLog.objects.filter(company=company).select_related('inventory', 'created_by')
    return base


@login_required
@company_admin_or_permission_required('inventory.view_inventory', raise_exception=True)
@never_cache
def waste_list(request):
    """List all waste logs with filtering by inventory, reason, date range."""
    company = get_company_profile_for_user(request.user, request)
    currency_symbol = getattr(company, 'currency_symbol', '₦') if company else '₦'
    base_qs = _waste_log_queryset(request)
    
    waste_reason = request.GET.get('reason', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    inventory_id = request.GET.get('inventory', '').strip()
    search = request.GET.get('search', '').strip()
    
    qs = base_qs
    if waste_reason:
        qs = qs.filter(reason=waste_reason)
    if date_from:
        qs = qs.filter(waste_date__gte=date_from)
    if date_to:
        qs = qs.filter(waste_date__lte=date_to)
    if inventory_id:
        qs = qs.filter(inventory_id=inventory_id)
    if search:
        qs = qs.filter(
            Q(inventory__product_name__icontains=search) |
            Q(description__icontains=search)
        )
    
    paginator = Paginator(qs, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    waste_agg = base_qs.aggregate(
        total_qty=Sum('quantity'),
        total_value=Sum('total_value'),
    )
    
    context = {
        'page_obj': page_obj,
        'object_list': page_obj.object_list,
        'waste_choices': WasteLog.WASTE_REASON_CHOICES,
        'inventory_list': Inventory.objects.filter(
            company=company, is_deleted=False
        ).order_by('product_name') if company else [],
        'total_waste_qty': waste_agg.get('total_qty') or 0,
        'total_waste_value': waste_agg.get('total_value') or 0,
        'waste_reason': waste_reason,
        'date_from': date_from,
        'date_to': date_to,
        'search': search,
        'user_currency_symbol': currency_symbol,
    }
    response = render(request, 'inventory/waste_log_list.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('inventory.view_inventory', raise_exception=True)
@never_cache
def waste_create(request):
    """Create a new waste log entry."""
    company = get_company_profile_for_user(request.user, request)
    if request.method == 'POST':
        from .forms import WasteLogForm
        form = WasteLogForm(request.POST, user=request.user, company=company)
        if form.is_valid():
            waste_log = form.save()
            messages.success(request, f'Waste log created: {waste_log.quantity} of {waste_log.inventory.product_name}.')
            resp = redirect('inventory:waste_list')
            apply_no_cache_headers(resp)
            return resp
    else:
        from .forms import WasteLogForm
        initial_inventory = request.GET.get('inventory', '')
        form = WasteLogForm(user=request.user, company=company)
        if initial_inventory:
            try:
                inv = Inventory.objects.get(pk=initial_inventory, is_deleted=False)
                form.fields['inventory'].queryset = Inventory.objects.filter(pk=initial_inventory)
                form.initial['inventory'] = inv
            except Inventory.DoesNotExist:
                pass
    response = render(request, 'inventory/waste_log_form.html', {'form': form, 'is_edit': False})
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('inventory.delete_inventory', raise_exception=True)
@require_POST
def waste_delete(request, pk):
    """Delete a waste log entry."""
    qs = _waste_log_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    inventory_name = obj.inventory.product_name
    obj.delete()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    messages.success(request, f'Waste log for {inventory_name} deleted.')
    resp = redirect('inventory:waste_list')
    apply_no_cache_headers(resp)
    return resp


@login_required
@company_admin_or_permission_required('inventory.view_inventory', raise_exception=True)
@never_cache
def waste_stats_json(request):
    """JSON endpoint for waste stats."""
    company = get_company_profile_for_user(request.user, request)
    currency_symbol = getattr(company, 'currency_symbol', '₦') if company else '₦'
    qs = _waste_log_queryset(request)
    
    waste_by_reason = {}
    for reason_code, reason_label in WasteLog.WASTE_REASON_CHOICES:
        agg = qs.filter(reason=reason_code).aggregate(
            total_qty=Sum('quantity'),
            total_value=Sum('total_value'),
        )
        waste_by_reason[reason_code] = {
            'label': reason_label,
            'quantity': float(agg.get('total_qty') or 0),
            'value': float(agg.get('total_value') or 0),
        }
    
    agg = qs.aggregate(
        total_qty=Sum('quantity'),
        total_value=Sum('total_value'),
    )
    
    resp = JsonResponse({
        'total_waste_qty': float(agg.get('total_qty') or 0),
        'total_waste_value': float(agg.get('total_value') or 0),
        'waste_by_reason': waste_by_reason,
        'currency_symbol': currency_symbol,
    })
    apply_no_cache_headers(resp)
    return resp


def _accessible_inventory_pks(request):
    """Primary keys of inventory rows the current user may view."""
    return list(_inventory_queryset(request).values_list('pk', flat=True))


def _inventory_issue_queryset(request):
    """Issues on inventory rows the current user can access (not limited to created_by)."""
    pks = _accessible_inventory_pks(request)
    qs = InventoryIssue.objects.select_related('inventory', 'created_by')
    if not pks:
        return qs.none()
    return qs.filter(inventory_id__in=pks)


def _money_str(amount):
    """Two-decimal string for JSON money fields."""
    return f'{_decimal_safe(amount):.2f}'


def _inventory_row_response(obj):
    """JSON fields for updating a list row after quantity changes."""
    return {
        'success': True,
        'remaining_quantity': str(obj.remaining_quantity),
        'actual_quantity': str(obj.actual_quantity),
        'net_quantity': str(obj.net_quantity),
        'total_amount': _money_str(obj.total_amount),
        'stock_balance_remaining': _money_str(obj.stock_balance_remaining),
        'balance_quantity': str(obj.balance_quantity),
        'waste': str(obj.waste),
        'waste_value': _money_str(obj.waste_value),
        'stock_status': obj.stock_status,
        'stock_status_display': obj.get_stock_status_display(),
        'unit_price': _money_str(obj.unit_price),
        'quantity_in': str(obj.quantity_in),
        'quantity_out': str(obj.quantity_out),
        'quantity_in_input': _quantity_in_input_display(obj),
        'quantity_out_input': _quantity_out_input_display(obj),
        'waste_input': _waste_total_input_display(obj),
        'unit_price_input': getattr(obj, 'unit_price_input', ''),
        'unit_label': getattr(obj, 'unit_label', '') or '',
        'available': str(obj.net_quantity),
        'has_issues': InventoryIssue.objects.filter(inventory_id=obj.pk).exists(),
        'has_receipts': InventoryReceipt.objects.filter(inventory_id=obj.pk).exists(),
        'has_waste_logs': WasteLog.objects.filter(inventory_id=obj.pk).exists(),
    }


def _serialize_issue(issue, remaining_after=None, unit_label=''):
    issued = timezone.localtime(issue.issued_at) if timezone.is_aware(issue.issued_at) else issue.issued_at
    user = issue.created_by
    rem_text = ''
    if remaining_after is not None:
        rem_text = str(remaining_after)
        if unit_label:
            rem_text += f' {unit_label}'
    is_legacy = (issue.remark or '') == LEGACY_ISSUE_REMARK
    line_val = getattr(issue, 'line_value', None)
    if line_val is None:
        line_val = _decimal_safe(issue.quantity) * _decimal_safe(issue.unit_price)
    return {
        'id': issue.pk,
        'quantity': str(issue.quantity),
        'quantity_input': issue.quantity_input or str(issue.quantity),
        'unit_price': _money_str(issue.unit_price),
        'line_value': _money_str(line_val),
        'recipient_name': issue.recipient_name or '',
        'issued_at': issued.strftime('%Y-%m-%d'),
        'issued_time': issued.strftime('%H:%M'),
        'issued_at_display': issued.strftime('%Y-%m-%d %I:%M %p'),
        'remark': issue.remark or '',
        'created_by': (user.get_full_name() or user.email or '—') if user else '—',
        'remaining_after': rem_text,
        'is_legacy': is_legacy,
        'inventory_id': issue.inventory_id,
    }


def _parse_issued_datetime(date_str, time_str):
    """Parse optional date/time fields into an aware datetime."""
    issued_at = timezone.now()
    date_str = (date_str or '').strip()
    time_str = (time_str or '').strip()
    if not date_str:
        return issued_at
    from datetime import datetime as dt
    try:
        if time_str:
            issued_at = dt.strptime(f'{date_str} {time_str}', '%Y-%m-%d %H:%M')
        else:
            issued_at = dt.strptime(date_str, '%Y-%m-%d')
        if timezone.is_naive(issued_at):
            issued_at = timezone.make_aware(issued_at, timezone.get_current_timezone())
    except ValueError:
        raise ValueError('Invalid date or time.')
    return issued_at


def _issues_list_payload(inv, issues_qs):
    """Build issue list with remaining stock after each withdrawal (chronological)."""
    from decimal import Decimal as D
    if isinstance(issues_qs, list):
        ordered = sorted(issues_qs, key=lambda i: (i.issued_at, i.pk))
        display_issues = sorted(issues_qs, key=lambda i: (i.issued_at, i.pk), reverse=True)
    else:
        ordered = list(issues_qs.order_by('issued_at', 'pk'))
        display_issues = list(reversed(ordered))
    cap = D(str(inv.quantity_in)) - D(str(inv.waste))
    cumulative = D('0')
    remaining_by_pk = {}
    for issue in ordered:
        cumulative += D(str(issue.quantity))
        remaining_by_pk[issue.pk] = max(D('0'), cap - cumulative)
    unit = inv.unit_label or ''
    items = []
    for issue in display_issues:
        items.append(_serialize_issue(
            issue,
            remaining_after=remaining_by_pk.get(issue.pk, cap),
            unit_label=unit,
        ))
    return items


@login_required
@company_admin_or_permission_required('inventory.view_inventory', raise_exception=True)
@require_GET
def ajax_issue_list(request):
    """List stock issues for one inventory row (for history modal / report)."""
    pk = request.GET.get('inventory') or request.GET.get('id') or request.GET.get('pk')
    if not pk:
        return JsonResponse({'success': False, 'message': 'Missing inventory id'}, status=400)
    inv = get_object_or_404(_inventory_queryset(request), pk=pk)
    try:
        inv = prepare_inventory_for_panel(inv.pk) or inv
    except Exception as exc:
        return JsonResponse({'success': False, 'message': str(exc)}, status=400)
    issues = _inventory_issue_queryset(request).filter(inventory_id=inv.pk)
    recipient = (request.GET.get('recipient') or '').strip()
    date_from = (request.GET.get('date_from') or '').strip()
    date_to = (request.GET.get('date_to') or '').strip()
    if recipient:
        issues = issues.filter(recipient_name__icontains=recipient)
    search = (request.GET.get('search') or '').strip()
    if search:
        issues = issues.filter(
            Q(recipient_name__icontains=search)
            | Q(quantity_input__icontains=search)
            | Q(remark__icontains=search)
        )
    if date_from:
        issues = issues.filter(issued_at__date__gte=date_from)
    if date_to:
        issues = issues.filter(issued_at__date__lte=date_to)
    items = _issues_list_payload(inv, issues)[:500]
    issue_count = getattr(inv, 'issue_count', None)
    if issue_count is None:
        issue_count = InventoryIssue.objects.filter(inventory_id=inv.pk).count()
    needs_opening = issue_count == 0 and _decimal_safe(inv.quantity_out) > 0
    data = {
        'success': True,
        'issues': items,
        'issue_count': issue_count,
        'needs_opening_import': needs_opening,
        'opening_quantity': inv.quantity_out_input or str(inv.quantity_out),
        'available': str(inv.net_quantity),
        'product_name': inv.product_name,
        'has_issues': issue_count > 0,
    }
    _enrich_stock_panel_totals(data, inv)
    resp = JsonResponse(data)
    apply_no_cache_headers(resp)
    return resp


@login_required
@company_admin_or_permission_required('inventory.change_inventory', raise_exception=True)
@require_POST
def ajax_issue_create(request):
    """Record one stock withdrawal; totals update automatically."""
    pk = request.POST.get('inventory') or request.POST.get('id') or request.POST.get('pk')
    if not pk:
        return JsonResponse({'success': False, 'message': 'Missing inventory id'}, status=400)
    inv = get_object_or_404(_inventory_queryset(request), pk=pk)
    qty_raw = (request.POST.get('quantity') or request.POST.get('quantity_input') or '').strip()
    if not qty_raw:
        return JsonResponse({'success': False, 'message': 'Quantity is required.'}, status=400)
    qty_raw = normalize_quantity_input(qty_raw)
    recipient = (request.POST.get('recipient_name') or request.POST.get('recipient') or '').strip()
    remark = (request.POST.get('remark') or '').strip()
    try:
        issued_at = _parse_issued_datetime(
            request.POST.get('issued_date'),
            request.POST.get('issued_time'),
        )
    except ValueError as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=400)
    try:
        issue = InventoryIssue(
            inventory=inv,
            quantity_input=qty_raw,
            recipient_name=recipient,
            remark=remark,
            issued_at=issued_at,
            created_by=request.user,
        )
        issue.save()
    except ValueError as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=400)
    inv = sync_inventory_row(inv)
    _clear_inventory_list_cache(request)
    data = _inventory_row_response(inv)
    issues_qs = InventoryIssue.objects.filter(inventory_id=inv.pk)
    data['issues'] = _issues_list_payload(inv, issues_qs)
    data['needs_opening_import'] = False
    _enrich_stock_panel_totals(data, inv)
    data['issue'] = next((i for i in data['issues'] if int(i['id']) == issue.pk), None)
    if not data['issue']:
        data['issue'] = _serialize_issue(issue)
    resp = JsonResponse(data)
    apply_no_cache_headers(resp)
    return resp


def _keep_legacy_text(current, posted, legacy_const):
    posted = (posted or '').strip()
    if (current or '') == legacy_const and (not posted or posted == legacy_const):
        return legacy_const
    return posted


@login_required
@company_admin_or_permission_required('inventory.change_inventory', raise_exception=True)
@require_POST
def ajax_issue_update(request, pk):
    """Edit one withdrawal; totals and remaining stock recalculate."""
    issue, err = _ledger_line_or_error(request, InventoryIssue, pk)
    if err:
        return err
    inv = issue.inventory
    qty_raw = (request.POST.get('quantity') or request.POST.get('quantity_input') or '').strip()
    if not qty_raw:
        return JsonResponse({'success': False, 'message': 'Quantity is required.'}, status=400)
    qty_raw = normalize_quantity_input(qty_raw)
    try:
        issued_at = _parse_issued_datetime(
            request.POST.get('issued_date'),
            request.POST.get('issued_time'),
        )
        issue.quantity_input = qty_raw
        issue.recipient_name = (request.POST.get('recipient_name') or request.POST.get('recipient') or '').strip()
        issue.remark = _keep_legacy_text(
            issue.remark,
            request.POST.get('remark') or '',
            LEGACY_ISSUE_REMARK,
        )
        issue.issued_at = issued_at
        issue.save()
        inv = sync_inventory_row(inv)
        _clear_inventory_list_cache(request)
        data = _inventory_row_response(inv)
        data['issues'] = _issues_list_payload(inv, InventoryIssue.objects.filter(inventory_id=inv.pk))
        data['needs_opening_import'] = False
        _enrich_stock_panel_totals(data, inv)
        resp = JsonResponse(data)
        apply_no_cache_headers(resp)
        return resp
    except ValueError as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=400)
    except Exception:
        logger.exception('ajax_issue_update failed for pk=%s', pk)
        return JsonResponse(
            {'success': False, 'message': 'Could not save this withdrawal. Please try again.'},
            status=500,
        )


@login_required
@company_admin_or_permission_required('inventory.change_inventory', raise_exception=True)
@require_POST
def ajax_issue_delete(request, pk):
    """Remove one issue and recalculate quantity out."""
    issue, err = _ledger_line_or_error(request, InventoryIssue, pk)
    if err:
        return err
    inv = issue.inventory
    try:
        issue.delete()
        inv = Inventory.objects.get(pk=inv.pk)
    except Exception as exc:
        return JsonResponse({'success': False, 'message': str(exc)}, status=400)
    _clear_inventory_list_cache(request)
    data = _inventory_row_response(inv)
    data['issues'] = _issues_list_payload(inv, InventoryIssue.objects.filter(inventory_id=inv.pk))
    resp = JsonResponse(data)
    apply_no_cache_headers(resp)
    return resp


@login_required
@company_admin_or_permission_required('inventory.change_inventory', raise_exception=True)
@require_POST
def ajax_issue_import_opening(request):
    """
    Log the current Quantity Out as the first withdrawal (with date/time) for dropdown history.
    """
    pk = request.POST.get('inventory') or request.POST.get('id') or request.POST.get('pk')
    if not pk:
        return JsonResponse({'success': False, 'message': 'Missing inventory id'}, status=400)
    inv = get_object_or_404(_inventory_queryset(request), pk=pk)
    if InventoryIssue.objects.filter(inventory_id=inv.pk).exists():
        return JsonResponse({
            'success': False,
            'message': 'Withdrawals already logged. Open the dropdown to view them.',
        }, status=400)
    opening_qty = _decimal_safe(inv.quantity_out)
    if opening_qty <= 0:
        return JsonResponse({
            'success': False,
            'message': 'Quantity Out is zero. Use New withdrawal to record stock taken out.',
        }, status=400)
    try:
        issued_at = _parse_issued_datetime(
            request.POST.get('issued_date'),
            request.POST.get('issued_time'),
        )
    except ValueError as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=400)
    recipient = (request.POST.get('recipient_name') or '').strip() or '(Earlier withdrawals)'
    InventoryIssue.objects.create(
        inventory=inv,
        quantity=opening_qty,
        quantity_input=inv.quantity_out_input or str(opening_qty),
        recipient_name=recipient,
        remark=LEGACY_ISSUE_REMARK,
        issued_at=issued_at,
        created_by=request.user,
        company_id=inv.company_id,
        account_id=inv.account_id,
    )
    inv = sync_inventory_row(inv)
    _clear_inventory_list_cache(request)
    data = _inventory_row_response(inv)
    data['issues'] = _issues_list_payload(inv, InventoryIssue.objects.filter(inventory_id=inv.pk))
    resp = JsonResponse(data)
    apply_no_cache_headers(resp)
    return resp


def _inventory_receipt_queryset(request):
    """Receipts on inventory rows the current user can access (not limited to created_by)."""
    pks = _accessible_inventory_pks(request)
    qs = InventoryReceipt.objects.select_related('inventory', 'created_by')
    if not pks:
        return qs.none()
    return qs.filter(inventory_id__in=pks)


def _inventory_waste_log_queryset(request):
    """Waste logs on inventory rows the current user can access (not limited to created_by)."""
    pks = _accessible_inventory_pks(request)
    qs = WasteLog.objects.select_related('inventory', 'created_by')
    if not pks:
        return qs.none()
    return qs.filter(inventory_id__in=pks)


def _ledger_line_or_error(request, model, pk):
    """Load a receipt/issue/waste row if the parent inventory is in the user's queryset.

    Always returns JSON on failure so the inventory page fetch() never tries to parse HTML 404.
    """
    obj = model.objects.select_related('inventory', 'created_by').filter(pk=pk).first()
    if not obj:
        return None, JsonResponse(
            {'success': False, 'message': 'This log was not found. Refresh the page and try again.'},
            status=404,
        )
    inv_id = getattr(obj, 'inventory_id', None)
    if not inv_id or not _inventory_queryset(request).filter(pk=inv_id).exists():
        return None, JsonResponse(
            {'success': False, 'message': 'You cannot edit this log.'},
            status=404,
        )
    return obj, None


def _serialize_receipt(receipt, cumulative_in=None, available_after=None, unit_label=''):
    received = timezone.localtime(receipt.received_at) if timezone.is_aware(receipt.received_at) else receipt.received_at
    user = receipt.created_by
    cum_text = avail_text = ''
    if cumulative_in is not None:
        cum_text = str(cumulative_in)
        if unit_label:
            cum_text += f' {unit_label}'
    if available_after is not None:
        avail_text = str(available_after)
        if unit_label:
            avail_text += f' {unit_label}'
    is_legacy = (receipt.remark or '') == LEGACY_RECEIPT_REMARK
    line_val = getattr(receipt, 'line_value', None)
    if line_val is None:
        line_val = _decimal_safe(receipt.quantity) * _decimal_safe(receipt.unit_price)
    return {
        'id': receipt.pk,
        'quantity': str(receipt.quantity),
        'quantity_input': receipt.quantity_input or str(receipt.quantity),
        'unit_price': _money_str(receipt.unit_price),
        'line_value': _money_str(line_val),
        'supplier_name': receipt.supplier_name or '',
        'received_at': received.strftime('%Y-%m-%d'),
        'received_time': received.strftime('%H:%M'),
        'received_at_display': received.strftime('%Y-%m-%d %I:%M %p'),
        'remark': receipt.remark or '',
        'created_by': (user.get_full_name() or user.email or '—') if user else '—',
        'cumulative_in': cum_text,
        'available_after': avail_text,
        'is_legacy': is_legacy,
        'inventory_id': receipt.inventory_id,
    }


def _ledger_out_waste_before(inv, cutoff_dt):
    """Sum of issues and waste on or before cutoff_dt (for running balance in ledgers)."""
    from decimal import Decimal as D
    out = (
        InventoryIssue.objects.filter(inventory_id=inv.pk, issued_at__lte=cutoff_dt)
        .aggregate(total=Sum('quantity'))['total']
    )
    cutoff_date = cutoff_dt.date() if hasattr(cutoff_dt, 'date') else cutoff_dt
    waste = (
        WasteLog.objects.filter(inventory_id=inv.pk, waste_date__lte=cutoff_date)
        .aggregate(total=Sum('quantity'))['total']
    )
    return _decimal_safe(out) + _decimal_safe(waste)


def _quantity_in_input_display(inv):
    samples = InventoryReceipt.objects.filter(inventory_id=inv.pk).values_list('quantity_input', flat=True)
    if samples:
        return compose_total_quantity_input(inv.quantity_in, samples)
    return inv.quantity_in_input or str(inv.quantity_in)


def _quantity_out_input_display(inv):
    samples = InventoryIssue.objects.filter(inventory_id=inv.pk).values_list('quantity_input', flat=True)
    if samples:
        return compose_total_quantity_input(inv.quantity_out, samples)
    return inv.quantity_out_input or str(inv.quantity_out)


def _waste_total_input_display(inv):
    samples = WasteLog.objects.filter(inventory_id=inv.pk).values_list('quantity_input', flat=True)
    return compose_total_quantity_input(inv.waste, samples)


def _enrich_stock_panel_totals(data, inv):
    """Attach list-panel totals so the UI can refresh every dropdown header after a save."""
    data['total_received'] = str(inv.quantity_in)
    data['total_issued'] = str(inv.quantity_out)
    data['total_waste'] = str(inv.waste)
    data['quantity_in'] = str(inv.quantity_in)
    data['quantity_out'] = str(inv.quantity_out)
    data['waste'] = str(inv.waste)
    data['quantity_in_input'] = _quantity_in_input_display(inv)
    data['quantity_out_input'] = _quantity_out_input_display(inv)
    data['waste_input'] = _waste_total_input_display(inv)
    data['unit_label'] = inv.unit_label or ''
    data['unit_price'] = _money_str(inv.unit_price)
    data['unit_price_input'] = getattr(inv, 'unit_price_input', '') or ''
    data['total_amount'] = _money_str(inv.total_amount)
    data['stock_balance_remaining'] = _money_str(inv.stock_balance_remaining)
    data['waste_value'] = _money_str(inv.waste_value)
    data['net_quantity'] = str(inv.net_quantity)
    data['balance_quantity'] = str(inv.balance_quantity)
    data['available'] = str(inv.net_quantity)
    data['formula_money'] = 'Balance = Quantity In × Unit Price; Stock value remaining = Net Qty × Unit Price'
    return data


def _receipts_list_payload(inv, receipts_qs):
    from decimal import Decimal as D
    if isinstance(receipts_qs, list):
        ordered = sorted(receipts_qs, key=lambda r: (r.received_at, r.pk))
        display_receipts = sorted(receipts_qs, key=lambda r: (r.received_at, r.pk), reverse=True)
    else:
        ordered = list(receipts_qs.order_by('received_at', 'pk'))
        display_receipts = list(reversed(ordered))
    cumulative = D('0')
    cumulative_by_pk = {}
    for receipt in ordered:
        cumulative += D(str(receipt.quantity))
        cumulative_by_pk[receipt.pk] = cumulative
    unit = inv.unit_label or ''
    items = []
    for receipt in display_receipts:
        cum = cumulative_by_pk.get(receipt.pk, cumulative)
        deducted = _ledger_out_waste_before(inv, receipt.received_at)
        items.append(_serialize_receipt(
            receipt,
            cumulative_in=cum,
            available_after=cum - deducted,
            unit_label=unit,
        ))
    return items


def _serialize_waste_log(wlog, available_after=None, unit_label=''):
    user = wlog.created_by
    avail_text = ''
    if available_after is not None:
        avail_text = str(available_after)
        if unit_label:
            avail_text += f' {unit_label}'
    is_legacy = (wlog.description or '') == LEGACY_WASTE_REMARK
    reason_display = dict(WasteLog.WASTE_REASON_CHOICES).get(wlog.reason, wlog.reason)
    created = timezone.localtime(wlog.created_at) if timezone.is_aware(wlog.created_at) else wlog.created_at
    return {
        'id': wlog.pk,
        'quantity': str(wlog.quantity),
        'quantity_input': wlog.quantity_input or str(wlog.quantity),
        'unit_price': _money_str(wlog.unit_price),
        'line_value': _money_str(wlog.total_value),
        'reason': wlog.reason,
        'reason_display': reason_display,
        'description': wlog.description or '',
        'waste_date': wlog.waste_date.strftime('%Y-%m-%d') if wlog.waste_date else '',
        'waste_at_display': (
            f"{wlog.waste_date.strftime('%Y-%m-%d')} {created.strftime('%I:%M %p')}"
            if wlog.waste_date else created.strftime('%Y-%m-%d %I:%M %p')
        ),
        'created_by': (user.get_full_name() or user.email or '—') if user else '—',
        'available_after': avail_text,
        'is_legacy': is_legacy,
        'inventory_id': wlog.inventory_id,
    }


def _waste_logs_list_payload(inv, logs_qs):
    from decimal import Decimal as D
    if isinstance(logs_qs, list):
        ordered = sorted(logs_qs, key=lambda w: (w.waste_date, w.created_at, w.pk))
        display_logs = sorted(logs_qs, key=lambda w: (w.waste_date, w.created_at, w.pk), reverse=True)
    else:
        ordered = list(logs_qs.order_by('waste_date', 'created_at', 'pk'))
        display_logs = list(reversed(ordered))
    cumulative_waste = D('0')
    remaining_by_pk = {}
    qty_in = D(str(inv.quantity_in))
    qty_out = D(str(inv.quantity_out))
    for wlog in ordered:
        cumulative_waste += D(str(wlog.quantity))
        remaining_by_pk[wlog.pk] = qty_in - cumulative_waste - qty_out
    unit = inv.unit_label or ''
    items = []
    for wlog in display_logs:
        items.append(_serialize_waste_log(
            wlog,
            available_after=remaining_by_pk.get(wlog.pk, qty_in - qty_out),
            unit_label=unit,
        ))
    return items


@login_required
@company_admin_or_permission_required('inventory.view_inventory', raise_exception=True)
@require_GET
def ajax_receipt_list(request):
    pk = request.GET.get('inventory') or request.GET.get('id') or request.GET.get('pk')
    if not pk:
        return JsonResponse({'success': False, 'message': 'Missing inventory id'}, status=400)
    inv = get_object_or_404(_inventory_queryset(request), pk=pk)
    try:
        inv = prepare_inventory_for_panel(inv.pk) or inv
    except Exception as exc:
        return JsonResponse({'success': False, 'message': str(exc)}, status=400)
    receipts = _inventory_receipt_queryset(request).filter(inventory_id=inv.pk)
    supplier = (request.GET.get('supplier') or '').strip()
    date_from = (request.GET.get('date_from') or '').strip()
    date_to = (request.GET.get('date_to') or '').strip()
    if supplier:
        receipts = receipts.filter(supplier_name__icontains=supplier)
    search = (request.GET.get('search') or '').strip()
    if search:
        receipts = receipts.filter(
            Q(supplier_name__icontains=search)
            | Q(quantity_input__icontains=search)
            | Q(remark__icontains=search)
        )
    if date_from:
        receipts = receipts.filter(received_at__date__gte=date_from)
    if date_to:
        receipts = receipts.filter(received_at__date__lte=date_to)
    
    # Order before pagination
    receipts = receipts.order_by('received_at', 'pk')
    
    # Pagination
    page = int(request.GET.get('page', 1))
    per_page = int(request.GET.get('per_page', 30))
    receipt_count = receipts.count()
    total_pages = (receipt_count + per_page - 1) // per_page
    page = max(1, min(page, total_pages)) if total_pages > 0 else 1
    offset = (page - 1) * per_page
    receipts_paginated = list(receipts[offset:offset + per_page])
    
    items = _receipts_list_payload(inv, receipts_paginated)
    needs_opening = receipt_count == 0 and _decimal_safe(inv.quantity_in) > 0
    data = {
        'success': True,
        'receipts': items,
        'receipt_count': receipt_count,
        'needs_opening_import': needs_opening,
        'opening_quantity': inv.quantity_in_input or str(inv.quantity_in),
        'product_name': inv.product_name,
        'has_receipts': receipt_count > 0,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages,
        'has_next': page < total_pages,
        'has_prev': page > 1,
    }
    _enrich_stock_panel_totals(data, inv)
    resp = JsonResponse(data)
    apply_no_cache_headers(resp)
    return resp


@login_required
@company_admin_or_permission_required('inventory.change_inventory', raise_exception=True)
@require_POST
def ajax_receipt_create(request):
    pk = request.POST.get('inventory') or request.POST.get('id') or request.POST.get('pk')
    if not pk:
        return JsonResponse({'success': False, 'message': 'Missing inventory id'}, status=400)
    inv = get_object_or_404(_inventory_queryset(request), pk=pk)
    qty_raw = (request.POST.get('quantity') or request.POST.get('quantity_input') or '').strip()
    if not qty_raw:
        return JsonResponse({'success': False, 'message': 'Quantity is required.'}, status=400)
    qty_raw = normalize_quantity_input(qty_raw)
    supplier = (request.POST.get('supplier_name') or request.POST.get('supplier') or '').strip()
    remark = (request.POST.get('remark') or '').strip()
    try:
        received_at = _parse_issued_datetime(
            request.POST.get('received_date') or request.POST.get('issued_date'),
            request.POST.get('received_time') or request.POST.get('issued_time'),
        )
    except ValueError as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=400)
    try:
        receipt = InventoryReceipt(
            inventory=inv,
            quantity_input=qty_raw,
            supplier_name=supplier,
            remark=remark,
            received_at=received_at,
            created_by=request.user,
        )
        receipt.save()
    except ValueError as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=400)
    inv = sync_inventory_row(inv)
    _clear_inventory_list_cache(request)
    data = _inventory_row_response(inv)
    data['receipts'] = _receipts_list_payload(inv, InventoryReceipt.objects.filter(inventory_id=inv.pk))
    data['needs_opening_import'] = False
    _enrich_stock_panel_totals(data, inv)
    resp = JsonResponse(data)
    apply_no_cache_headers(resp)
    return resp


@login_required
@company_admin_or_permission_required('inventory.change_inventory', raise_exception=True)
@require_POST
def ajax_receipt_update(request, pk):
    """Edit one receipt; Quantity In and remaining stock recalculate."""
    receipt, err = _ledger_line_or_error(request, InventoryReceipt, pk)
    if err:
        return err
    inv = receipt.inventory
    qty_raw = (request.POST.get('quantity') or request.POST.get('quantity_input') or '').strip()
    if not qty_raw:
        return JsonResponse({'success': False, 'message': 'Quantity is required.'}, status=400)
    qty_raw = normalize_quantity_input(qty_raw)
    try:
        received_at = _parse_issued_datetime(
            request.POST.get('received_date') or request.POST.get('issued_date'),
            request.POST.get('received_time') or request.POST.get('issued_time'),
        )
        receipt.quantity_input = qty_raw
        receipt.supplier_name = (request.POST.get('supplier_name') or request.POST.get('supplier') or '').strip()
        receipt.remark = _keep_legacy_text(
            receipt.remark,
            request.POST.get('remark') or '',
            LEGACY_RECEIPT_REMARK,
        )
        receipt.received_at = received_at
        receipt.save()
        inv = sync_inventory_row(inv)
        _clear_inventory_list_cache(request)
        data = _inventory_row_response(inv)
        data['receipts'] = _receipts_list_payload(inv, InventoryReceipt.objects.filter(inventory_id=inv.pk))
        data['needs_opening_import'] = False
        _enrich_stock_panel_totals(data, inv)
        resp = JsonResponse(data)
        apply_no_cache_headers(resp)
        return resp
    except ValueError as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=400)
    except Exception:
        logger.exception('ajax_receipt_update failed for pk=%s', pk)
        return JsonResponse(
            {'success': False, 'message': 'Could not save this receipt. Please try again.'},
            status=500,
        )


@login_required
@company_admin_or_permission_required('inventory.change_inventory', raise_exception=True)
@require_POST
def ajax_receipt_delete(request, pk):
    """Remove one receipt and recalculate quantity in."""
    receipt, err = _ledger_line_or_error(request, InventoryReceipt, pk)
    if err:
        return err
    inv = receipt.inventory
    try:
        receipt.delete()
        inv = Inventory.objects.get(pk=inv.pk)
    except Exception as exc:
        return JsonResponse({'success': False, 'message': str(exc)}, status=400)
    _clear_inventory_list_cache(request)
    data = _inventory_row_response(inv)
    data['receipts'] = _receipts_list_payload(inv, InventoryReceipt.objects.filter(inventory_id=inv.pk))
    resp = JsonResponse(data)
    apply_no_cache_headers(resp)
    return resp


@login_required
@company_admin_or_permission_required('inventory.change_inventory', raise_exception=True)
@require_POST
def ajax_receipt_import_opening(request):
    pk = request.POST.get('inventory') or request.POST.get('id') or request.POST.get('pk')
    if not pk:
        return JsonResponse({'success': False, 'message': 'Missing inventory id'}, status=400)
    inv = get_object_or_404(_inventory_queryset(request), pk=pk)
    if InventoryReceipt.objects.filter(inventory_id=inv.pk).exists():
        return JsonResponse({
            'success': False,
            'message': 'Receipts already logged. Open the dropdown to view them.',
        }, status=400)
    opening_qty = _decimal_safe(inv.quantity_in)
    if opening_qty <= 0:
        return JsonResponse({
            'success': False,
            'message': 'Quantity In is zero. Use Receive stock to record incoming stock.',
        }, status=400)
    try:
        received_at = _parse_issued_datetime(
            request.POST.get('received_date') or request.POST.get('issued_date'),
            request.POST.get('received_time') or request.POST.get('issued_time'),
        )
    except ValueError as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=400)
    supplier = (request.POST.get('supplier_name') or '').strip() or '(Earlier stock in)'
    InventoryReceipt.objects.create(
        inventory=inv,
        quantity=opening_qty,
        quantity_input=inv.quantity_in_input or str(opening_qty),
        supplier_name=supplier,
        remark=LEGACY_RECEIPT_REMARK,
        received_at=received_at,
        created_by=request.user,
        company_id=inv.company_id,
        account_id=inv.account_id,
    )
    inv = sync_inventory_row(inv)
    _clear_inventory_list_cache(request)
    data = _inventory_row_response(inv)
    data['receipts'] = _receipts_list_payload(inv, InventoryReceipt.objects.filter(inventory_id=inv.pk))
    resp = JsonResponse(data)
    apply_no_cache_headers(resp)
    return resp


@login_required
@company_admin_or_permission_required('inventory.view_inventory', raise_exception=True)
@require_GET
def ajax_waste_log_list(request):
    pk = request.GET.get('inventory') or request.GET.get('id') or request.GET.get('pk')
    if not pk:
        return JsonResponse({'success': False, 'message': 'Missing inventory id'}, status=400)
    inv = get_object_or_404(_inventory_queryset(request), pk=pk)
    inv = prepare_inventory_for_panel(inv.pk) or inv
    logs = _inventory_waste_log_queryset(request).filter(inventory_id=inv.pk)
    reason = (request.GET.get('reason') or '').strip()
    date_from = (request.GET.get('date_from') or '').strip()
    date_to = (request.GET.get('date_to') or '').strip()
    if reason:
        logs = logs.filter(reason=reason)
    search = (request.GET.get('search') or '').strip()
    if search:
        logs = logs.filter(
            Q(reason__icontains=search)
            | Q(description__icontains=search)
            | Q(quantity_input__icontains=search)
        )
    if date_from:
        logs = logs.filter(waste_date__gte=date_from)
    if date_to:
        logs = logs.filter(waste_date__lte=date_to)
    
    # Order before pagination
    logs = logs.order_by('waste_date', 'pk')
    
    # Pagination
    page = int(request.GET.get('page', 1))
    per_page = int(request.GET.get('per_page', 30))
    log_count = logs.count()
    total_pages = (log_count + per_page - 1) // per_page
    page = max(1, min(page, total_pages)) if total_pages > 0 else 1
    offset = (page - 1) * per_page
    logs_paginated = list(logs[offset:offset + per_page])
    
    items = _waste_logs_list_payload(inv, logs_paginated)
    needs_opening = log_count == 0 and _decimal_safe(inv.waste) > 0
    data = {
        'success': True,
        'waste_logs': items,
        'waste_log_count': log_count,
        'needs_opening_import': needs_opening,
        'opening_quantity': _waste_total_input_display(inv) or str(inv.waste),
        'product_name': inv.product_name,
        'has_waste_logs': log_count > 0,
        'waste_reason_choices': list(WasteLog.WASTE_REASON_CHOICES),
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages,
        'has_next': page < total_pages,
        'has_prev': page > 1,
    }
    _enrich_stock_panel_totals(data, inv)
    resp = JsonResponse(data)
    apply_no_cache_headers(resp)
    return resp


@login_required
@company_admin_or_permission_required('inventory.change_inventory', raise_exception=True)
@require_POST
def ajax_waste_log_create(request):
    pk = request.POST.get('inventory') or request.POST.get('id') or request.POST.get('pk')
    if not pk:
        return JsonResponse({'success': False, 'message': 'Missing inventory id'}, status=400)
    inv = get_object_or_404(_inventory_queryset(request), pk=pk)
    qty_raw = (request.POST.get('quantity') or request.POST.get('quantity_input') or '').strip()
    if not qty_raw:
        return JsonResponse({'success': False, 'message': 'Quantity is required.'}, status=400)
    qty_raw = normalize_quantity_input(qty_raw)
    reason = (request.POST.get('reason') or 'other').strip()
    if reason not in dict(WasteLog.WASTE_REASON_CHOICES):
        reason = 'other'
    description = (request.POST.get('description') or request.POST.get('remark') or '').strip()
    waste_date_str = (request.POST.get('waste_date') or request.POST.get('issued_date') or '').strip()
    from datetime import datetime as dt
    waste_date = timezone.now().date()
    if waste_date_str:
        try:
            waste_date = dt.strptime(waste_date_str, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'success': False, 'message': 'Invalid waste date.'}, status=400)
    try:
        wlog = WasteLog(
            inventory=inv,
            quantity_input=qty_raw,
            unit_price=_decimal_safe(inv.unit_price),
            reason=reason,
            description=description,
            waste_date=waste_date,
            created_by=request.user,
        )
        wlog.save()
    except ValueError as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=400)
    inv = sync_inventory_row(inv)
    _clear_inventory_list_cache(request)
    data = _inventory_row_response(inv)
    data['waste_logs'] = _waste_logs_list_payload(inv, WasteLog.objects.filter(inventory_id=inv.pk))
    data['needs_opening_import'] = False
    _enrich_stock_panel_totals(data, inv)
    resp = JsonResponse(data)
    apply_no_cache_headers(resp)
    return resp


@login_required
@company_admin_or_permission_required('inventory.change_inventory', raise_exception=True)
@require_POST
def ajax_waste_log_update(request, pk):
    """Edit one waste log; waste total and remaining stock recalculate."""
    wlog, err = _ledger_line_or_error(request, WasteLog, pk)
    if err:
        return err
    inv = wlog.inventory
    qty_raw = (request.POST.get('quantity') or request.POST.get('quantity_input') or '').strip()
    if not qty_raw:
        return JsonResponse({'success': False, 'message': 'Quantity is required.'}, status=400)
    qty_raw = normalize_quantity_input(qty_raw)
    reason = (request.POST.get('reason') or 'other').strip()
    if reason not in dict(WasteLog.WASTE_REASON_CHOICES):
        reason = 'other'
    description = (request.POST.get('description') or request.POST.get('remark') or '').strip()
    waste_date_str = (request.POST.get('waste_date') or request.POST.get('issued_date') or '').strip()
    from datetime import datetime as dt
    waste_date = wlog.waste_date or timezone.now().date()
    if waste_date_str:
        try:
            waste_date = dt.strptime(waste_date_str, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'success': False, 'message': 'Invalid waste date.'}, status=400)
    try:
        wlog.quantity_input = qty_raw
        wlog.reason = reason
        wlog.description = _keep_legacy_text(wlog.description, description, LEGACY_WASTE_REMARK)
        wlog.waste_date = waste_date
        wlog.save()
        inv = sync_inventory_row(inv)
        _clear_inventory_list_cache(request)
        data = _inventory_row_response(inv)
        data['waste_logs'] = _waste_logs_list_payload(inv, WasteLog.objects.filter(inventory_id=inv.pk))
        data['needs_opening_import'] = False
        _enrich_stock_panel_totals(data, inv)
        resp = JsonResponse(data)
        apply_no_cache_headers(resp)
        return resp
    except ValueError as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=400)
    except Exception:
        logger.exception('ajax_waste_log_update failed for pk=%s', pk)
        return JsonResponse(
            {'success': False, 'message': 'Could not save this waste log. Please try again.'},
            status=500,
        )


@login_required
@company_admin_or_permission_required('inventory.change_inventory', raise_exception=True)
@require_POST
def ajax_waste_log_delete(request, pk):
    """Remove one waste log and recalculate waste total."""
    wlog, err = _ledger_line_or_error(request, WasteLog, pk)
    if err:
        return err
    inv = wlog.inventory
    try:
        wlog.delete()
        inv = Inventory.objects.get(pk=inv.pk)
    except Exception as exc:
        return JsonResponse({'success': False, 'message': str(exc)}, status=400)
    _clear_inventory_list_cache(request)
    data = _inventory_row_response(inv)
    data['waste_logs'] = _waste_logs_list_payload(inv, WasteLog.objects.filter(inventory_id=inv.pk))
    resp = JsonResponse(data)
    apply_no_cache_headers(resp)
    return resp


@login_required
@company_admin_or_permission_required('inventory.change_inventory', raise_exception=True)
@require_POST
def ajax_waste_log_import_opening(request):
    pk = request.POST.get('inventory') or request.POST.get('id') or request.POST.get('pk')
    if not pk:
        return JsonResponse({'success': False, 'message': 'Missing inventory id'}, status=400)
    inv = get_object_or_404(_inventory_queryset(request), pk=pk)
    if WasteLog.objects.filter(inventory_id=inv.pk).exists():
        return JsonResponse({
            'success': False,
            'message': 'Waste already logged. Open the dropdown to view entries.',
        }, status=400)
    opening_qty = _decimal_safe(inv.waste)
    if opening_qty <= 0:
        return JsonResponse({
            'success': False,
            'message': 'Waste is zero. Use Record waste for each incident.',
        }, status=400)
    from datetime import datetime as dt
    waste_date_str = (request.POST.get('waste_date') or request.POST.get('issued_date') or '').strip()
    waste_date = timezone.now().date()
    if waste_date_str:
        try:
            waste_date = dt.strptime(waste_date_str, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'success': False, 'message': 'Invalid waste date.'}, status=400)
    WasteLog.objects.create(
        inventory=inv,
        quantity=opening_qty,
        quantity_input=str(opening_qty),
        unit_price=_decimal_safe(inv.unit_price),
        reason='other',
        description=LEGACY_WASTE_REMARK,
        waste_date=waste_date,
        created_by=request.user,
        company_id=inv.company_id,
        account_id=inv.account_id,
    )
    inv = sync_inventory_row(inv)
    _clear_inventory_list_cache(request)
    data = _inventory_row_response(inv)
    data['waste_logs'] = _waste_logs_list_payload(inv, WasteLog.objects.filter(inventory_id=inv.pk))
    resp = JsonResponse(data)
    apply_no_cache_headers(resp)
    return resp


def _serialize_movement(movement):
    created = timezone.localtime(movement.created_at) if timezone.is_aware(movement.created_at) else movement.created_at
    user = movement.created_by
    qty_in = _decimal_safe(movement.quantity_in)
    qty_out = _decimal_safe(movement.quantity_out)
    waste = _decimal_safe(movement.waste)
    if qty_in > 0 and qty_out == 0 and waste == 0:
        event = 'Stock received'
    elif qty_out > 0 and qty_in == 0:
        event = 'Stock issued'
    elif waste > 0 and qty_in == 0 and qty_out == 0:
        event = 'Waste'
    elif qty_in == 0 and qty_out == 0:
        event = (movement.remark or 'Update').strip() or 'Update'
    else:
        event = movement.remark or 'Inventory change'
    return {
        'id': movement.pk,
        'created_at_display': created.strftime('%Y-%m-%d %I:%M %p'),
        'event': event,
        'quantity_in': str(movement.quantity_in),
        'quantity_out': str(movement.quantity_out),
        'waste': str(movement.waste),
        'quantity_after': str(movement.remaining_after_display),
        'unit_price': _money_str(movement.unit_price),
        'balance': _money_str(movement.balance),
        'stock_balance_remaining': _money_str(movement.stock_remaining_display),
        'waste_value': _money_str(movement.waste_value),
        'remark': movement.remark or '',
        'created_by': (user.get_full_name() or user.email or '—') if user else '—',
    }


def _build_financial_timeline(inv):
    """
    Real-time style calculation log from each receipt, issue, and waste line
    (same sources as Quantity In ▾ / Quantity Out ▾), plus unit-price-only updates.
    """
    from decimal import Decimal as D

    unit_label = inv.unit_label or ''
    suffix = f' {unit_label}' if unit_label else ''
    raw_events = []

    for receipt in InventoryReceipt.objects.filter(inventory_id=inv.pk).order_by('received_at', 'pk'):
        received = (
            timezone.localtime(receipt.received_at)
            if timezone.is_aware(receipt.received_at)
            else receipt.received_at
        )
        raw_events.append({
            'sort_at': received,
            'kind': 'in',
            'at_display': received.strftime('%Y-%m-%d %I:%M %p'),
            'title': 'Stock received',
            'qty_input': receipt.quantity_input or str(receipt.quantity),
            'qty': _decimal_safe(receipt.quantity),
            'unit_price': _decimal_safe(receipt.unit_price),
            'line_value': _decimal_safe(receipt.line_value),
            'detail': receipt.supplier_name or '',
        })

    for issue in InventoryIssue.objects.filter(inventory_id=inv.pk).order_by('issued_at', 'pk'):
        issued = (
            timezone.localtime(issue.issued_at)
            if timezone.is_aware(issue.issued_at)
            else issue.issued_at
        )
        raw_events.append({
            'sort_at': issued,
            'kind': 'out',
            'at_display': issued.strftime('%Y-%m-%d %I:%M %p'),
            'title': 'Stock issued',
            'qty_input': issue.quantity_input or str(issue.quantity),
            'qty': _decimal_safe(issue.quantity),
            'unit_price': _decimal_safe(issue.unit_price),
            'line_value': _decimal_safe(issue.line_value),
            'detail': issue.recipient_name or '',
        })

    for wlog in WasteLog.objects.filter(inventory_id=inv.pk).order_by('waste_date', 'created_at', 'pk'):
        created = (
            timezone.localtime(wlog.created_at)
            if timezone.is_aware(wlog.created_at)
            else wlog.created_at
        )
        if wlog.waste_date:
            at_display = f"{wlog.waste_date.strftime('%Y-%m-%d')} {created.strftime('%I:%M %p')}"
        else:
            at_display = created.strftime('%Y-%m-%d %I:%M %p')
        sort_at = created
        if wlog.waste_date:
            from datetime import datetime as dt
            sort_at = dt.combine(wlog.waste_date, created.time())
            if timezone.is_aware(created):
                sort_at = timezone.make_aware(sort_at, timezone.get_current_timezone())
        raw_events.append({
            'sort_at': sort_at,
            'kind': 'waste',
            'at_display': at_display,
            'title': 'Waste recorded',
            'qty_input': wlog.quantity_input or str(wlog.quantity),
            'qty': _decimal_safe(wlog.quantity),
            'unit_price': _decimal_safe(wlog.unit_price),
            'line_value': _decimal_safe(wlog.total_value),
            'detail': wlog.get_reason_display() if hasattr(wlog, 'get_reason_display') else wlog.reason,
        })

    kind_order = {'in': 0, 'out': 1, 'waste': 2, 'price': 3}
    raw_events.sort(key=lambda e: (e['sort_at'], kind_order.get(e['kind'], 9)))

    run_in = run_out = run_waste = D('0')
    last_price = _decimal_safe(inv.unit_price)
    timeline = []

    def _qty_text(qty):
        t = format(_decimal_safe(qty), 'f')
        if '.' in t:
            t = t.rstrip('0').rstrip('.') or '0'
        return t + suffix

    def _sort_ts(dt):
        if dt is None:
            return 0.0
        if timezone.is_aware(dt):
            return dt.timestamp()
        return timezone.make_aware(dt, timezone.get_current_timezone()).timestamp()

    for ev in raw_events:
        price = _decimal_safe(ev['unit_price'])
        if price <= 0:
            price = last_price if last_price > 0 else _decimal_safe(inv.unit_price)
        if ev['kind'] == 'in':
            run_in += ev['qty']
            change = f"+{ev['qty_input']}"
        elif ev['kind'] == 'out':
            run_out += ev['qty']
            change = f"−{ev['qty_input']}"
        else:
            run_waste += ev['qty']
            change = f"−{ev['qty_input']} waste"

        if price > 0:
            last_price = price
        raw_net = run_in - run_waste - run_out
        net = _floor_zero(raw_net)
        balance_after = run_in * last_price
        stock_after = net * last_price
        net_warning = raw_net < 0

        if ev['kind'] == 'in':
            calc = (
                f"Received {change} @ {_money_str(last_price)} each · "
                f"Total received = {_qty_text(run_in)} · "
                f"Balance (all stock in) = {_qty_text(run_in)} × {_money_str(last_price)} · "
                f"Stock on hand = {_qty_text(net)} × {_money_str(last_price)}"
            )
        elif ev['kind'] == 'out':
            calc = (
                f"Issued {change} @ {_money_str(last_price)} each · "
                f"Net left = {_qty_text(run_in)} − {_qty_text(run_waste)} − {_qty_text(run_out)} = {_qty_text(net)} · "
                f"Stock value = {_qty_text(net)} × {_money_str(last_price)}"
            )
        else:
            calc = (
                f"Waste {change} @ {_money_str(last_price)} each · "
                f"Net left = {_qty_text(net)} · "
                f"Stock value = {_qty_text(net)} × {_money_str(last_price)}"
            )

        timeline.append({
            'sort_at_ts': _sort_ts(ev['sort_at']),
            'at_display': ev['at_display'],
            'event': ev['title'],
            'kind': ev['kind'],
            'change': change,
            'unit_price': _money_str(last_price),
            'line_value': _money_str(ev['line_value']),
            'balance_after': _money_str(balance_after),
            'stock_balance_remaining': _money_str(stock_after),
            'net_quantity': _qty_text(net),
            'quantity_in_total': _qty_text(run_in),
            'calculation': calc,
            'detail': ev['detail'] or '',
            'net_warning': net_warning,
        })

    for movement in InventoryMovement.objects.filter(product_id=inv.pk).order_by('created_at', 'pk'):
        qty_in = _decimal_safe(movement.quantity_in)
        qty_out = _decimal_safe(movement.quantity_out)
        waste_m = _decimal_safe(movement.waste)
        if qty_in > 0 or qty_out > 0 or waste_m > 0:
            continue
        remark = (movement.remark or '').strip()
        if 'unit price' not in remark.lower():
            continue
        created = (
            timezone.localtime(movement.created_at)
            if timezone.is_aware(movement.created_at)
            else movement.created_at
        )
        price = _decimal_safe(movement.unit_price)
        if price > 0:
            last_price = price
        raw_net = run_in - run_waste - run_out
        net = _floor_zero(raw_net)
        balance_after = run_in * last_price
        stock_after = net * last_price
        timeline.append({
            'sort_at_ts': _sort_ts(created),
            'at_display': created.strftime('%Y-%m-%d %I:%M %p'),
            'event': 'Unit price changed',
            'kind': 'price',
            'change': f"New price {_money_str(last_price)}",
            'unit_price': _money_str(last_price),
            'line_value': '—',
            'balance_after': _money_str(balance_after),
            'stock_balance_remaining': _money_str(stock_after),
            'net_quantity': _qty_text(net),
            'quantity_in_total': _qty_text(run_in),
            'calculation': (
                f"Unit price set to {_money_str(last_price)} · "
                f"Balance = {_qty_text(run_in)} × {_money_str(last_price)} · "
                f"Stock on hand = {_qty_text(net)} × {_money_str(last_price)}"
            ),
            'detail': remark,
            'net_warning': raw_net < 0,
        })

    timeline.sort(key=lambda e: e['sort_at_ts'], reverse=True)
    return timeline


@login_required
@company_admin_or_permission_required('inventory.view_inventory', raise_exception=True)
@require_GET
def ajax_financial_timeline(request):
    """Calculation log for Balance or Stock balance remaining (from receipts/issues/waste)."""
    pk = request.GET.get('inventory') or request.GET.get('id') or request.GET.get('pk')
    focus = (request.GET.get('focus') or 'balance').strip().lower()
    if focus not in ('balance', 'remaining', 'stock_remaining'):
        focus = 'balance'
    if not pk:
        return JsonResponse({'success': False, 'message': 'Missing inventory id'}, status=400)
    inv = get_object_or_404(_inventory_queryset(request), pk=pk)
    inv = prepare_inventory_for_panel(inv.pk) or inv
    timeline = _build_financial_timeline(inv)
    data = {
        'success': True,
        'focus': focus,
        'product_name': inv.product_name,
        'timeline': timeline,
        'timeline_count': len(timeline),
        'formula_balance': 'Balance = Quantity In × Unit Price (total value of stock received)',
        'formula_remaining': 'Stock balance remaining = Net Qty × Unit Price (value of stock still on hand)',
    }
    _enrich_stock_panel_totals(data, inv)
    resp = JsonResponse(data)
    apply_no_cache_headers(resp)
    return resp


@login_required
@company_admin_or_permission_required('inventory.view_inventory', raise_exception=True)
@require_GET
def ajax_price_history(request):
    """Unit price & value history — same transaction log as Balance / Stock remaining panels."""
    pk = request.GET.get('inventory') or request.GET.get('id') or request.GET.get('pk')
    if not pk:
        return JsonResponse({'success': False, 'message': 'Missing inventory id'}, status=400)
    inv = get_object_or_404(_inventory_queryset(request), pk=pk)
    inv = prepare_inventory_for_panel(inv.pk) or inv
    timeline = _build_financial_timeline(inv)
    data = {
        'success': True,
        'product_name': inv.product_name,
        'timeline': timeline,
        'timeline_count': len(timeline),
    }
    _enrich_stock_panel_totals(data, inv)
    resp = JsonResponse(data)
    apply_no_cache_headers(resp)
    return resp


@login_required
@company_admin_or_permission_required('inventory.view_inventory', raise_exception=True)
@require_GET
def ajax_stock_summary(request):
    pk = request.GET.get('inventory') or request.GET.get('id') or request.GET.get('pk')
    if not pk:
        return JsonResponse({'success': False, 'message': 'Missing inventory id'}, status=400)
    inv = get_object_or_404(_inventory_queryset(request), pk=pk)
    inv = prepare_inventory_for_panel(inv.pk) or inv
    unit = inv.unit_label or ''
    issue_count = getattr(inv, 'issue_count', None)
    receipt_count = getattr(inv, 'receipt_count', None)
    waste_log_count = getattr(inv, 'waste_log_count', None)
    if issue_count is None:
        issue_count = InventoryIssue.objects.filter(inventory_id=inv.pk).count()
    if receipt_count is None:
        receipt_count = InventoryReceipt.objects.filter(inventory_id=inv.pk).count()
    if waste_log_count is None:
        waste_log_count = WasteLog.objects.filter(inventory_id=inv.pk).count()
    data = {
        'success': True,
        'product_name': inv.product_name,
        'formula': 'Net Qty = Quantity In − Waste − Quantity Out',
        'balance_note': 'Balance qty is the available stock for this product (same as Net Qty).',
        'has_receipts': receipt_count > 0,
        'has_issues': issue_count > 0,
        'has_waste_logs': waste_log_count > 0,
        'receipt_count': receipt_count,
        'issue_count': issue_count,
        'waste_log_count': waste_log_count,
    }
    _enrich_stock_panel_totals(data, inv)
    resp = JsonResponse(data)
    apply_no_cache_headers(resp)
    return resp
