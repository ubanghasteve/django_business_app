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

from apps.core.permissions import company_admin_or_permission_required
from apps.core.ownership import for_user_queryset, get_account_for_user, is_company_admin
from apps.core.utils import get_company_profile_for_user, apply_no_cache_headers
from .models import Inventory
from apps.waybills.utils.quantity_parser import extract_numeric_value


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


def _inventory_list_document_context(request, object_list, date_label):
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
    return {
        'object_list': object_list,
        'date_label': date_label,
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
        total_stock_value_remaining=Sum('stock_balance_remaining'),
    )
    total_quantity_in = agg.get('total_in') or 0
    total_quantity_out = agg.get('total_out') or 0
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
def inventory_list(request):
    """List with search, filter, pagination. Card stats from full dataset; table from filtered.
    GET responses are cacheable by the browser for 60s (pagination, filters) for faster back/forward."""
    company = get_company_profile_for_user(request.user, request)
    base_qs = _inventory_queryset(request).order_by('sn')
    # Card stats + approval/stock counts in 2 queries (was 8+)
    card_agg = base_qs.aggregate(
        total_in=Sum('quantity_in'),
        total_out=Sum('quantity_out'),
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
    paginator = Paginator(qs, 5)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    get_copy = request.GET.copy()
    if 'page' in get_copy:
        get_copy.pop('page', None)
    pagination_base_query = get_copy.urlencode()
    # Currency from company admin settings (so list and AJAX partials use same source)
    currency_symbol = getattr(company, 'currency_symbol', '₦') if company else '₦'
    currency_code = getattr(company, 'currency_code', 'NGN') if company else 'NGN'
    context = {
        'page_obj': page_obj,
        'pagination_base_query': pagination_base_query,
        'object_list': page_obj.object_list,
        'total_products': status_counts.get('total_products', 0),
        'total_quantity_in': card_agg.get('total_in') or 0,
        'total_quantity_out': card_agg.get('total_out') or 0,
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
        'approval_choices': Inventory.APPROVAL_STATUS_CHOICES,
        'stock_choices': Inventory.STOCK_STATUS_CHOICES,
        'workflow_choices': Inventory.WORKFLOW_STATUS_CHOICES,
        'user_currency_symbol': currency_symbol,
        'user_currency_code': currency_code,
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
    obj.delete()
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
    # Paginate movements so very long histories don't block page load.
    # 100 rows per page keeps the ledger fast while still showing a rich history.
    paginator = Paginator(movements, 100)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    movements_page = page_obj.object_list

    # Totals stay in sync with the main inventory table for this row:
    # use the authoritative Inventory fields for quantity in/out and remaining/value.
    total_qty_in = product.quantity_in
    total_qty_out = product.quantity_out
    current_stock = product.remaining_quantity
    total_stock_value_remaining = product.stock_balance_remaining

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
        'current_stock': current_stock,
        'total_stock_value_remaining': total_stock_value_remaining,
        'user_currency_symbol': currency_symbol,
        'approval_choices': Inventory.APPROVAL_STATUS_CHOICES,
        'stock_choices': Inventory.STOCK_STATUS_CHOICES,
        'search': search,
        'approval_status_filter': approval_filter,
        'stock_status_filter': stock_filter,
        'date_from': date_from,
        'date_to': date_to,
        'min_quantity': min_quantity,
        'max_quantity': max_quantity,
    }
    # AJAX refresh (for realtime-like updates without full page reload)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' and request.GET.get('format') == 'json':
        rows_html = render_to_string(
            'inventory/product_report_rows_partial.html',
            context,
            request=request,
        )
        resp = JsonResponse({
            'rows_html': rows_html,
            'total_qty_in': str(total_qty_in),
            'total_qty_out': str(total_qty_out),
            'current_stock': str(current_stock),
            'total_stock_value_remaining': str(total_stock_value_remaining),
            'approval_status': getattr(product, 'approval_status', ''),
            'approval_status_display': product.get_approval_status_display() if product else '',
            'stock_status': getattr(product, 'stock_status', ''),
            'stock_status_display': product.get_stock_status_display() if product else '',
            # Mixed-input strings + unit label so the report header/cards can
            # mirror exactly what is shown on the main inventory list.
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
    """Print full inventory table with optional date range. Company details + logo, no signature. A4 zoom, text wrap."""
    qs = _inventory_queryset(request).order_by('sn')
    filter_kwargs, date_label = _parse_inventory_list_date_range(request)
    if filter_kwargs:
        qs = qs.filter(**filter_kwargs)
    object_list = list(qs)
    context = _inventory_list_document_context(request, object_list, date_label)
    context['approval_choices'] = Inventory.APPROVAL_STATUS_CHOICES
    response = render(request, 'inventory/inventory_list_print.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('inventory.download_inventory', raise_exception=True)
@never_cache
def inventory_list_pdf(request):
    """Download full inventory table as PDF with optional date range. Same layout as print (A4, text wrap)."""
    qs = _inventory_queryset(request).order_by('sn')
    filter_kwargs, date_label = _parse_inventory_list_date_range(request)
    if filter_kwargs:
        qs = qs.filter(**filter_kwargs)
    object_list = list(qs)
    try:
        from django.template.loader import get_template
        from weasyprint import HTML
        context = _inventory_list_document_context(request, object_list, date_label)
        context['approval_choices'] = Inventory.APPROVAL_STATUS_CHOICES
        if context.get('company_logo'):
            context['company_logo'] = request.build_absolute_uri(context['company_logo'])
        template = get_template('inventory/inventory_list_print.html')
        html_str = template.render(context, request)
        html = HTML(string=html_str)
        pdf_file = html.write_pdf()
        filename = f"inventory-list-{timezone.now().strftime('%Y%m%d-%H%M')}.pdf"
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
    if not obj.account_id and getattr(request.user, 'account_id', None):
        obj.account_id = request.user.account_id
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
        'company_name': (obj.company_name or '').strip() or (getattr(obj.company, 'company_name', None) or '—'),
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
                'quantity_in', 'quantity_out', 'unit_price', 'low_stock_threshold',
                'approval_status', 'workflow_status', 'remark'}
    if field not in editable:
        return JsonResponse({'success': False, 'message': 'Field not editable'}, status=400)
    if field in ('quantity_in', 'quantity_out', 'unit_price', 'low_stock_threshold'):
        from decimal import Decimal
        raw_text = str(value)
        # Store the original mixed text on the *_input fields so it persists.
        if field == 'quantity_in':
            obj.quantity_in_input = raw_text
        elif field == 'quantity_out':
            obj.quantity_out_input = raw_text
        elif field == 'unit_price':
            obj.unit_price_input = raw_text
        elif field == 'low_stock_threshold':
            obj.low_stock_threshold_input = raw_text

        # Parse out the numeric portion using the shared quantity parser.
        try:
            numeric = extract_numeric_value(raw_text)
            value = Decimal(str(numeric))
            # For price/threshold, guard against negative values.
            if field in ('unit_price', 'low_stock_threshold') and value < 0:
                value = Decimal('0')
        except Exception:
            # Fall back to the existing numeric value if parsing fails.
            value = getattr(obj, field, 0)
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
    _clear_inventory_list_cache(request)
    resp_data = {
        'success': True,
        'remaining_quantity': str(obj.remaining_quantity),
        'total_amount': str(obj.total_amount),
        'stock_balance_remaining': str(obj.stock_balance_remaining),
        'balance_quantity': str(obj.balance_quantity),
        'stock_status': obj.stock_status,
        'stock_status_display': obj.get_stock_status_display(),
        'unit_price': str(obj.unit_price),
        'quantity_in': str(obj.quantity_in),
        'quantity_out': str(obj.quantity_out),
        'low_stock_threshold': str(obj.low_stock_threshold),
        # Echo back the raw mixed-input text so the frontend can keep showing
        # exactly what the user typed even after recomputations.
        'quantity_in_input': getattr(obj, 'quantity_in_input', ''),
        'quantity_out_input': getattr(obj, 'quantity_out_input', ''),
        'unit_price_input': getattr(obj, 'unit_price_input', ''),
        'low_stock_threshold_input': getattr(obj, 'low_stock_threshold_input', ''),
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
