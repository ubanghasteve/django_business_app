# -*- coding: utf-8 -*-
"""
Store views: dashboard, list (with cache), create, update, delete, detail, print, PDF, AJAX.
All querysets scoped via for_user_queryset(Store, request.user, request, account_lookup='account').
Cache key: store_list_{company_id}; cleared on create/update/delete/status_change.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count, Case, When, IntegerField, F, ExpressionWrapper, DecimalField
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.core.cache import cache
from datetime import date, timedelta
import calendar

from apps.core.permissions import company_admin_or_permission_required
from apps.core.ownership import for_user_queryset, get_account_for_user, is_company_admin
from apps.core.utils import get_company_profile_for_user, apply_no_cache_headers
from .models import Store, WasteLog, StoreCategory, StoreCustomField, StoreCustomForm, StoreLayout
from apps.waybills.utils.quantity_parser import extract_numeric_value


def _store_queryset(request):
    """Queryset for current user: account-scoped, plus records with no account but same company (so counts show). Exclude soft-deleted (offline sync)."""
    base = for_user_queryset(
        Store, request.user, request, account_lookup='account'
    ).filter(is_deleted=False).select_related('company', 'created_by')
    account = get_account_for_user(request.user)
    company = get_company_profile_for_user(request.user, request)
    if account and company:
        from django.db.models import Q
        extra = Store.objects.filter(account__isnull=True, company=company, is_deleted=False).select_related('company', 'created_by')
        if not is_company_admin(request.user, request):
            extra = extra.filter(created_by=request.user)
        base = (base | extra).distinct()
    elif not account and company:
        base = Store.objects.filter(company=company, is_deleted=False).select_related('company', 'created_by')
        if not is_company_admin(request.user, request):
            base = base.filter(created_by=request.user)
    return base


def _clear_store_list_cache(request):
    company = get_company_profile_for_user(request.user, request)
    if company:
        cache.delete(f"store_list_{company.id}")


def _store_document_context(request, obj):
    """Context for store detail/print/PDF: company details and theme, no signature."""
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


def _parse_store_list_date_range(request):
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


def _store_list_document_context(request, object_list, date_label):
    """Context for store list print/PDF: company details, logo, theme, object_list, no signature."""
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
@company_admin_or_permission_required('store.view_store', raise_exception=True)
@never_cache
def store_dashboard(request):
    """Dashboard with summary cards: total products, total quantity in, total quantity out, stock value remaining."""
    company = get_company_profile_for_user(request.user, request)
    qs = _store_queryset(request)
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
    response = render(request, 'store/dashboard.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('store.view_store', raise_exception=True)
@never_cache
def dashboard_stats_json(request):
    """JSON endpoint for dashboard card stats. No-cache so modals always get fresh counts."""
    company = get_company_profile_for_user(request.user, request)
    currency_symbol = getattr(company, 'currency_symbol', '₦') if company else '₦'
    currency_code = getattr(company, 'currency_code', 'NGN') if company else 'NGN'
    qs = _store_queryset(request)
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
@company_admin_or_permission_required('store.view_store', raise_exception=True)
def store_list(request):
    """List with search, filter, pagination. Card stats from full dataset; table from filtered.
    GET responses are cacheable by the browser for 60s (pagination, filters) for faster back/forward."""
    company = get_company_profile_for_user(request.user, request)
    base_qs = _store_queryset(request).order_by('sn')
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
    admin_flag = is_company_admin(request.user, request)
    can_approve_store = admin_flag or request.user.has_perm('store.can_approve_store')
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
        'approval_choices': Store.APPROVAL_STATUS_CHOICES,
        'stock_choices': Store.STOCK_STATUS_CHOICES,
        'workflow_choices': Store.WORKFLOW_STATUS_CHOICES,
        'user_currency_symbol': currency_symbol,
        'user_currency_code': currency_code,
        'can_approve_store': can_approve_store,
    }
    if request.headers.get('X-Pagination-Ajax') == '1':
        rows_html = render_to_string(
            'store/store_list_rows_partial.html',
            context,
            request=request,
        )
        pagination_html = render_to_string(
            'store/store_list_pagination_partial.html',
            context,
            request=request,
        )
        return JsonResponse({'rows_html': rows_html, 'pagination_html': pagination_html})
    response = render(request, 'store/store_list.html', context)
    response['Cache-Control'] = 'private, max-age=60'
    return response


@login_required
@company_admin_or_permission_required('store.add_store', raise_exception=True)
@never_cache
def store_create(request):
    if request.method == 'POST':
        company = get_company_profile_for_user(request.user, request)
        if not company:
            messages.error(request, 'Company profile is required to create store.')
            resp = redirect('store:list')
            apply_no_cache_headers(resp)
            return resp
        from .forms import StoreForm
        form = StoreForm(request.POST, user=request.user)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.created_by = request.user
            obj.save()
            _clear_store_list_cache(request)
            messages.success(request, 'Store record created.')
            resp = redirect('store:list')
            apply_no_cache_headers(resp)
            return resp
    else:
        from .forms import StoreForm
        form = StoreForm(user=request.user)
    response = render(request, 'store/store_form.html', {'form': form, 'is_edit': False})
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('store.change_store', raise_exception=True)
@never_cache
def store_update(request, pk):
    qs = _store_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    if request.method == 'POST':
        from .forms import StoreForm
        form = StoreForm(request.POST, instance=obj, user=request.user)
        if form.is_valid():
            form.save()
            _clear_store_list_cache(request)
            messages.success(request, 'Store updated.')
            resp = redirect('store:list')
            apply_no_cache_headers(resp)
            return resp
    else:
        from .forms import StoreForm
        form = StoreForm(instance=obj, user=request.user)
    response = render(request, 'store/store_form.html', {'form': form, 'object': obj, 'is_edit': True})
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('store.delete_store', raise_exception=True)
def store_confirm_delete(request, pk):
    qs = _store_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    response = render(request, 'store/store_confirm_delete.html', {'object': obj})
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('store.delete_store', raise_exception=True)
@require_POST
def store_delete(request, pk):
    qs = _store_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    company_id = obj.company_id
    try:
        obj.delete()
    except Exception as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
        messages.error(request, f'Error deleting record: {e}')
        return redirect('store:list')
    Store.renumber_sn_for_company(company_id)
    _clear_store_list_cache(request)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    messages.success(request, 'Store record deleted.')
    resp = redirect('store:list')
    apply_no_cache_headers(resp)
    return resp


@login_required
@company_admin_or_permission_required('store.view_store', raise_exception=True)
@never_cache
def store_detail(request, pk):
    qs = _store_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    context = _store_document_context(request, obj)
    response = render(request, 'store/store_detail.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('store.view_store', raise_exception=True)
@never_cache
def store_product_report(request, pk):
    """Product ledger / report: full movement history for one store record with totals."""
    qs = _store_queryset(request)
    product = get_object_or_404(qs, pk=pk)
    # Show most recent movements first in the report (newest at the top).
    # Only select columns used by the template/filters to keep this endpoint fast.
    movements = (
        product.movements.all()
        .select_related('created_by')
        .only(
            'id',
            'product_id',
            'date',
            'created_at',
            'created_by__first_name',
            'created_by__last_name',
            'created_by__email',
            'opening_stock',
            'opening_stock_input',
            'quantity_in',
            'quantity_out',
            'waste',
            'waste_input',
            'quantity_after',
            'unit_price',
            'balance',
            'stock_balance_remaining',
            'stock_status',
            'approval_status',
            'remark',
        )
        .order_by('-date', '-created_at', '-pk')
    )
    # --- Filters & search for movements (accurate, multi-field) ---
    search = (request.GET.get('search') or '').strip()
    approval_filter = (request.GET.get('approval_status') or '').strip()
    stock_filter = (request.GET.get('stock_status') or '').strip()
    date_from = (request.GET.get('date_from') or '').strip()
    date_to = (request.GET.get('date_to') or '').strip()
    min_quantity = (request.GET.get('min_quantity') or '').strip()
    max_quantity = (request.GET.get('max_quantity') or '').strip()

    if approval_filter and approval_filter in dict(Store.APPROVAL_STATUS_CHOICES):
        movements = movements.filter(approval_status=approval_filter)
    if stock_filter and stock_filter in dict(Store.STOCK_STATUS_CHOICES):
        movements = movements.filter(stock_status=stock_filter)
    if date_from:
        movements = movements.filter(date__gte=date_from)
    if date_to:
        movements = movements.filter(date__lte=date_to)
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

    # Totals stay in sync with the main store table for this row:
    # use the authoritative Store fields for quantity in/out and remaining/value.
    total_qty_in = product.quantity_in
    total_qty_out = product.quantity_out
    total_waste = product.waste
    actual_quantity = product.actual_quantity
    current_stock = product.remaining_quantity
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
        'current_stock': current_stock,
        'total_stock_value_remaining': total_stock_value_remaining,
        'total_waste_value': total_waste_value,
        'user_currency_symbol': currency_symbol,
        'search': search,
        'date_from': date_from,
        'date_to': date_to,
        'min_quantity': min_quantity,
        'max_quantity': max_quantity,
    }
    # AJAX refresh (for realtime-like updates without full page reload)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' and request.GET.get('format') == 'json':
        rows_html = render_to_string(
            'store/product_report_rows_partial.html',
            context,
            request=request,
        )
        resp = JsonResponse({
            'rows_html': rows_html,
            'total_qty_in': str(total_qty_in),
            'total_qty_out': str(total_qty_out),
            'total_waste': str(total_waste),
            'actual_quantity': str(actual_quantity),
            'current_stock': str(product.balance_quantity),
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
            'opening_stock': str(product.opening_stock),
            'opening_stock_input': getattr(product, 'opening_stock_input', '') or '',
            'waste': str(product.waste),
            'unit_label': getattr(product, 'unit_label', ''),
        })
        apply_no_cache_headers(resp)
        return resp
    response = render(request, 'store/product_report.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('store.print_store', raise_exception=True)
@never_cache
def store_print(request, pk):
    qs = _store_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    context = _store_document_context(request, obj)
    response = render(request, 'store/store_print.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('store.download_store', raise_exception=True)
@never_cache
def store_pdf(request, pk):
    qs = _store_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    try:
        from django.template.loader import get_template
        from weasyprint import HTML
        context = _store_document_context(request, obj)
        if context.get('company_logo'):
            context['company_logo'] = request.build_absolute_uri(context['company_logo'])
        template = get_template('store/store_print.html')
        html_str = template.render(context, request)
        html = HTML(string=html_str)
        pdf_file = html.write_pdf()
        response = HttpResponse(pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="store-{obj.transaction_id}.pdf"'
        apply_no_cache_headers(response)
        return response
    except ImportError:
        resp = redirect('store:print', pk=pk)
        apply_no_cache_headers(resp)
        return resp


@login_required
@company_admin_or_permission_required('store.print_store', raise_exception=True)
@never_cache
def store_list_print(request):
    """Print full store table with optional date range. Company details + logo, no signature. A4 zoom, text wrap."""
    qs = _store_queryset(request).order_by('sn')
    filter_kwargs, date_label = _parse_store_list_date_range(request)
    if filter_kwargs:
        qs = qs.filter(**filter_kwargs)
    object_list = list(qs)
    context = _store_list_document_context(request, object_list, date_label)
    context['approval_choices'] = Store.APPROVAL_STATUS_CHOICES
    response = render(request, 'store/store_list_print.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('store.download_store', raise_exception=True)
@never_cache
def store_list_pdf(request):
    """Download full store table as PDF with optional date range. Same layout as print (A4, text wrap)."""
    qs = _store_queryset(request).order_by('sn')
    filter_kwargs, date_label = _parse_store_list_date_range(request)
    if filter_kwargs:
        qs = qs.filter(**filter_kwargs)
    object_list = list(qs)
    try:
        from django.template.loader import get_template
        from weasyprint import HTML
        context = _store_list_document_context(request, object_list, date_label)
        context['approval_choices'] = Store.APPROVAL_STATUS_CHOICES
        if context.get('company_logo'):
            context['company_logo'] = request.build_absolute_uri(context['company_logo'])
        template = get_template('store/store_list_print.html')
        html_str = template.render(context, request)
        html = HTML(string=html_str)
        pdf_file = html.write_pdf()
        filename = f"store-list-{timezone.now().strftime('%Y%m%d-%H%M')}.pdf"
        response = HttpResponse(pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        apply_no_cache_headers(response)
        return response
    except ImportError:
        from django.urls import reverse
        url = reverse('store:list_print') + ('?' + request.GET.urlencode() if request.GET else '')
        return redirect(url)


# ----- AJAX: auto-save on blur (spreadsheet-like UX) -----

@login_required
@company_admin_or_permission_required('store.add_store', raise_exception=True)
@require_POST
def ajax_create(request):
    """Create one store record from POST (table Add row). Returns JSON for row insert."""
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return JsonResponse({'success': False, 'message': 'Company profile is required.'}, status=400)
    from decimal import Decimal
    from .forms import StoreForm
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
        'date': request.POST.get('date') or None,
        'opening_stock': request.POST.get('opening_stock', '0'),
    }
    if not data['product_name']:
        return JsonResponse({'success': False, 'message': 'Product name is required.'}, status=400)
    form = StoreForm(data, user=request.user)
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
    _clear_store_list_cache(request)
    created_by_display = (obj.created_by.get_full_name() or obj.created_by.email or '—') if obj.created_by else '—'
    resp = JsonResponse({
        'success': True,
        'id': obj.pk,
        'uuid': str(obj.uuid),
        'sn': obj.sn,
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
        'opening_stock': str(obj.opening_stock),
        'opening_stock_input': getattr(obj, 'opening_stock_input', '') or '',
        'waste': str(obj.waste),
        'waste_input': getattr(obj, 'waste_input', '') or '',
        'stock_status': obj.stock_status,
        'stock_status_display': obj.get_stock_status_display(),
        'approval_status': obj.approval_status,
        'approval_status_display': obj.get_approval_status_display(),
        'remark': (obj.remark or '')[:50],
        'low_stock_threshold': str(obj.low_stock_threshold),
        'quantity_in_input': getattr(obj, 'quantity_in_input', ''),
        'quantity_out_input': getattr(obj, 'quantity_out_input', ''),
        'unit_price_input': getattr(obj, 'unit_price_input', ''),
        'low_stock_threshold_input': getattr(obj, 'low_stock_threshold_input', ''),
        'unit_label': getattr(obj, 'unit_label', '') or '',
        'created_by_display': created_by_display,
        'created_at': obj.created_at.strftime('%Y-%m-%d %I:%M:%S %p'),
        'date': obj.date.strftime('%Y-%m-%d') if obj.date else '',
    })
    resp['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    return resp


@login_required
@company_admin_or_permission_required('store.change_store', raise_exception=True)
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
    qs = _store_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    editable = {'product_name', 'category', 'company_name', 'vendor', 'stock_location', 'phone_number',
                'quantity_in', 'quantity_out', 'waste', 'unit_price', 'low_stock_threshold',
                'approval_status', 'workflow_status', 'remark', 'date', 'opening_stock'}
    if field not in editable:
        return JsonResponse({'success': False, 'message': 'Field not editable'}, status=400)
    if field in ('quantity_in', 'quantity_out', 'waste', 'unit_price', 'low_stock_threshold', 'opening_stock'):
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
        elif field == 'opening_stock':
            obj.opening_stock_input = raw_text
        elif field == 'waste':
            obj.waste_input = raw_text

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
    elif field == 'date':
        # Parse date string in YYYY-MM-DD format
        from datetime import date as date_type
        if value and str(value).strip():
            try:
                value = date_type.fromisoformat(str(value).strip())
            except ValueError:
                return JsonResponse({'success': False, 'message': 'Invalid date format'}, status=400)
        else:
            value = None
    if field in ('approval_status', 'workflow_status'):
        # Only company admin or users with explicit approval permission may
        # change approval/workflow status via this generic field updater.
        if not (is_company_admin(request.user, request) or request.user.has_perm('store.can_approve_store')):
            return JsonResponse(
                {'success': False, 'message': 'You do not have permission to approve store records.'},
                status=403,
            )
        if field == 'approval_status' and value not in dict(Store.APPROVAL_STATUS_CHOICES):
            value = obj.approval_status
        elif field == 'workflow_status' and value not in dict(Store.WORKFLOW_STATUS_CHOICES):
            value = obj.workflow_status
    setattr(obj, field, value)
    obj.save()
    # Reload from DB so stock_status and balance_quantity are exactly what was persisted
    obj.refresh_from_db()
    _clear_store_list_cache(request)
    resp_data = {
        'success': True,
        'remaining_quantity': str(obj.remaining_quantity),
        'actual_quantity': str(obj.actual_quantity),
        'net_quantity': str(obj.net_quantity),
        'total_amount': str(obj.total_amount),
        'stock_balance_remaining': str(obj.stock_balance_remaining),
        'balance_quantity': str(obj.balance_quantity),
        'waste': str(obj.waste),
        'date': str(obj.date) if obj.date else '',
        'waste_value': str(obj.waste_value),
        'stock_status': obj.stock_status,
        'stock_status_display': obj.get_stock_status_display(),
        'unit_price': str(obj.unit_price),
        'quantity_in': str(obj.quantity_in),
        'quantity_out': str(obj.quantity_out),
        'low_stock_threshold': str(obj.low_stock_threshold),
        'opening_stock': str(obj.opening_stock),
        'opening_stock_input': getattr(obj, 'opening_stock_input', '') or '',
        'waste_input': getattr(obj, 'waste_input', '') or '',
        # Echo back the raw mixed-input text so the frontend can keep showing
        # exactly what the user typed even after recomputations.
        'quantity_in_input': getattr(obj, 'quantity_in_input', ''),
        'quantity_out_input': getattr(obj, 'quantity_out_input', ''),
        'unit_price_input': getattr(obj, 'unit_price_input', ''),
        'low_stock_threshold_input': getattr(obj, 'low_stock_threshold_input', ''),
        'unit_label': getattr(obj, 'unit_label', '') or '',
        'remark': obj.remark or '',
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
@company_admin_or_permission_required('store.can_approve_store', raise_exception=True)
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
    qs = _store_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    if approval and approval in dict(Store.APPROVAL_STATUS_CHOICES):
        obj.approval_status = approval
        if approval == 'approved':
            obj.approved_by = request.user
            obj.approved_at = timezone.now()
        else:
            obj.approved_by = None
            obj.approved_at = None
    if workflow and workflow in dict(Store.WORKFLOW_STATUS_CHOICES):
        obj.workflow_status = workflow
    save_fields = ['approval_status', 'workflow_status', 'updated_at']
    if approval and approval in dict(Store.APPROVAL_STATUS_CHOICES):
        save_fields.extend(['approved_by', 'approved_at'])
    obj.save(update_fields=save_fields)
    _clear_store_list_cache(request)
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
    ).select_related('store', 'created_by')
    account = get_account_for_user(request.user)
    company = get_company_profile_for_user(request.user, request)
    if account and company:
        from django.db.models import Q
        extra = WasteLog.objects.filter(account__isnull=True, company=company).select_related('store', 'created_by')
        base = (base | extra).distinct()
    elif not account and company:
        base = WasteLog.objects.filter(company=company).select_related('store', 'created_by')
    return base


@login_required
@company_admin_or_permission_required('store.view_store', raise_exception=True)
@never_cache
def waste_list(request):
    """List all waste logs with filtering by store, reason, date range."""
    company = get_company_profile_for_user(request.user, request)
    currency_symbol = getattr(company, 'currency_symbol', '₦') if company else '₦'
    base_qs = _waste_log_queryset(request)
    
    waste_reason = request.GET.get('reason', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    store_id = request.GET.get('store', '').strip()
    search = request.GET.get('search', '').strip()
    
    qs = base_qs
    if waste_reason:
        qs = qs.filter(reason=waste_reason)
    if date_from:
        qs = qs.filter(waste_date__gte=date_from)
    if date_to:
        qs = qs.filter(waste_date__lte=date_to)
    if store_id:
        qs = qs.filter(store_id=store_id)
    if search:
        qs = qs.filter(
            Q(store__product_name__icontains=search) |
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
        'store_list': Store.objects.filter(
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
    response = render(request, 'store/waste_log_list.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('store.view_store', raise_exception=True)
@never_cache
def waste_create(request):
    """Create a new waste log entry."""
    company = get_company_profile_for_user(request.user, request)
    if request.method == 'POST':
        from .forms import WasteLogForm
        form = WasteLogForm(request.POST, user=request.user, company=company)
        if form.is_valid():
            waste_log = form.save()
            messages.success(request, f'Waste log created: {waste_log.quantity} of {waste_log.store.product_name}.')
            resp = redirect('store:waste_list')
            apply_no_cache_headers(resp)
            return resp
    else:
        from .forms import WasteLogForm
        initial_store = request.GET.get('store', '')
        form = WasteLogForm(user=request.user, company=company)
        if initial_store:
            try:
                inv = Store.objects.get(pk=initial_store, is_deleted=False)
                form.fields['store'].queryset = Store.objects.filter(pk=initial_store)
                form.initial['store'] = inv
            except Store.DoesNotExist:
                pass
    response = render(request, 'store/waste_log_form.html', {'form': form, 'is_edit': False})
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('store.delete_store', raise_exception=True)
@require_POST
def waste_delete(request, pk):
    """Delete a waste log entry."""
    qs = _waste_log_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    store_name = obj.store.product_name
    obj.delete()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    messages.success(request, f'Waste log for {store_name} deleted.')
    resp = redirect('store:waste_list')
    apply_no_cache_headers(resp)
    return resp


@login_required
@company_admin_or_permission_required('store.view_store', raise_exception=True)
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


# ----- Category Views -----

def _category_queryset(request):
    from apps.core.ownership import for_user_queryset
    base = for_user_queryset(
        StoreCategory, request.user, request, account_lookup='account'
    )
    company = get_company_profile_for_user(request.user, request)
    if company:
        base = base.filter(company=company) | StoreCategory.objects.filter(company=company, account__isnull=True)
    return base.distinct()


@login_required
@company_admin_or_permission_required('store.view_store_category', raise_exception=True)
@never_cache
def category_list(request):
    qs = _category_queryset(request)
    search = request.GET.get('search', '').strip()
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(description__icontains=search))
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))
    context = {
        'page_obj': page_obj,
        'object_list': page_obj.object_list,
        'search': search,
    }
    response = render(request, 'store/category_list.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('store.add_store_category', raise_exception=True)
@never_cache
def category_create(request):
    company = get_company_profile_for_user(request.user, request)
    if request.method == 'POST':
        form = StoreCategoryForm(request.POST, user=request.user, company=company)
        if form.is_valid():
            form.save()
            messages.success(request, 'Category created.')
            resp = redirect('store:category_list')
            apply_no_cache_headers(resp)
            return resp
    else:
        form = StoreCategoryForm(user=request.user, company=company)
    response = render(request, 'store/category_form.html', {'form': form, 'is_edit': False})
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('store.change_store_category', raise_exception=True)
@never_cache
def category_update(request, pk):
    qs = _category_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    company = get_company_profile_for_user(request.user, request)
    if request.method == 'POST':
        form = StoreCategoryForm(request.POST, instance=obj, user=request.user, company=company)
        if form.is_valid():
            form.save()
            messages.success(request, 'Category updated.')
            resp = redirect('store:category_list')
            apply_no_cache_headers(resp)
            return resp
    else:
        form = StoreCategoryForm(instance=obj, user=request.user, company=company)
    response = render(request, 'store/category_form.html', {'form': form, 'object': obj, 'is_edit': True})
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('store.delete_store_category', raise_exception=True)
@require_POST
def category_delete(request, pk):
    qs = _category_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    name = obj.name
    obj.delete()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    messages.success(request, f'Category "{name}" deleted.')
    resp = redirect('store:category_list')
    apply_no_cache_headers(resp)
    return resp


# ----- Custom Field Views -----

def _custom_field_queryset(request):
    from apps.core.ownership import for_user_queryset
    base = for_user_queryset(
        StoreCustomField, request.user, request, account_lookup='account'
    )
    company = get_company_profile_for_user(request.user, request)
    if company:
        base = base.filter(company=company) | StoreCustomField.objects.filter(company=company, account__isnull=True)
    return base.distinct()


@login_required
@company_admin_or_permission_required('store.view_store_customfield', raise_exception=True)
@never_cache
def custom_field_list(request):
    qs = _custom_field_queryset(request)
    search = request.GET.get('search', '').strip()
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(field_key__icontains=search))
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))
    context = {
        'page_obj': page_obj,
        'object_list': page_obj.object_list,
        'search': search,
    }
    response = render(request, 'store/custom_field_list.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('store.add_store_customfield', raise_exception=True)
@never_cache
def custom_field_create(request):
    company = get_company_profile_for_user(request.user, request)
    if request.method == 'POST':
        form = StoreCustomFieldForm(request.POST, user=request.user, company=company)
        if form.is_valid():
            form.save()
            messages.success(request, 'Custom field created.')
            resp = redirect('store:custom_field_list')
            apply_no_cache_headers(resp)
            return resp
    else:
        form = StoreCustomFieldForm(user=request.user, company=company)
    response = render(request, 'store/custom_field_form.html', {'form': form, 'is_edit': False})
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('store.change_store_customfield', raise_exception=True)
@never_cache
def custom_field_update(request, pk):
    qs = _custom_field_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    company = get_company_profile_for_user(request.user, request)
    if request.method == 'POST':
        form = StoreCustomFieldForm(request.POST, instance=obj, user=request.user, company=company)
        if form.is_valid():
            form.save()
            messages.success(request, 'Custom field updated.')
            resp = redirect('store:custom_field_list')
            apply_no_cache_headers(resp)
            return resp
    else:
        form = StoreCustomFieldForm(instance=obj, user=request.user, company=company)
    response = render(request, 'store/custom_field_form.html', {'form': form, 'object': obj, 'is_edit': True})
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('store.delete_store_customfield', raise_exception=True)
@require_POST
def custom_field_delete(request, pk):
    qs = _custom_field_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    name = obj.name
    obj.delete()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    messages.success(request, f'Custom field "{name}" deleted.')
    resp = redirect('store:custom_field_list')
    apply_no_cache_headers(resp)
    return resp


# ----- Custom Form Views -----

def _custom_form_queryset(request):
    from apps.core.ownership import for_user_queryset
    base = for_user_queryset(
        StoreCustomForm, request.user, request, account_lookup='account'
    )
    company = get_company_profile_for_user(request.user, request)
    if company:
        base = base.filter(company=company) | StoreCustomForm.objects.filter(company=company, account__isnull=True)
    return base.distinct()


@login_required
@company_admin_or_permission_required('store.view_store_customform', raise_exception=True)
@never_cache
def custom_form_list(request):
    qs = _custom_form_queryset(request)
    search = request.GET.get('search', '').strip()
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(description__icontains=search))
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))
    context = {
        'page_obj': page_obj,
        'object_list': page_obj.object_list,
        'search': search,
    }
    response = render(request, 'store/custom_form_list.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('store.add_store_customform', raise_exception=True)
@never_cache
def custom_form_create(request):
    company = get_company_profile_for_user(request.user, request)
    if request.method == 'POST':
        form = StoreCustomFormForm(request.POST, user=request.user, company=company)
        if form.is_valid():
            form.save()
            messages.success(request, 'Custom form created.')
            resp = redirect('store:custom_form_list')
            apply_no_cache_headers(resp)
            return resp
    else:
        form = StoreCustomFormForm(user=request.user, company=company)
    response = render(request, 'store/custom_form_form.html', {'form': form, 'is_edit': False})
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('store.change_store_customform', raise_exception=True)
@never_cache
def custom_form_update(request, pk):
    qs = _custom_form_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    company = get_company_profile_for_user(request.user, request)
    if request.method == 'POST':
        form = StoreCustomFormForm(request.POST, instance=obj, user=request.user, company=company)
        if form.is_valid():
            form.save()
            messages.success(request, 'Custom form updated.')
            resp = redirect('store:custom_form_list')
            apply_no_cache_headers(resp)
            return resp
    else:
        form = StoreCustomFormForm(instance=obj, user=request.user, company=company)
    response = render(request, 'store/custom_form_form.html', {'form': form, 'object': obj, 'is_edit': True})
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('store.view_store_customform', raise_exception=True)
@never_cache
def custom_form_detail(request, pk):
    qs = _custom_form_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    company = get_company_profile_for_user(request.user, request)
    currency_symbol = getattr(company, 'currency_symbol', '₦') if company else '₦'
    context = {
        'object': obj,
        'currency_symbol': currency_symbol,
        'company_profile': company,
    }
    response = render(request, 'store/custom_form_detail.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('store.delete_store_customform', raise_exception=True)
@require_POST
def custom_form_delete(request, pk):
    qs = _custom_form_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    name = obj.name
    obj.delete()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    messages.success(request, f'Custom form "{name}" deleted.')
    resp = redirect('store:custom_form_list')
    apply_no_cache_headers(resp)
    return resp


# ----- Layout Views -----

def _layout_queryset(request):
    from apps.core.ownership import for_user_queryset
    base = for_user_queryset(
        StoreLayout, request.user, request, account_lookup='account'
    )
    company = get_company_profile_for_user(request.user, request)
    if company:
        base = base.filter(company=company) | StoreLayout.objects.filter(company=company, account__isnull=True)
    return base.distinct()


@login_required
@company_admin_or_permission_required('store.view_store_layout', raise_exception=True)
@never_cache
def layout_list(request):
    qs = _layout_queryset(request)
    search = request.GET.get('search', '').strip()
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(description__icontains=search))
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))
    context = {
        'page_obj': page_obj,
        'object_list': page_obj.object_list,
        'search': search,
    }
    response = render(request, 'store/layout_list.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('store.add_store_layout', raise_exception=True)
@never_cache
def layout_create(request):
    company = get_company_profile_for_user(request.user, request)
    if request.method == 'POST':
        form = StoreLayoutForm(request.POST, user=request.user, company=company)
        if form.is_valid():
            form.save()
            messages.success(request, 'Layout created.')
            resp = redirect('store:layout_list')
            apply_no_cache_headers(resp)
            return resp
    else:
        form = StoreLayoutForm(user=request.user, company=company)
    response = render(request, 'store/layout_form.html', {'form': form, 'is_edit': False})
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('store.change_store_layout', raise_exception=True)
@never_cache
def layout_update(request, pk):
    qs = _layout_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    company = get_company_profile_for_user(request.user, request)
    if request.method == 'POST':
        form = StoreLayoutForm(request.POST, instance=obj, user=request.user, company=company)
        if form.is_valid():
            form.save()
            messages.success(request, 'Layout updated.')
            resp = redirect('store:layout_list')
            apply_no_cache_headers(resp)
            return resp
    else:
        form = StoreLayoutForm(instance=obj, user=request.user, company=company)
    response = render(request, 'store/layout_form.html', {'form': form, 'object': obj, 'is_edit': True})
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('store.view_store_layout', raise_exception=True)
@never_cache
def layout_preview(request, pk):
    qs = _layout_queryset(request)
    layout = get_object_or_404(qs, pk=pk)
    company = get_company_profile_for_user(request.user, request)
    currency_symbol = getattr(company, 'currency_symbol', '₦') if company else '₦'
    qs = _store_queryset(request)
    search = request.GET.get('search', '').strip()
    if search:
        for term in search.split():
            t = term.strip()
            if t:
                qs = qs.filter(
                    Q(product_name__icontains=t) | Q(category__icontains=t) | Q(transaction_id__icontains=t)
                )
    items = qs[:20]
    grand_total = sum(float(getattr(i, 'total_amount', 0) or 0) for i in items)
    context = {
        'layout': layout,
        'items': items,
        'grand_total': grand_total,
        'currency_symbol': currency_symbol,
        'company_profile': company,
        'search': search,
    }
    response = render(request, 'store/layout_preview.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('store.view_store_layout', raise_exception=True)
@never_cache
def layout_management(request):
    qs = _layout_queryset(request)
    company = get_company_profile_for_user(request.user, request)
    currency_symbol = getattr(company, 'currency_symbol', '₦') if company else '₦'
    default_layout = qs.filter(is_default=True).first()
    context = {
        'page_obj': qs,
        'default_layout': default_layout,
        'currency_symbol': currency_symbol,
        'company_profile': company,
    }
    response = render(request, 'store/layout_management.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('store.delete_store_layout', raise_exception=True)
@require_POST
def layout_delete(request, pk):
    qs = _layout_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    name = obj.name
    obj.delete()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    messages.success(request, f'Layout "{name}" deleted.')
    resp = redirect('store:layout_list')
    apply_no_cache_headers(resp)
    return resp
