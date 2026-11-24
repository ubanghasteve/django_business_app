# -*- coding: utf-8 -*-
"""
Expense views: dashboard, list (with cache), create, update, delete, detail, print, PDF, AJAX.
All querysets scoped via for_user_queryset(Expense, request.user, request, account_lookup='account').
Cache key: expense_list_{company_id}; cleared on create/update/delete/status_change.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.core.cache import cache
from datetime import date, timedelta
import calendar

from apps.core.permissions import company_admin_or_permission_required
from apps.core.ownership import for_user_queryset, get_account_for_user, is_company_admin
from apps.core.utils import get_company_profile_for_user, apply_no_cache_headers
from .models import Expense


def _expense_queryset(request):
    """Queryset for current user: account-scoped, plus records with no account but same company (so counts show)."""
    base = for_user_queryset(
        Expense, request.user, request, account_lookup='account'
    ).select_related('company', 'created_by')
    account = get_account_for_user(request.user)
    company = get_company_profile_for_user(request.user, request)
    if account and company:
        from django.db.models import Q
        extra = Expense.objects.filter(account__isnull=True, company=company).select_related('company', 'created_by')
        if not is_company_admin(request.user, request):
            extra = extra.filter(created_by=request.user)
        base = (base | extra).distinct()
    elif not account and company:
        base = Expense.objects.filter(company=company).select_related('company', 'created_by')
        if not is_company_admin(request.user, request):
            base = base.filter(created_by=request.user)
    return base


def _clear_expense_list_cache(request):
    company = get_company_profile_for_user(request.user, request)
    if company:
        cache.delete(f"expense_list_{company.id}")


def _expense_document_context(request, obj):
    """Context for expense detail/print/PDF: company details and theme, no signature."""
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


def _parse_expense_list_date_range(request):
    """
    Parse GET params: range_type (all, day, week, month, quarter, year, custom),
    period_date (YYYY-MM-DD for day/week/month/quarter/year), date_from, date_to (for custom).
    Returns (queryset_filter_kwargs, date_label).
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
                filter_kwargs['expense_date__gte'] = d_from
            if date_to_s:
                d_to = date.fromisoformat(date_to_s)
                filter_kwargs['expense_date__lte'] = d_to
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
        filter_kwargs['expense_date'] = ref
        date_label = ref.strftime('%d %b %Y')
    elif range_type == 'week':
        week_start = ref - timedelta(days=ref.weekday())
        week_end = week_start + timedelta(days=6)
        filter_kwargs['expense_date__gte'] = week_start
        filter_kwargs['expense_date__lte'] = week_end
        date_label = f"{week_start.strftime('%d %b %Y')} – {week_end.strftime('%d %b %Y')} (Week)"
    elif range_type == 'month':
        start_of_month = ref.replace(day=1)
        _, last_day = calendar.monthrange(ref.year, ref.month)
        end_of_month = ref.replace(day=last_day)
        filter_kwargs['expense_date__gte'] = start_of_month
        filter_kwargs['expense_date__lte'] = end_of_month
        date_label = ref.strftime('%B %Y')
    elif range_type == 'quarter':
        quarter = (ref.month - 1) // 3 + 1
        quarter_start = date(ref.year, (quarter - 1) * 3 + 1, 1)
        quarter_end_month = quarter * 3
        _, qlast = calendar.monthrange(ref.year, quarter_end_month)
        quarter_end = date(ref.year, quarter_end_month, qlast)
        filter_kwargs['expense_date__gte'] = quarter_start
        filter_kwargs['expense_date__lte'] = quarter_end
        date_label = f"Q{quarter} {ref.year}"
    elif range_type == 'year':
        year_start = date(ref.year, 1, 1)
        year_end = date(ref.year, 12, 31)
        filter_kwargs['expense_date__gte'] = year_start
        filter_kwargs['expense_date__lte'] = year_end
        date_label = str(ref.year)
    else:
        return {}, 'All records'

    return filter_kwargs, date_label


def _expense_list_document_context(request, object_list, date_label):
    """Context for expense list print/PDF: company details, logo, theme, object_list, no signature."""
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
@company_admin_or_permission_required('expense.view_expense', raise_exception=True)
@never_cache
def expense_dashboard(request):
    """Dashboard with summary cards: total products, total quantity in, total quantity out."""
    qs = _expense_queryset(request)
    total_products = qs.count()
    agg = qs.aggregate(
        total_in=Sum('quantity_purchased'),
        total_out=Sum('quantity_out'),
        total_balance=Sum('total_amount'),
    )
    total_quantity_in = agg.get('total_in') or 0
    total_quantity_out = agg.get('total_out') or 0
    status_counts = {
        'draft': qs.filter(status='draft').count(),
        'pending': qs.filter(status='pending').count(),
        'approved': qs.filter(status='approved').count(),
        'rejected': qs.filter(status='rejected').count(),
    }
    context = {
        'total_products': total_products,
        'total_quantity_in': total_quantity_in,
        'total_quantity_out': total_quantity_out,
        'approval_counts': status_counts,
    }
    response = render(request, 'expense/dashboard.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('expense.view_expense', raise_exception=True)
@never_cache
def dashboard_stats_json(request):
    """JSON endpoint for dashboard card stats. No-cache so modals always get fresh counts."""
    company = get_company_profile_for_user(request.user, request)
    currency_symbol = getattr(company, 'currency_symbol', '₦') if company else '₦'
    currency_code = getattr(company, 'currency_code', 'NGN') if company else 'NGN'
    qs = _expense_queryset(request)
    agg = qs.aggregate(
        total_in=Sum('quantity_purchased'),
        total_out=Sum('quantity_out'),
        total_balance=Sum('total_amount'),
    )
    total_balance = agg.get('total_balance')
    if total_balance is None:
        total_balance = 0
    resp = JsonResponse({
        'total_products': qs.count(),
        'total_quantity_in': int(agg.get('total_in') or 0),
        'total_quantity_out': int(agg.get('total_out') or 0),
        'total_balance': float(total_balance),
        'currency_symbol': currency_symbol,
        'currency_code': currency_code,
        'approval_counts': {
            'draft': qs.filter(status='draft').count(),
            'pending': qs.filter(status='pending').count(),
            'approved': qs.filter(status='approved').count(),
            'rejected': qs.filter(status='rejected').count(),
        },
    })
    apply_no_cache_headers(resp)
    return resp


@login_required
@company_admin_or_permission_required('expense.view_expense', raise_exception=True)
def expense_list(request):
    """List with search, filter, pagination. Card stats from full dataset; table from filtered."""
    company = get_company_profile_for_user(request.user, request)
    base_qs = _expense_queryset(request).order_by('-expense_date', 'sn')
    card_agg = base_qs.aggregate(
        total_in=Sum('quantity_purchased'),
        total_out=Sum('quantity_out'),
        total_balance=Sum('total_amount'),
    )
    approval_counts = {
        'draft': base_qs.filter(status='draft').count(),
        'pending': base_qs.filter(status='pending').count(),
        'approved': base_qs.filter(status='approved').count(),
        'rejected': base_qs.filter(status='rejected').count(),
    }
    qs = base_qs
    search = (request.GET.get('search') or '').strip()
    status_filter = request.GET.get('status', '').strip() or request.GET.get('approval_status', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    if search:
        # Multi-word: each word must appear in at least one field (AND of terms).
        # Single letter/word: matches any field containing that text (icontains).
        terms = [t.strip() for t in search.split() if t.strip()]
        if not terms:
            terms = [search]
        for term in terms:
            q_term = (
                Q(product_name__icontains=term) |
                Q(vendor__icontains=term) |
                Q(transaction_id__icontains=term) |
                Q(expense_category__icontains=term) |
                Q(department__icontains=term) |
                Q(po_number__icontains=term) |
                Q(description__icontains=term) |
                Q(product_category__icontains=term) |
                Q(product_description__icontains=term) |
                Q(product_id__icontains=term) |
                Q(unit_of_measurement__icontains=term)
            )
            try:
                sn_val = int(term)
                q_term = q_term | Q(sn=sn_val)
            except (ValueError, TypeError):
                pass
            qs = qs.filter(q_term)
    if status_filter:
        qs = qs.filter(status=status_filter)
    if date_from:
        qs = qs.filter(expense_date__gte=date_from)
    if date_to:
        qs = qs.filter(expense_date__lte=date_to)
    paginator = Paginator(qs, 5)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    get_copy = request.GET.copy()
    if 'page' in get_copy:
        get_copy.pop('page', None)
    pagination_base_query = get_copy.urlencode()
    agg = qs.aggregate(
        total_in=Sum('quantity_purchased'),
        total_out=Sum('quantity_out'),
    )
    currency_symbol = getattr(company, 'currency_symbol', '₦') if company else '₦'
    currency_code = getattr(company, 'currency_code', 'NGN') if company else 'NGN'
    context = {
        'page_obj': page_obj,
        'pagination_base_query': pagination_base_query,
        'object_list': page_obj.object_list,
        'total_products': base_qs.count(),
        'total_quantity_in': card_agg.get('total_in') or 0,
        'total_quantity_out': card_agg.get('total_out') or 0,
        'total_balance': card_agg.get('total_balance') or 0,
        'approval_counts': approval_counts,
        'search': search,
        'status_filter': status_filter,
        'date_from': date_from,
        'date_to': date_to,
        'status_choices': Expense.STATUS_CHOICES,
        'user_currency_symbol': currency_symbol,
        'user_currency_code': currency_code,
    }
    if request.headers.get('X-Pagination-Ajax') == '1':
        rows_html = render_to_string(
            'expense/expense_list_rows_partial.html',
            context,
            request=request,
        )
        pagination_html = render_to_string(
            'expense/expense_list_pagination_partial.html',
            context,
            request=request,
        )
        return JsonResponse({'rows_html': rows_html, 'pagination_html': pagination_html})
    response = render(request, 'expense/expense_list.html', context)
    response['Cache-Control'] = 'private, max-age=60'
    return response


@login_required
@company_admin_or_permission_required('expense.add_expense', raise_exception=True)
@never_cache
def expense_create(request):
    if request.method == 'POST':
        company = get_company_profile_for_user(request.user, request)
        if not company:
            messages.error(request, 'Company profile is required to create expense.')
            resp = redirect('expense:list')
            apply_no_cache_headers(resp)
            return resp
        from .forms import ExpenseForm
        form = ExpenseForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.created_by = request.user
            obj.save()
            _clear_expense_list_cache(request)
            messages.success(request, 'Expense record created.')
            resp = redirect('expense:list')
            apply_no_cache_headers(resp)
            return resp
    else:
        from .forms import ExpenseForm
        form = ExpenseForm(user=request.user)
    response = render(request, 'expense/expense_form.html', {'form': form, 'is_edit': False})
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('expense.change_expense', raise_exception=True)
@never_cache
def expense_update(request, pk):
    qs = _expense_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    if request.method == 'POST':
        from .forms import ExpenseForm
        form = ExpenseForm(request.POST, request.FILES, instance=obj, user=request.user)
        if form.is_valid():
            form.save()
            _clear_expense_list_cache(request)
            messages.success(request, 'Expense updated.')
            resp = redirect('expense:list')
            apply_no_cache_headers(resp)
            return resp
    else:
        from .forms import ExpenseForm
        form = ExpenseForm(instance=obj, user=request.user)
    response = render(request, 'expense/expense_form.html', {'form': form, 'object': obj, 'is_edit': True})
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('expense.delete_expense', raise_exception=True)
@require_POST
def expense_delete(request, pk):
    qs = _expense_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    company_id = obj.company_id
    obj.delete()
    Expense.renumber_sn_for_company(company_id)
    _clear_expense_list_cache(request)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    messages.success(request, 'Expense record deleted.')
    resp = redirect('expense:list')
    apply_no_cache_headers(resp)
    return resp


@login_required
@company_admin_or_permission_required('expense.view_expense', raise_exception=True)
@never_cache
def expense_detail(request, pk):
    qs = _expense_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    context = _expense_document_context(request, obj)
    response = render(request, 'expense/expense_detail.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('expense.print_expense', raise_exception=True)
@never_cache
def expense_print(request, pk):
    qs = _expense_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    context = _expense_document_context(request, obj)
    response = render(request, 'expense/expense_print.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('expense.download_expense', raise_exception=True)
@never_cache
def expense_pdf(request, pk):
    qs = _expense_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    try:
        from django.template.loader import get_template
        from xhtml2pdf import pisa
        context = _expense_document_context(request, obj)
        if context.get('company_logo'):
            context['company_logo'] = request.build_absolute_uri(context['company_logo'])
        template = get_template('expense/expense_print.html')
        html_str = template.render(context, request)
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="expense-{obj.transaction_id}.pdf"'
        pisa_status = pisa.CreatePDF(html_str, dest=response)
        if pisa_status.err:
            resp = redirect('expense:print', pk=pk)
            apply_no_cache_headers(resp)
            return resp
        apply_no_cache_headers(response)
        return response
    except ImportError:
        resp = redirect('expense:print', pk=pk)
        apply_no_cache_headers(resp)
        return resp


@login_required
@company_admin_or_permission_required('expense.print_expense', raise_exception=True)
@never_cache
def expense_list_print(request):
    """Print full expense table with optional date range."""
    qs = _expense_queryset(request).order_by('-expense_date', 'sn')
    filter_kwargs, date_label = _parse_expense_list_date_range(request)
    if filter_kwargs:
        qs = qs.filter(**filter_kwargs)
    object_list = list(qs)
    context = _expense_list_document_context(request, object_list, date_label)
    context['status_choices'] = Expense.STATUS_CHOICES
    response = render(request, 'expense/expense_list_print.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('expense.download_expense', raise_exception=True)
@never_cache
def expense_list_pdf(request):
    """Download full expense table as PDF with optional date range."""
    qs = _expense_queryset(request).order_by('-expense_date', 'sn')
    filter_kwargs, date_label = _parse_expense_list_date_range(request)
    if filter_kwargs:
        qs = qs.filter(**filter_kwargs)
    object_list = list(qs)
    try:
        from django.template.loader import get_template
        from xhtml2pdf import pisa
        context = _expense_list_document_context(request, object_list, date_label)
        context['status_choices'] = Expense.STATUS_CHOICES
        if context.get('company_logo'):
            context['company_logo'] = request.build_absolute_uri(context['company_logo'])
        template = get_template('expense/expense_list_print.html')
        html_str = template.render(context, request)
        filename = f"expense-list-{timezone.now().strftime('%Y%m%d-%H%M')}.pdf"
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        pisa_status = pisa.CreatePDF(html_str, dest=response)
        if pisa_status.err:
            from django.urls import reverse
            url = reverse('expense:list_print') + ('?' + request.GET.urlencode() if request.GET else '')
            return redirect(url)
        apply_no_cache_headers(response)
        return response
    except ImportError:
        from django.urls import reverse
        url = reverse('expense:list_print') + ('?' + request.GET.urlencode() if request.GET else '')
        return redirect(url)


@login_required
@company_admin_or_permission_required('expense.add_expense', raise_exception=True)
@require_POST
def ajax_create(request):
    """Create one expense record from POST (table Add row). Returns JSON for row insert."""
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return JsonResponse({'success': False, 'message': 'Company profile is required.'}, status=400)
    from .forms import ExpenseForm
    data = {
        'expense_date': request.POST.get('expense_date') or '',
        'expense_category': (request.POST.get('expense_category') or '').strip() or '',
        'department': (request.POST.get('department') or '').strip() or '',
        'vendor': (request.POST.get('vendor') or '').strip() or '',
        'po_number': (request.POST.get('po_number') or '').strip() or '',
        'description': (request.POST.get('description') or '').strip() or '',
        'product_id': (request.POST.get('product_id') or '').strip() or '',
        'product_name': (request.POST.get('product_name') or '').strip() or None,
        'product_category': (request.POST.get('product_category') or '').strip() or '',
        'product_description': (request.POST.get('product_description') or '').strip() or '',
        'unit_of_measurement': (request.POST.get('unit_of_measurement') or '').strip() or '',
        'quantity_purchased': request.POST.get('quantity_purchased', '0'),
        'quantity_out': request.POST.get('quantity_out', '0'),
        'unit_price': request.POST.get('unit_price', '0'),
        'quantity_threshold': request.POST.get('quantity_threshold', '0'),
        'subtotal': request.POST.get('subtotal', ''),
        'tax': request.POST.get('tax', '0'),
        'discount': request.POST.get('discount', '0'),
        'payment_method': (request.POST.get('payment_method') or '').strip() or 'cash',
        'payment_date': request.POST.get('payment_date') or '',
        'status': (request.POST.get('status') or '').strip() or 'draft',
    }
    if not data['product_name']:
        return JsonResponse({'success': False, 'message': 'Product name is required.'}, status=400)
    form = ExpenseForm(data, request.FILES, user=request.user)
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
    _clear_expense_list_cache(request)
    created_by_display = (obj.created_by.get_full_name() or obj.created_by.email or '—') if obj.created_by else '—'
    approved_by_display = (obj.approved_by.get_full_name() or obj.approved_by.email or '—') if obj.approved_by else '—'
    resp = JsonResponse({
        'success': True,
        'id': obj.pk,
        'uuid': str(obj.uuid) if getattr(obj, 'uuid', None) else '',
        'sn': obj.sn,
        'transaction_id': obj.transaction_id,
        'expense_date': obj.expense_date.strftime('%Y-%m-%d') if obj.expense_date else '',
        'expense_category': obj.expense_category or '',
        'department': obj.department or '',
        'vendor': obj.vendor or '',
        'po_number': obj.po_number or '',
        'description': (obj.description or '')[:80],
        'product_id': obj.product_id or '',
        'product_name': obj.product_name or '',
        'product_category': obj.product_category or '',
        'product_description': (obj.product_description or '')[:80],
        'unit_of_measurement': obj.unit_of_measurement or '',
        'quantity_purchased': str(obj.quantity_purchased),
        'quantity_out': str(obj.quantity_out),
        'remaining_quantity': str(obj.remaining_quantity),
        'unit_price': str(obj.unit_price),
        'total_purchase_value': str(obj.total_purchase_value),
        'stock_value_remaining': str(obj.stock_value_remaining),
        'quantity_threshold': str(obj.quantity_threshold),
        'low_stock_alert': obj.low_stock_alert,
        'subtotal': str(obj.subtotal),
        'tax': str(obj.tax),
        'discount': str(obj.discount),
        'total_amount': str(obj.total_amount),
        'payment_method': obj.payment_method or '',
        'payment_date': obj.payment_date.strftime('%Y-%m-%d') if obj.payment_date else '',
        'receipt_url': obj.receipt_upload.url if obj.receipt_upload else '',
        'status': obj.status,
        'status_display': obj.get_status_display(),
        'approved_by_display': approved_by_display,
        'created_by_display': created_by_display,
        'created_at': obj.created_at.strftime('%Y-%m-%d %I:%M:%S %p'),
        'updated_at': obj.updated_at.strftime('%Y-%m-%d %I:%M:%S %p') if obj.updated_at else '',
    })
    resp['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    return resp


@login_required
@company_admin_or_permission_required('expense.change_expense', raise_exception=True)
@require_POST
def ajax_update_field(request):
    """Update a single field; recalc on backend; return JSON."""
    pk = request.POST.get('id') or request.POST.get('pk')
    field = (request.POST.get('field') or '').strip()
    value = request.POST.get('value', '')
    if not pk or not field:
        return JsonResponse({'success': False, 'message': 'Missing id or field'}, status=400)
    qs = _expense_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    editable = {
        'expense_date', 'expense_category', 'department', 'vendor', 'po_number', 'description',
        'product_id', 'product_name', 'product_category', 'product_description', 'unit_of_measurement',
        'quantity_purchased', 'quantity_out', 'unit_price', 'quantity_threshold',
        'subtotal', 'tax', 'discount', 'payment_method', 'payment_date', 'status',
    }
    if field not in editable:
        return JsonResponse({'success': False, 'message': 'Field not editable'}, status=400)
    decimal_fields = ('quantity_purchased', 'quantity_out', 'unit_price', 'quantity_threshold', 'subtotal', 'tax', 'discount')
    if field in decimal_fields:
        try:
            from decimal import Decimal
            value = Decimal(str(value).replace(',', ''))
        except Exception:
            value = getattr(obj, field, 0)
    if field == 'expense_date' or field == 'payment_date':
        if value:
            try:
                from datetime import datetime
                if isinstance(value, str):
                    value = datetime.strptime(value[:10], '%Y-%m-%d').date()
            except (ValueError, TypeError):
                value = getattr(obj, field, None)
        else:
            value = None
    if field == 'status':
        # Only company admin or users with explicit approval permission may
        # change the approval/status field via this generic field updater.
        if not (is_company_admin(request.user, request) or request.user.has_perm('expense.can_approve_expense')):
            return JsonResponse(
                {'success': False, 'message': 'You do not have permission to approve expense records.'},
                status=403,
            )
        if value not in dict(Expense.STATUS_CHOICES):
            value = obj.status
        if value == 'approved':
            obj.approved_by = request.user
            obj.approved_at = timezone.now()
        else:
            obj.approved_by = None
            obj.approved_at = None
    setattr(obj, field, value)
    obj.save()
    _clear_expense_list_cache(request)
    resp_data = {
        'success': True,
        'remaining_quantity': str(obj.remaining_quantity),
        'total_purchase_value': str(obj.total_purchase_value),
        'stock_value_remaining': str(obj.stock_value_remaining),
        'low_stock_alert': obj.low_stock_alert,
        'total_amount': str(obj.total_amount),
        'unit_price': str(obj.unit_price),
        'quantity_purchased': str(obj.quantity_purchased),
        'quantity_out': str(obj.quantity_out),
        'quantity_threshold': str(obj.quantity_threshold),
        'subtotal': str(obj.subtotal),
        'tax': str(obj.tax),
        'discount': str(obj.discount),
    }
    if field == 'status':
        resp_data['status'] = obj.status
        resp_data['status_display'] = obj.get_status_display()
        resp_data['approved_by_display'] = (obj.approved_by.get_full_name() or obj.approved_by.email or '—') if obj.approved_by else '—'
    if field in ('expense_date', 'payment_date'):
        d = getattr(obj, field, None)
        resp_data[field] = d.strftime('%Y-%m-%d') if d else ''
    resp = JsonResponse(resp_data)
    apply_no_cache_headers(resp)
    return resp


@login_required
@company_admin_or_permission_required('expense.can_approve_expense', raise_exception=True)
@require_POST
def ajax_status_update(request):
    """Update status; set approved_by/approved_at when status is approved. Return JSON."""
    raw_pk = request.POST.get('id') or request.POST.get('pk')
    if not raw_pk:
        return JsonResponse({'success': False, 'message': 'Missing id'}, status=400)
    try:
        pk = int(raw_pk)
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'message': 'Invalid id'}, status=400)
    status_val = (request.POST.get('status') or request.POST.get('approval_status') or '').strip()
    if not status_val or status_val not in dict(Expense.STATUS_CHOICES):
        return JsonResponse({'success': False, 'message': 'Invalid status'}, status=400)
    qs = _expense_queryset(request)
    obj = get_object_or_404(qs, pk=pk)
    obj.status = status_val
    if status_val == 'approved':
        obj.approved_by = request.user
        obj.approved_at = timezone.now()
    else:
        obj.approved_by = None
        obj.approved_at = None
    obj.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
    _clear_expense_list_cache(request)
    approved_by_display = (obj.approved_by.get_full_name() or obj.approved_by.email or '—') if obj.approved_by else '—'
    resp = JsonResponse({
        'success': True,
        'status': obj.status,
        'status_display': obj.get_status_display(),
        'approved_by_display': approved_by_display,
    })
    resp['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    return resp
