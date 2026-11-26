# -*- coding: utf-8 -*-
from django.shortcuts import render, get_object_or_404, redirect
from business_app.views import get_object_or_unauthorized
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from apps.core.permissions import company_admin_or_permission_required
from django.db import transaction
from django.db.models import Q, F, Sum, Count, Case, When, Value
from django.db.models.functions import Least
from django.db.models.fields import DecimalField
from django.db.utils import OperationalError
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse, Http404
from django.views.decorators.cache import never_cache
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta
from .models import Invoice, InvoiceItem, InvoiceTemplate, safe_decimal_for_db
from apps.waybills.models import Waybill
from .forms import InvoiceForm, InvoiceItemFormSet, InvoiceFilterForm, InvoiceTemplateForm
# from apps.core.utils import generate_pdf_response
import openpyxl
from django.template.loader import render_to_string
from xhtml2pdf import pisa
from django.template.loader import render_to_string
from django.http import HttpResponse
from apps.core.models import CompanyProfile
from apps.core.utils import get_company_profile_for_user, get_account_users_for_filter, get_revenue_period_boundaries, apply_no_cache_headers
from apps.core.ownership import for_user_queryset, get_account_for_user
import os
import urllib.parse
import base64
import sys
import logging
import re
import time
from collections import defaultdict

logger = logging.getLogger(__name__)

_INVOICE_DB_BUSY_MSG = (
    'The database was busy for a moment. Wait a second, then click Save once. '
    'This is temporary — invoices still work.'
)


def _is_db_lock_error(exc):
    if not isinstance(exc, OperationalError):
        return False
    msg = str(exc).lower()
    return 'locked' in msg or 'busy' in msg


def _retry_on_db_lock(operation, attempts=5):
    last = None
    for i in range(attempts):
        try:
            return operation()
        except OperationalError as exc:
            last = exc
            if not _is_db_lock_error(exc):
                raise
            time.sleep(0.2 * (2 ** i))
    raise last


def _replace_invoice_line_items(invoice, new_items):
    qs = InvoiceItem.objects.filter(invoice_id=invoice.pk)
    qs._raw_delete(qs.db)
    for item in new_items:
        item.pk = None
        item.invoice = invoice
    if new_items:
        InvoiceItem.objects.bulk_create(new_items)


def get_filtered_invoices(request):
    # Per-team-member isolation: admin sees all company invoices, team members see only their own
    invoices = for_user_queryset(Invoice, request.user, request, account_lookup='account').select_related('user', 'template', 'created_by')
    filter_form = InvoiceFilterForm(request.GET)
    from apps.accounts.rbac import is_company_admin as _is_company_admin
    if _is_company_admin(request):
        filter_form.fields['created_by'].queryset = get_account_users_for_filter(request.user)
    if filter_form.is_valid():
        search = filter_form.cleaned_data.get('search')
        status = filter_form.cleaned_data.get('status')
        date_from = filter_form.cleaned_data.get('date_from')
        date_to = filter_form.cleaned_data.get('date_to')
        if search:
            invoices = invoices.filter(
                Q(invoice_number__icontains=search) |
                Q(client_name__icontains=search) |
                Q(client_email__icontains=search) |
                Q(client_phone__icontains=search) |
                Q(notes__icontains=search)
            )
        if status:
            invoices = invoices.filter(status=status)
        if date_from:
            invoices = invoices.filter(invoice_date__gte=date_from)
        if date_to:
            invoices = invoices.filter(invoice_date__lte=date_to)
        # Admin-only: filter by creator (do not apply for team members)
        if _is_company_admin(request) and filter_form.cleaned_data.get('created_by'):
            invoices = invoices.filter(created_by=filter_form.cleaned_data['created_by'])
    return invoices


def _normalize_customer_name(value):
    return (value or '').strip().lower()


def _normalize_customer_email(value):
    return (value or '').strip().lower()


def _normalize_customer_phone(value):
    phone = re.sub(r'[^0-9+]', '', (value or '').strip())
    if phone.startswith('00'):
        phone = '+' + phone[2:]
    if phone.startswith('234') and not phone.startswith('+'):
        phone = '+' + phone
    if phone.startswith('0') and len(phone) >= 10:
        phone = '+234' + phone[1:]
    return phone


def _extract_waybill_customer_contact(waybill):
    custom_data = getattr(waybill, 'custom_data', {}) or {}
    receiver_info = custom_data.get('receiver_info') or {}
    custom_receiver_info = custom_data.get('custom_receiver_info') or {}
    name = (
        receiver_info.get('receiver_name')
        or custom_receiver_info.get('receiver_name')
        or custom_data.get('receiver_name')
        or ''
    ).strip()
    phone = (
        receiver_info.get('receiver_phone')
        or custom_receiver_info.get('receiver_phone')
        or custom_data.get('receiver_phone')
        or ''
    ).strip()
    email = (
        receiver_info.get('receiver_email')
        or custom_receiver_info.get('receiver_email')
        or custom_data.get('receiver_email')
        or ''
    ).strip()
    return {'name': name, 'phone': phone, 'email': email}


def _resolve_customer_bucket_key(name, email, phone, email_to_key, phone_to_key, name_to_key):
    normalized_email = _normalize_customer_email(email)
    normalized_phone = _normalize_customer_phone(phone)
    normalized_name = _normalize_customer_name(name)
    if normalized_email and normalized_email in email_to_key:
        return email_to_key[normalized_email]
    if normalized_phone and normalized_phone in phone_to_key:
        return phone_to_key[normalized_phone]
    if normalized_name and normalized_name in name_to_key:
        return name_to_key[normalized_name]
    return None


def _parse_decimal_quantity(value):
    if value is None:
        return Decimal('0')
    text = str(value).strip()
    if not text:
        return Decimal('0')
    match = re.search(r'-?\d+(?:\.\d+)?', text.replace(',', ''))
    if not match:
        return Decimal('0')
    try:
        return Decimal(match.group(0))
    except Exception:
        return Decimal('0')


def _extract_waybill_item_product(item_data):
    if not isinstance(item_data, dict):
        return ''
    for key in ('product', 'product_service', 'item_description', 'description', 'item'):
        val = (item_data.get(key) or '').strip()
        if val:
            return val
    return ''


def _extract_waybill_item_total_qty(item_data):
    if not isinstance(item_data, dict):
        return Decimal('0')
    for key in ('quantity', 'qty', 'total_quantity', 'total_qty', 'ordered_quantity'):
        qty = _parse_decimal_quantity(item_data.get(key))
        if qty:
            return qty
    return Decimal('0')


def _build_customer_sync_metrics(request, invoices_on_page):
    """
    Build customer-level invoice + waybill metrics shown on invoice list rows.
    Metrics are account-scoped (all visible records), then mapped to the customers
    present on the current page for fast rendering.
    """
    page_aliases = set()
    for inv in invoices_on_page:
        if _normalize_customer_name(inv.client_name):
            page_aliases.add(('name', _normalize_customer_name(inv.client_name)))
        if _normalize_customer_email(inv.client_email):
            page_aliases.add(('email', _normalize_customer_email(inv.client_email)))
        if _normalize_customer_phone(inv.client_phone):
            page_aliases.add(('phone', _normalize_customer_phone(inv.client_phone)))
    if not page_aliases:
        return {}

    base_invoice_qs = for_user_queryset(Invoice, request.user, request, account_lookup='account')
    buckets = {}
    email_to_key = {}
    phone_to_key = {}
    name_to_key = {}
    for inv in base_invoice_qs.only('client_name', 'client_email', 'client_phone', 'grand_total', 'amount_paid', 'balance_due'):
        bucket_key = _resolve_customer_bucket_key(
            inv.client_name, inv.client_email, inv.client_phone, email_to_key, phone_to_key, name_to_key
        )
        if not bucket_key:
            bucket_key = f"customer-{len(buckets) + 1}"
            buckets[bucket_key] = {
                'customer_name': (inv.client_name or '').strip() or 'Unknown Customer',
                'total_supplies': 0,
                'total_supplied_value': Decimal('0'),
                'total_paid_value': Decimal('0'),
                'total_amount_remaining': Decimal('0'),
                'waybill_count': 0,
                'total_goods_supplied': Decimal('0'),
                'total_goods_delivered': Decimal('0'),
                'total_goods_owed': Decimal('0'),
                'jobs_completed': 0,
                'jobs_pending': 0,
                'total_jobs_owed': 0,
                'delivery_count': 0,
                'total_delivery': Decimal('0'),
                'outstanding_delivery': 0,
                'total_outstandings': Decimal('0'),
            }
        metrics = buckets[bucket_key]
        metrics['total_supplies'] += 1
        metrics['total_supplied_value'] += Decimal(str(getattr(inv, 'grand_total', 0) or 0))
        metrics['total_paid_value'] += Decimal(str(getattr(inv, 'amount_paid', 0) or 0))
        remaining_amount = Decimal(str(getattr(inv, 'balance_due', 0) or 0))
        if remaining_amount > 0:
            metrics['total_amount_remaining'] += remaining_amount

        normalized_email = _normalize_customer_email(inv.client_email)
        normalized_phone = _normalize_customer_phone(inv.client_phone)
        normalized_name = _normalize_customer_name(inv.client_name)
        if normalized_email:
            email_to_key[normalized_email] = bucket_key
        if normalized_phone:
            phone_to_key[normalized_phone] = bucket_key
        if normalized_name:
            name_to_key[normalized_name] = bucket_key

    page_bucket_keys = set()
    for alias_type, alias_value in page_aliases:
        if alias_type == 'email' and alias_value in email_to_key:
            page_bucket_keys.add(email_to_key[alias_value])
        elif alias_type == 'phone' and alias_value in phone_to_key:
            page_bucket_keys.add(phone_to_key[alias_value])
        elif alias_type == 'name' and alias_value in name_to_key:
            page_bucket_keys.add(name_to_key[alias_value])

    if not page_bucket_keys:
        return {
            'buckets': {},
            'email_to_key': email_to_key,
            'phone_to_key': phone_to_key,
            'name_to_key': name_to_key,
        }

    waybills = for_user_queryset(Waybill, request.user, request, account_lookup='account').only(
        'custom_data',
        'status',
        'total_quantity_value',
        'delivered_quantity_value',
        'remaining_quantity_value',
    )
    for wb in waybills:
        customer_contact = _extract_waybill_customer_contact(wb)
        bucket_key = _resolve_customer_bucket_key(
            customer_contact.get('name'),
            customer_contact.get('email'),
            customer_contact.get('phone'),
            email_to_key,
            phone_to_key,
            name_to_key,
        )
        if bucket_key not in page_bucket_keys:
            continue

        total_qty = Decimal(str(getattr(wb, 'total_quantity_value', 0) or 0))
        delivered_qty = Decimal(str(getattr(wb, 'delivered_quantity_value', 0) or 0))
        remaining_qty = Decimal(str(getattr(wb, 'remaining_quantity_value', 0) or 0))
        if remaining_qty < 0:
            remaining_qty = Decimal('0')

        item = buckets[bucket_key]
        item['waybill_count'] += 1
        item['total_goods_supplied'] += total_qty
        item['total_goods_delivered'] += delivered_qty
        item['total_goods_owed'] += remaining_qty
        if remaining_qty > 0:
            item['jobs_pending'] += 1
        else:
            item['jobs_completed'] += 1
        item['total_jobs_owed'] = item['jobs_pending']
        item['delivery_count'] = item['waybill_count']
        item['total_delivery'] = item['total_goods_delivered']
        item['outstanding_delivery'] = item['jobs_pending']
        item['total_outstandings'] = item['total_goods_owed']

    filtered_metrics = {k: buckets[k] for k in page_bucket_keys if k in buckets}
    return {
        'buckets': filtered_metrics,
        'email_to_key': email_to_key,
        'phone_to_key': phone_to_key,
        'name_to_key': name_to_key,
    }


def _build_customer_item_breakdown(request, page_bucket_keys, email_to_key, phone_to_key, name_to_key):
    """
    Build per-customer item-level supply summary:
    - item name
    - unit worth (average unit price)
    - total quantity supplied
    - total value supplied per item
    - total supplies amount and supply line count
    """
    if not page_bucket_keys:
        return {}

    invoice_qs = for_user_queryset(Invoice, request.user, request, account_lookup='account')
    item_qs = InvoiceItem.objects.select_related('invoice').filter(invoice__in=invoice_qs).only(
        'product_service',
        'description',
        'quantity',
        'unit_price',
        'line_total',
        'invoice__client_name',
        'invoice__client_email',
        'invoice__client_phone',
    )

    buckets = {}
    for item in item_qs:
        inv = item.invoice
        bucket_key = _resolve_customer_bucket_key(
            inv.client_name,
            inv.client_email,
            inv.client_phone,
            email_to_key,
            phone_to_key,
            name_to_key,
        )
        if bucket_key not in page_bucket_keys:
            continue

        bucket = buckets.setdefault(bucket_key, {
            'item_map': {},
            'total_item_supplies_amount': Decimal('0'),
            'total_item_supply_lines': 0,
        })
        item_name = (item.product_service or item.description or 'Unnamed item').strip()
        item_key = _normalize_customer_name(item_name)
        qty = Decimal(str(item.quantity or 0))
        unit_price = Decimal(str(item.unit_price or 0))
        value = Decimal(str(item.line_total or 0))
        if value == 0 and qty and unit_price:
            value = qty * unit_price

        row = bucket['item_map'].setdefault(item_key, {
            'item_name': item_name,
            'total_qty': Decimal('0'),
            'total_value': Decimal('0'),
            'supply_count': 0,
            'unit_price_total': Decimal('0'),
        })
        row['total_qty'] += qty
        row['total_value'] += value
        row['supply_count'] += 1
        row['unit_price_total'] += unit_price

        bucket['total_item_supplies_amount'] += value
        bucket['total_item_supply_lines'] += 1

    result = {}
    for bucket_key, bucket in buckets.items():
        rows = []
        for row in bucket['item_map'].values():
            count = row['supply_count'] or 1
            avg_price = row['unit_price_total'] / Decimal(str(count))
            rows.append({
                'item_name': row['item_name'],
                'total_qty': row['total_qty'],
                'total_value': row['total_value'],
                'supply_count': row['supply_count'],
                'unit_worth': avg_price,
            })
        rows.sort(key=lambda r: r['total_value'], reverse=True)
        result[bucket_key] = {
            'item_rows': rows,
            'total_item_supplies_amount': bucket['total_item_supplies_amount'],
            'total_item_supply_lines': bucket['total_item_supply_lines'],
            'distinct_item_count': len(rows),
            'extra_item_count': max(len(rows) - 8, 0),
        }
    return result

@login_required
@permission_required('invoices.view_invoice', raise_exception=True)
@never_cache
def invoice_list(request):
    """List all invoices. Never cached so deletes/creates show immediately."""
    from apps.accounts.rbac import is_company_admin as _is_company_admin
    from apps.accounts.services import _clear_user_permission_cache
    from apps.accounts.models import SubUser

    # Clear permission cache for team members so has_perm() reflects latest role (fixes
    # Create/Export/Edit buttons not showing after role assignment without re-login)
    if SubUser.objects.filter(linked_user=request.user).exists():
        _clear_user_permission_cache(request.user)

    is_company_admin = _is_company_admin(request)
    from apps.core.mixins import is_read_only_user
    can_see_creator = is_company_admin or is_read_only_user(request.user)
    invoices = get_filtered_invoices(request)
    filter_form = InvoiceFilterForm(request.GET)
    paginator = Paginator(invoices, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    customer_sync_state = _build_customer_sync_metrics(request, page_obj.object_list)
    customer_sync_metrics = customer_sync_state.get('buckets', {})
    email_to_key = customer_sync_state.get('email_to_key', {})
    phone_to_key = customer_sync_state.get('phone_to_key', {})
    name_to_key = customer_sync_state.get('name_to_key', {})
    customer_item_breakdown = _build_customer_item_breakdown(
        request,
        set(customer_sync_metrics.keys()),
        email_to_key,
        phone_to_key,
        name_to_key,
    )
    for inv in page_obj.object_list:
        bucket_key = _resolve_customer_bucket_key(
            inv.client_name,
            inv.client_email,
            inv.client_phone,
            email_to_key,
            phone_to_key,
            name_to_key,
        )
        inv.customer_sync = customer_sync_metrics.get(bucket_key, {
            'total_supplies': 0,
            'total_supplied_value': Decimal('0'),
            'total_paid_value': Decimal('0'),
            'total_amount_remaining': Decimal('0'),
            'waybill_count': 0,
            'total_goods_supplied': Decimal('0'),
            'total_goods_delivered': Decimal('0'),
            'total_goods_owed': Decimal('0'),
            'jobs_completed': 0,
            'jobs_pending': 0,
            'total_jobs_owed': 0,
            'delivery_count': 0,
            'total_delivery': Decimal('0'),
            'outstanding_delivery': 0,
            'total_outstandings': Decimal('0'),
        })
        inv.customer_items = customer_item_breakdown.get(bucket_key, {
            'item_rows': [],
            'total_item_supplies_amount': Decimal('0'),
            'total_item_supply_lines': 0,
            'distinct_item_count': 0,
            'extra_item_count': 0,
        })
    # One query for all filtered metrics (totals, outstanding, refund_due, revenue).
    # Formulas: Total=Sum(grand_total), Paid=Sum(amount_paid), Revenue=Sum(min(amount_paid,grand_total)),
    # Outstanding=Sum(balance_due) where balance_due>0, Refund=Sum(amount_paid-grand_total) where amount_paid>grand_total.
    # Null invoice_date: excluded from period cards only; included in first-row counts/sums.
    invoices_agg = get_filtered_invoices(request).annotate(
        rev_cap=Least(F('amount_paid'), F('grand_total'))
    )
    agg = invoices_agg.aggregate(
        total_count=Count('id'),
        total_amount=Sum('grand_total'),
        paid_amount=Sum('amount_paid'),
        outstanding=Sum(Case(When(balance_due__gt=0, then=F('balance_due')), default=Value(Decimal('0')), output_field=DecimalField())),
        refund_due=Sum(Case(When(amount_paid__gt=F('grand_total'), then=F('amount_paid') - F('grand_total')), default=Value(Decimal('0')), output_field=DecimalField())),
        revenue_generated=Sum('rev_cap'),
    )
    total_invoices = agg.get('total_count') or 0
    total_amount_val = agg.get('total_amount')
    paid_amount_val = agg.get('paid_amount')
    outstanding_amount = agg.get('outstanding') or 0
    refund_due = agg.get('refund_due') or 0
    revenue_generated = agg.get('revenue_generated') or 0
    if total_amount_val is None:
        total_amount_val = 0
    if paid_amount_val is None:
        paid_amount_val = 0
    # Metrics (computed above) are consistent with unpaid / partial / paid:
    # - Unpaid (pending) invoices: amount_paid=0 → revenue=0, outstanding=grand_total. They do not inflate revenue.
    # - Part payment: only amount_paid counts as revenue; outstanding = balance still owed (grand_total - amount_paid).
    # - Revenue = min(amount_paid, grand_total) per invoice so overpayments do not inflate revenue.
    # Outstanding = what customers still owe us (positive balance_due only). Overpayments excluded.
    # (outstanding_amount, refund_due, revenue_generated already in agg above)

    # One query for all period revenues (today, week, month, quarter, year)
    # Use Coalesce to fallback to created_at date when invoice_date is null
    from django.db.models.functions import Coalesce
    periods = get_revenue_period_boundaries()
    base_capped = for_user_queryset(Invoice, request.user, request, account_lookup='account').annotate(
        rev_cap=Least(F('amount_paid'), F('grand_total')),
        effective_date=Coalesce('invoice_date', 'created_at__date')
    )
    
    # Simpler approach - filter first, then sum
    rev_today = base_capped.filter(effective_date=periods['today']).aggregate(total=Sum('rev_cap'))['total'] or 0
    rev_week = base_capped.filter(effective_date__gte=periods['week_start'], effective_date__lte=periods['week_end']).aggregate(total=Sum('rev_cap'))['total'] or 0
    rev_month = base_capped.filter(effective_date__gte=periods['start_of_month'], effective_date__lte=periods['end_of_month']).aggregate(total=Sum('rev_cap'))['total'] or 0
    rev_quarter = base_capped.filter(effective_date__gte=periods['quarter_start'], effective_date__lte=periods['quarter_end']).aggregate(total=Sum('rev_cap'))['total'] or 0
    rev_year = base_capped.filter(effective_date__gte=periods['year_start'], effective_date__lte=periods['year_end']).aggregate(total=Sum('rev_cap'))['total'] or 0
    account = get_account_for_user(request.user)
    if account:
        current_template = InvoiceTemplate.objects.filter(user__account=account, is_default=True).first()
        if not current_template:
            current_template = InvoiceTemplate.objects.filter(user__account=account).first()
    else:
        current_template = InvoiceTemplate.objects.filter(user=request.user).first()
    if not current_template:
        current_template = InvoiceTemplate.objects.create(
            user=request.user,
            name="Default Invoice Template",
            description="Automatically created default template",
            is_default=True
        )
    company_profile = get_company_profile_for_user(request.user, request)
    currency_symbol = (company_profile.currency_symbol or "₦") if company_profile else "₦"
    currency_code = (company_profile.currency_code or "NGN") if company_profile else "NGN"

    account_users = get_account_users_for_filter(request.user) if is_company_admin else []
    if is_company_admin:
        filter_form.fields['created_by'].queryset = account_users

    # Explicit permission flags for Create/Export/Edit buttons - ensures team members with
    # invoice role permissions see the buttons (perms in templates can have cache issues)
    can_create_invoice = request.user.has_perm('invoices.add_invoice')
    can_export_invoice = is_company_admin or request.user.has_perm('invoices.download_invoice')
    can_change_invoice = is_company_admin or request.user.has_perm('invoices.change_invoice')
    can_print_invoice = is_company_admin or request.user.has_perm('invoices.print_invoice')
    can_delete_invoice = is_company_admin or request.user.has_perm('invoices.delete_invoice')
    # Approval (status/payment) actions: strictly require can_approve_invoice (or company admin)
    can_approve_invoice = is_company_admin or request.user.has_perm('invoices.can_approve_invoice')

    context = {
        'page_obj': page_obj,
        'filter_form': filter_form,
        'total_invoices': total_invoices,
        'total_amount': total_amount_val,
        'paid_amount': paid_amount_val,
        'revenue_generated': revenue_generated,
        'outstanding_amount': outstanding_amount,
        'revenue_today': rev_today,
        'revenue_week': rev_week,
        'revenue_month': rev_month,
        'revenue_quarter': rev_quarter,
        'revenue_year': rev_year,
        'refund_due': refund_due,
        'currency_symbol': currency_symbol,
        'company_profile': company_profile,
        'current_template': current_template,
        'account_users': account_users,
        'is_company_admin': is_company_admin,
        'show_created_by': can_see_creator,
        'can_create_invoice': can_create_invoice,
        'can_export_invoice': can_export_invoice,
        'can_change_invoice': can_change_invoice,
        'can_print_invoice': can_print_invoice,
        'can_delete_invoice': can_delete_invoice,
        'can_approve_invoice': can_approve_invoice,
        'customer_sync_metrics': customer_sync_metrics,
    }
    return render(request, 'invoices/invoice_list.html', context)


def _get_invoices_for_card_filter(request, filter_key):
    """
    Return a queryset of invoices filtered by the given card filter key.
    First-row cards (total_invoices, total_amount, paid_amount, revenue_generated,
    outstanding, refund_due) use the same filtered set as the list page so modal
    records and counts match the card. Period cards (revenue_today/week/month/quarter/year)
    use full account scope (no list filters) per product spec.
    """
    from apps.accounts.rbac import is_company_admin as _is_company_admin
    # First-row cards: use list filter so modal shows exactly the records the card is based on
    first_row = {'total_invoices', 'total_amount', 'paid_amount', 'revenue_generated', 'outstanding', 'refund_due'}
    if filter_key in first_row:
        base = get_filtered_invoices(request)
    else:
        base = for_user_queryset(Invoice, request.user, request, account_lookup='account')
    base = base.select_related('created_by').order_by('-created_at')

    if filter_key in ('total_invoices', 'total_amount'):
        return base

    if filter_key == 'paid_amount':
        return base.filter(amount_paid__gt=0)

    if filter_key == 'revenue_generated':
        # Invoices that contributed to revenue (min(amount_paid, grand_total) > 0)
        return base.filter(amount_paid__gt=0)

    if filter_key == 'outstanding':
        return base.filter(balance_due__gt=0)

    if filter_key == 'refund_due':
        return base.filter(amount_paid__gt=F('grand_total'))

    # Period cards: full account scope, same date boundaries as list view
    periods = get_revenue_period_boundaries()
    base_capped = base.annotate(rev_cap=Least(F('amount_paid'), F('grand_total'))).filter(rev_cap__gt=0)

    if filter_key == 'revenue_today':
        return base_capped.filter(invoice_date=periods['today'])
    if filter_key == 'revenue_week':
        return base_capped.filter(
            invoice_date__gte=periods['week_start'],
            invoice_date__lte=periods['week_end']
        )
    if filter_key == 'revenue_month':
        return base_capped.filter(
            invoice_date__gte=periods['start_of_month'],
            invoice_date__lte=periods['end_of_month']
        )
    if filter_key == 'revenue_quarter':
        return base_capped.filter(
            invoice_date__gte=periods['quarter_start'],
            invoice_date__lte=periods['quarter_end']
        )
    if filter_key == 'revenue_year':
        return base_capped.filter(
            invoice_date__gte=periods['year_start'],
            invoice_date__lte=periods['year_end']
        )

    return base.none()


@login_required
@permission_required('invoices.view_invoice', raise_exception=True)
@never_cache
def invoice_card_records_api(request):
    """
    JSON API: return invoices filtered by card type for the records modal.
    GET ?filter=outstanding|total_invoices|paid_amount|revenue_generated|refund_due|revenue_today|revenue_week|revenue_month|revenue_quarter|revenue_year
    """
    filter_key = (request.GET.get('filter') or '').strip().lower()
    allowed = {
        'total_invoices', 'total_amount', 'paid_amount', 'revenue_generated',
        'outstanding', 'refund_due',
        'revenue_today', 'revenue_week', 'revenue_month', 'revenue_quarter', 'revenue_year',
    }
    if filter_key not in allowed:
        return JsonResponse({'error': 'Invalid or missing filter', 'invoices': []}, status=400)

    try:
        qs = _get_invoices_for_card_filter(request, filter_key)
        # Use full queryset (no .only()) to avoid conflicts with filtered base and ensure all fields load
    except Exception as e:
        logger.exception('invoice_card_records_api filter failed')
        return JsonResponse({'error': str(e) or 'Server error', 'invoices': []}, status=200)

    company_profile = get_company_profile_for_user(request.user, request)
    currency_symbol = (company_profile.currency_symbol or "₦") if company_profile else "₦"
    currency_code = (company_profile.currency_code or "NGN") if company_profile else "NGN"
    from apps.accounts.rbac import is_company_admin as _is_company_admin
    from apps.core.mixins import is_read_only_user
    show_created_by = _is_company_admin(request) or is_read_only_user(request.user)

    # Status display labels (match list page: Not Paid, Pending, Paid, Delivered)
    status_display_map = {
        'unpaid': 'Not Paid',
        'partial': 'Pending',
        'paid': 'Paid',
        'delivered': 'Delivered',
    }

    def invoice_to_dict(inv):
        d = {
            'pk': inv.pk,
            'invoice_number': inv.invoice_number or '',
            'client_name': inv.client_name or '',
            'client_email': inv.client_email or '',
            'invoice_date': inv.invoice_date.strftime('%b %d, %Y') if inv.invoice_date else '—',
            'invoice_date_iso': inv.invoice_date.isoformat() if inv.invoice_date else '',
            'due_date': inv.due_date.strftime('%b %d, %Y') if inv.due_date else '—',
            'grand_total': str(inv.grand_total),
            'status': inv.status or 'unpaid',
            'status_display': status_display_map.get(inv.status, inv.get_status_display() or '—'),
            'detail_url': f'/invoices/{inv.pk}/',
            'edit_url': f'/invoices/{inv.pk}/edit/',
            'print_url': f'/invoices/{inv.pk}/print/',
        }
        if show_created_by:
            d['created_by_name'] = (inv.created_by.get_full_name() or inv.created_by.email) if inv.created_by else '—'
        return d

    user = request.user
    can_edit = user.has_perm('invoices.change_invoice') or _is_company_admin(request)
    can_print = user.has_perm('invoices.print_invoice') or _is_company_admin(request)
    can_delete = user.has_perm('invoices.delete_invoice') or _is_company_admin(request)

    try:
        invoices = [invoice_to_dict(inv) for inv in qs]
    except Exception as e:
        logger.exception('invoice_card_records_api serialize failed')
        return JsonResponse({'error': str(e) or 'Server error', 'invoices': []}, status=200)

    return JsonResponse({
        'invoices': invoices,
        'currency_symbol': currency_symbol,
        'show_created_by': show_created_by,
        'can_edit': can_edit,
        'can_print': can_print,
        'can_delete': can_delete,
    })


@login_required
@permission_required('invoices.view_invoice', raise_exception=True)
def invoice_report_api(request):
    """
    JSON API: return invoice report data with date filtering.
    GET parameters:
    - date_from: Start date (YYYY-MM-DD)
    - date_to: End date (YYYY-MM-DD)
    - filter: today|week|month|quarter|year|custom
    - details_page: 1-based page index for the Invoice Details table (default 1)
    - details_per_page: rows per page for that table, max 50 (default 10)
    - details_search: optional client search text for Invoice Details table
    - details_transaction_date: optional exact transaction date (YYYY-MM-DD) for Invoice Details table
    """
    from django.db.models.functions import Coalesce
    from apps.accounts.rbac import is_company_admin as _is_company_admin
    from django.db.models.functions import TruncMonth, TruncWeek, TruncDay
    
    filter_type = (request.GET.get('filter') or 'month').strip().lower()
    details_filter = (request.GET.get('details_filter') or 'all').strip().lower()
    details_search = (request.GET.get('details_search') or '').strip()
    details_transaction_date = (request.GET.get('details_transaction_date') or '').strip()
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    
    company_profile = get_company_profile_for_user(request.user, request)
    currency_symbol = (company_profile.currency_symbol or "₦") if company_profile else "₦"
    
    base_qs = for_user_queryset(Invoice, request.user, request, account_lookup='account')
    base_qs = base_qs.annotate(
        rev_cap=Least(F('amount_paid'), F('grand_total')),
        effective_date=Coalesce('invoice_date', 'created_at__date')
    )
    
    today = timezone.now().date()
    
    if filter_type == 'today':
        date_from = today
        date_to = today
    elif filter_type == 'week':
        week_start = today - timedelta(days=today.weekday())
        date_from = week_start
        date_to = week_start + timedelta(days=6)
    elif filter_type == 'month':
        date_from = today.replace(day=1)
        next_month = today.replace(day=28) + timedelta(days=4)
        date_to = next_month.replace(day=1) - timedelta(days=1)
    elif filter_type == 'quarter':
        quarter = (today.month - 1) // 3
        q_start_month = quarter * 3 + 1
        date_from = today.replace(month=q_start_month, day=1)
        next_quarter = date_from + timedelta(days=90)
        date_to = (next_quarter.replace(day=1) - timedelta(days=1))
    elif filter_type == 'year':
        date_from = today.replace(month=1, day=1)
        date_to = today.replace(month=12, day=31)
    
    if date_from:
        try:
            if isinstance(date_from, str):
                date_from = timezone.datetime.strptime(date_from, '%Y-%m-%d').date()
            base_qs = base_qs.filter(effective_date__gte=date_from)
        except (ValueError, TypeError):
            pass
    
    if date_to:
        try:
            if isinstance(date_to, str):
                date_to = timezone.datetime.strptime(date_to, '%Y-%m-%d').date()
            base_qs = base_qs.filter(effective_date__lte=date_to)
        except (ValueError, TypeError):
            pass
    
    filtered_qs = base_qs
    
    total_invoices = filtered_qs.count()
    total_amount = filtered_qs.aggregate(total=Sum('grand_total'))['total'] or 0
    paid_amount = filtered_qs.aggregate(total=Sum('amount_paid'))['total'] or 0
    outstanding = filtered_qs.filter(balance_due__gt=0).aggregate(total=Sum('balance_due'))['total'] or 0
    due_payment_amount = filtered_qs.aggregate(
        total=Sum(
            Case(
                When(amount_paid__gt=F('grand_total'), then=F('amount_paid') - F('grand_total')),
                default=Value(0),
                output_field=DecimalField(),
            )
        )
    )['total'] or 0
    revenue = filtered_qs.aggregate(total=Sum('rev_cap'))['total'] or 0
    completed_paid_amount = filtered_qs.filter(status='paid').aggregate(total=Sum('grand_total'))['total'] or 0
    partial_paid_amount = filtered_qs.filter(status='partial').aggregate(total=Sum('amount_paid'))['total'] or 0
    
    status_breakdown = filtered_qs.values('status').annotate(
        count=Count('id'),
        total=Sum('grand_total')
    ).order_by('-count')
    
    status_data = []
    for item in status_breakdown:
        status_data.append({
            'status': item['status'],
            'count': item['count'],
            'total': float(item['total'] or 0)
        })
    
    client_breakdown = filtered_qs.values('client_name').annotate(
        invoice_count=Count('id'),
        total_amount=Sum('grand_total'),
        total_paid=Sum('amount_paid')
    ).order_by('-total_amount')[:10]
    
    client_data = []
    for item in client_breakdown:
        client_data.append({
            'client_name': item['client_name'] or 'Unknown',
            'invoice_count': item['invoice_count'],
            'total_amount': float(item['total_amount'] or 0),
            'total_paid': float(item['total_paid'] or 0)
        })
    
    daily_revenue = filtered_qs.filter(rev_cap__gt=0).values('effective_date').annotate(
        revenue=Sum('rev_cap'),
        count=Count('id')
    ).order_by('effective_date')[:30]
    
    daily_data = []
    for item in daily_revenue:
        daily_data.append({
            'date': str(item['effective_date']),
            'revenue': float(item['revenue'] or 0),
            'count': item['count']
        })
    
    try:
        details_page = int(request.GET.get('details_page') or 1)
    except (TypeError, ValueError):
        details_page = 1
    details_page = max(1, details_page)
    try:
        details_per_page = int(request.GET.get('details_per_page') or 10)
    except (TypeError, ValueError):
        details_per_page = 10
    details_per_page = max(1, min(details_per_page, 50))

    invoices_qs = filtered_qs.select_related('created_by')
    # Optional details table filter from report summary card clicks
    if details_filter == 'outstanding':
        invoices_qs = invoices_qs.filter(balance_due__gt=0)
    elif details_filter in ('revenue_generated', 'paid_amount'):
        invoices_qs = invoices_qs.filter(rev_cap__gt=0)
    elif details_filter == 'completed_paid':
        invoices_qs = invoices_qs.filter(status='paid')
    elif details_filter == 'partial_paid':
        invoices_qs = invoices_qs.filter(status='partial')
    elif details_filter == 'refund_due':
        invoices_qs = invoices_qs.filter(amount_paid__gt=F('grand_total'))
    elif details_filter in ('all', 'total_invoices', 'total_amount'):
        pass
    else:
        details_filter = 'all'

    if details_search:
        invoices_qs = invoices_qs.filter(
            Q(client_name__icontains=details_search) |
            Q(client_email__icontains=details_search)
        )
    if details_transaction_date:
        try:
            tx_date = timezone.datetime.strptime(details_transaction_date, '%Y-%m-%d').date()
            invoices_qs = invoices_qs.filter(effective_date=tx_date)
        except (TypeError, ValueError):
            pass

    invoices_qs = invoices_qs.order_by('-created_at')
    paginator = Paginator(invoices_qs, details_per_page)
    page_obj = paginator.get_page(details_page)
    recent_data = []
    for inv in page_obj:
        recent_data.append({
            'invoice_number': inv.invoice_number or '',
            'client_name': inv.client_name or '',
            'invoice_date': inv.invoice_date.strftime('%Y-%m-%d') if inv.invoice_date else '',
            'grand_total': str(inv.grand_total),
            'amount_paid': str(inv.amount_paid),
            'balance_due': str(inv.balance_due),
            'status': inv.status or 'unpaid',
            'detail_url': f'/invoices/{inv.pk}/',
        })
    invoice_details_pagination = {
        'page': page_obj.number,
        'per_page': details_per_page,
        'total_count': paginator.count,
        'total_pages': paginator.num_pages,
        'has_next': page_obj.has_next(),
        'has_previous': page_obj.has_previous(),
    }
    
    avg_invoice_value = total_amount / total_invoices if total_invoices > 0 else 0
    paid_percentage = (paid_amount / total_amount * 100) if total_amount > 0 else 0
    
    return JsonResponse({
        'summary': {
            'total_invoices': total_invoices,
            'total_amount': float(total_amount),
            'paid_amount': float(paid_amount),
            'completed_paid_amount': float(completed_paid_amount),
            'partial_paid_amount': float(partial_paid_amount),
            'due_payment_amount': float(due_payment_amount),
            'outstanding': float(outstanding),
            'revenue': float(revenue),
            'avg_invoice_value': float(avg_invoice_value),
            'paid_percentage': float(paid_percentage),
        },
        'status_breakdown': status_data,
        'client_breakdown': client_data,
        'daily_revenue': daily_data,
        'recent_invoices': recent_data,
        'invoice_details_pagination': invoice_details_pagination,
        'currency_symbol': currency_symbol,
        'date_range': {
            'date_from': str(date_from) if date_from else None,
            'date_to': str(date_to) if date_to else None,
            'filter': filter_type,
        },
        'details_filter': details_filter,
    })


@login_required
@permission_required('invoices.view_invoice', raise_exception=True)
def invoice_supply_ledger_api(request):
    """
    Excel-style customer supply ledger for modal view.
    Returns item-level rows with delivery/outstanding overview.
    """
    filter_type = (request.GET.get('filter') or 'month').strip().lower()
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    company_profile = get_company_profile_for_user(request.user, request)
    currency_symbol = (company_profile.currency_symbol or "₦") if company_profile else "₦"

    base_qs = for_user_queryset(Invoice, request.user, request, account_lookup='account').prefetch_related('items')
    today = timezone.now().date()
    if filter_type == 'today':
        date_from = today
        date_to = today
    elif filter_type == 'week':
        week_start = today - timedelta(days=today.weekday())
        date_from = week_start
        date_to = week_start + timedelta(days=6)
    elif filter_type == 'month':
        date_from = today.replace(day=1)
        next_month = today.replace(day=28) + timedelta(days=4)
        date_to = next_month.replace(day=1) - timedelta(days=1)
    elif filter_type == 'quarter':
        quarter = (today.month - 1) // 3
        q_start_month = quarter * 3 + 1
        date_from = today.replace(month=q_start_month, day=1)
        next_quarter = date_from + timedelta(days=90)
        date_to = (next_quarter.replace(day=1) - timedelta(days=1))
    elif filter_type == 'year':
        date_from = today.replace(month=1, day=1)
        date_to = today.replace(month=12, day=31)

    if date_from:
        try:
            if isinstance(date_from, str):
                date_from = timezone.datetime.strptime(date_from, '%Y-%m-%d').date()
            base_qs = base_qs.filter(invoice_date__gte=date_from)
        except (ValueError, TypeError):
            pass
    if date_to:
        try:
            if isinstance(date_to, str):
                date_to = timezone.datetime.strptime(date_to, '%Y-%m-%d').date()
            base_qs = base_qs.filter(invoice_date__lte=date_to)
        except (ValueError, TypeError):
            pass

    invoices = list(base_qs.order_by('-created_at')[:800])
    page_aliases = set()
    for inv in invoices:
        if _normalize_customer_name(inv.client_name):
            page_aliases.add(('name', _normalize_customer_name(inv.client_name)))
        if _normalize_customer_email(inv.client_email):
            page_aliases.add(('email', _normalize_customer_email(inv.client_email)))
        if _normalize_customer_phone(inv.client_phone):
            page_aliases.add(('phone', _normalize_customer_phone(inv.client_phone)))

    customer_sync_state = _build_customer_sync_metrics(request, invoices) if invoices else {
        'buckets': {},
        'email_to_key': {},
        'phone_to_key': {},
        'name_to_key': {},
    }
    buckets = customer_sync_state.get('buckets', {})
    email_to_key = customer_sync_state.get('email_to_key', {})
    phone_to_key = customer_sync_state.get('phone_to_key', {})
    name_to_key = customer_sync_state.get('name_to_key', {})

    # Aggregate at customer + product level to avoid double counting.
    product_rows = {}
    customer_totals = defaultdict(lambda: {
        'billed_qty': Decimal('0'),
        'value_billed': Decimal('0'),
        'payment_allocated': Decimal('0'),
        'delivery_qty': Decimal('0'),
    })

    for inv in invoices:
        bucket_key = _resolve_customer_bucket_key(
            inv.client_name, inv.client_email, inv.client_phone, email_to_key, phone_to_key, name_to_key
        )
        if not bucket_key:
            continue
        customer_name = (inv.client_name or '').strip() or (buckets.get(bucket_key, {}).get('customer_name') or 'Unknown Customer')
        invoice_date_str = inv.invoice_date.strftime('%d-%b-%y') if inv.invoice_date else ''

        grand_total = Decimal(str(inv.grand_total or 0))
        amount_paid = Decimal(str(inv.amount_paid or 0))
        payment_ratio = (amount_paid / grand_total) if grand_total > 0 else Decimal('0')

        for item in inv.items.all():
            qty = Decimal(str(item.quantity or 0))
            unit_price = Decimal(str(item.unit_price or 0))
            amount = Decimal(str(item.line_total or 0))
            if amount == 0 and qty and unit_price:
                amount = qty * unit_price
            product_name = (item.product_service or item.description or 'Unnamed Item').strip()
            product_key = _normalize_customer_name(product_name) or 'unnamed-item'
            row_key = (bucket_key, product_key)
            row = product_rows.setdefault(row_key, {
                'date': invoice_date_str,
                'customer_name': customer_name,
                'product': product_name,
                'quantity': Decimal('0'),
                'price_total': Decimal('0'),
                'price_count': 0,
                'amount': Decimal('0'),
                'payment': Decimal('0'),
                'delivery': Decimal('0'),
                'u_balance': Decimal('0'),
                'outstanding': Decimal('0'),
                'customer_owes_company': Decimal('0'),
                'company_owes_customer': Decimal('0'),
                'excess_supplies': Decimal('0'),
            })
            row['quantity'] += qty
            row['amount'] += amount
            row['price_total'] += unit_price
            row['price_count'] += 1
            row['payment'] += (amount * payment_ratio)
            # Keep latest non-empty date for row ordering/visibility
            if invoice_date_str:
                row['date'] = invoice_date_str

    # Map waybill product deliveries where available.
    waybill_qs = for_user_queryset(Waybill, request.user, request, account_lookup='account').prefetch_related('items').only(
        'id', 'waybill_number', 'waybill_date', 'status', 'custom_data', 'total_quantity_value', 'delivered_quantity_value', 'remaining_quantity_value', 'created_at'
    )
    customer_waybill_overview = defaultdict(lambda: {
        'waybill_count': 0,
        'delivered_waybills': 0,
        'outstanding_waybills': 0,
        'total_delivered_qty': Decimal('0'),
        'total_outstanding_qty': Decimal('0'),
        'waybills': [],
    })
    customer_delivery_unassigned = defaultdict(Decimal)
    for wb in waybill_qs:
        contact = _extract_waybill_customer_contact(wb)
        bucket_key = _resolve_customer_bucket_key(
            contact.get('name'), contact.get('email'), contact.get('phone'),
            email_to_key, phone_to_key, name_to_key,
        )
        if not bucket_key:
            continue
        custom_data = getattr(wb, 'custom_data', {}) or {}
        delivery_quantities = custom_data.get('delivery_quantities') or []
        matched_any = False
        for dq in delivery_quantities:
            if not isinstance(dq, dict):
                continue
            product_name = (dq.get('product') or dq.get('product_service') or dq.get('description') or '').strip()
            if not product_name:
                continue
            delivered_val = _parse_decimal_quantity(dq.get('delivered_quantity_input'))
            if delivered_val <= 0:
                delivered_val = _parse_decimal_quantity(dq.get('total_quantity_input'))
            product_key = _normalize_customer_name(product_name)
            row_key = (bucket_key, product_key)
            if row_key in product_rows:
                product_rows[row_key]['delivery'] += delivered_val
                matched_any = True
        if not matched_any:
            # Fallback to WaybillItem rows when delivery_quantities don't carry product labels.
            for wb_item in wb.items.all():
                item_data = getattr(wb_item, 'item_data', {}) or {}
                product_name = _extract_waybill_item_product(item_data)
                if not product_name:
                    continue
                total_qty = _extract_waybill_item_total_qty(item_data)
                if total_qty <= 0:
                    continue
                delivered_val = Decimal(str(getattr(wb, 'delivered_quantity_value', 0) or 0))
                total_val = Decimal(str(getattr(wb, 'total_quantity_value', 0) or 0))
                if delivered_val > 0 and total_val > 0:
                    delivered_val = delivered_val * (total_qty / total_val)
                else:
                    delivered_val = total_qty
                product_key = _normalize_customer_name(product_name)
                row_key = (bucket_key, product_key)
                if row_key in product_rows:
                    product_rows[row_key]['delivery'] += delivered_val
                    matched_any = True
        if not matched_any:
            customer_delivery_unassigned[bucket_key] += Decimal(str(getattr(wb, 'delivered_quantity_value', 0) or 0))
        wb_total_qty = Decimal(str(getattr(wb, 'total_quantity_value', 0) or 0))
        wb_delivered_qty = Decimal(str(getattr(wb, 'delivered_quantity_value', 0) or 0))
        wb_outstanding_qty = Decimal(str(getattr(wb, 'remaining_quantity_value', 0) or 0))
        if wb_outstanding_qty < 0:
            wb_outstanding_qty = Decimal('0')
        overview = customer_waybill_overview[bucket_key]
        overview['waybill_count'] += 1
        overview['total_delivered_qty'] += wb_delivered_qty
        overview['total_outstanding_qty'] += wb_outstanding_qty
        if wb_outstanding_qty > 0:
            overview['outstanding_waybills'] += 1
        else:
            overview['delivered_waybills'] += 1
        overview['waybills'].append({
            'waybill_number': wb.waybill_number or f'WB-{wb.id}',
            'waybill_date': wb.waybill_date.strftime('%d-%b-%y') if wb.waybill_date else '',
            'status': wb.status or '',
            'total_qty': float(wb_total_qty),
            'delivered_qty': float(wb_delivered_qty),
            'outstanding_qty': float(wb_outstanding_qty),
            'detail_url': f'/waybills/{wb.id}/',
        })

    # Distribute unassigned delivery proportionally by billed qty within customer.
    qty_by_customer = defaultdict(Decimal)
    for (bucket_key, _), row in product_rows.items():
        qty_by_customer[bucket_key] += row['quantity']
    for (bucket_key, _), row in product_rows.items():
        unassigned = customer_delivery_unassigned.get(bucket_key, Decimal('0'))
        total_qty = qty_by_customer.get(bucket_key, Decimal('0'))
        if unassigned > 0 and total_qty > 0:
            row['delivery'] += (unassigned * (row['quantity'] / total_qty))

    rows = []
    totals = {
        'total_supply_amount': Decimal('0'),
        'total_payment': Decimal('0'),
        'total_outstanding_amount': Decimal('0'),
        'total_quantity': Decimal('0'),
        'total_delivery_qty': Decimal('0'),
        'total_outstanding_qty': Decimal('0'),
        'total_customer_owes_company': Decimal('0'),
        'total_company_owes_customer': Decimal('0'),
        'total_excess_supplies': Decimal('0'),
        'total_jobs_owed_count': 0,
        'total_jobs_owed_amount': Decimal('0'),
        'total_jobs_amount': Decimal('0'),
    }
    for (bucket_key, _), row in product_rows.items():
        billed_qty = row['quantity']
        delivered_qty = row['delivery']
        delivery_outstanding = billed_qty - delivered_qty
        excess_supplies = Decimal('0')
        if delivery_outstanding < 0:
            excess_supplies = abs(delivery_outstanding)
            delivery_outstanding = Decimal('0')

        value_billed = row['amount']
        paid_val = row['payment']
        amount_gap = value_billed - paid_val
        customer_owes = amount_gap if amount_gap > 0 else Decimal('0')
        company_owes = abs(amount_gap) if amount_gap < 0 else Decimal('0')

        if customer_owes == 0 and delivery_outstanding == 0:
            remark = 'FULLY SUPPLIED AND PAID'
        elif customer_owes > 0 and delivery_outstanding == 0:
            remark = 'FULLY SUPPLIED AND PART PAID'
        elif delivery_outstanding > 0 and paid_val > 0:
            remark = 'PARTLY SUPPLIED'
        elif delivery_outstanding > 0 and paid_val <= 0:
            remark = 'NOT SUPPLIED'
        elif company_owes > 0:
            remark = 'COMPANY OWES CUSTOMER'
        else:
            remark = 'PENDING RECONCILIATION'

        avg_price = (row['price_total'] / Decimal(str(row['price_count'] or 1))) if row['price_count'] else Decimal('0')
        row_payload = {
            'date': row['date'],
            'date_iso': '',
            'customer_key': bucket_key,
            'customer_name': row['customer_name'],
            'product': row['product'],
            'quantity': float(billed_qty),
            'price': float(avg_price),
            'amount': float(value_billed),
            'payment': float(paid_val),
            'q_supplied': float(billed_qty),
            'delivery': float(delivered_qty),
            'u_balance': float(delivery_outstanding),
            'outstanding': float(customer_owes),
            'customer_owes_company': float(customer_owes),
            'company_owes_customer': float(company_owes),
            'excess_supplies': float(excess_supplies),
            'remark': remark,
            'job_owed': delivery_outstanding > 0,
        }
        if row.get('date'):
            # best effort reverse parse from source invoices for stable client-side date filtering
            row_payload['date_iso'] = ''
        rows.append(row_payload)

        totals['total_supply_amount'] += value_billed
        totals['total_payment'] += paid_val
        totals['total_outstanding_amount'] += customer_owes
        totals['total_quantity'] += billed_qty
        totals['total_delivery_qty'] += delivered_qty
        totals['total_outstanding_qty'] += delivery_outstanding
        totals['total_customer_owes_company'] += customer_owes
        totals['total_company_owes_customer'] += company_owes
        totals['total_excess_supplies'] += excess_supplies
        totals['total_jobs_amount'] += value_billed
        if delivery_outstanding > 0:
            totals['total_jobs_owed_count'] += 1
            totals['total_jobs_owed_amount'] += value_billed

    rows.sort(key=lambda r: (r.get('customer_name') or '', r.get('product') or ''))
    waybill_overview_payload = {}
    for key, ov in customer_waybill_overview.items():
        waybill_overview_payload[key] = {
            'waybill_count': ov['waybill_count'],
            'delivered_waybills': ov['delivered_waybills'],
            'outstanding_waybills': ov['outstanding_waybills'],
            'total_delivered_qty': float(ov['total_delivered_qty']),
            'total_outstanding_qty': float(ov['total_outstanding_qty']),
            'waybills': ov['waybills'],
        }

    return JsonResponse({
        'rows': rows,
        'summary': {
            'line_count': len(rows),
            'total_supply_amount': float(totals['total_supply_amount']),
            'total_payment': float(totals['total_payment']),
            'total_outstanding_amount': float(totals['total_outstanding_amount']),
            'total_quantity': float(totals['total_quantity']),
            'total_delivery_qty': float(totals['total_delivery_qty']),
            'total_outstanding_qty': float(totals['total_outstanding_qty']),
            'total_customer_owes_company': float(totals['total_customer_owes_company']),
            'total_company_owes_customer': float(totals['total_company_owes_customer']),
            'total_excess_supplies': float(totals['total_excess_supplies']),
            'total_jobs_owed_count': totals['total_jobs_owed_count'],
            'total_jobs_owed_amount': float(totals['total_jobs_owed_amount']),
            'total_jobs_amount': float(totals['total_jobs_amount']),
        },
        'waybill_overview': waybill_overview_payload,
        'currency_symbol': currency_symbol,
        'date_range': {
            'date_from': str(date_from) if date_from else None,
            'date_to': str(date_to) if date_to else None,
            'filter': filter_type,
        },
    })


def get_invoice_context(invoice, user, request=None):
    """Get context data for invoice rendering. Uses account company profile so team members see logo/details. Pass request so team members get account company currency."""
    company_profile = get_company_profile_for_user(user, request)
    company_logo = None
    company_signature = None
    default_bank_account = None
    bank_accounts = []
    if company_profile:
        if company_profile.logo:
            company_logo = company_profile.logo.url
        if company_profile.signature:
            company_signature = company_profile.signature.url
        from apps.core.models import BankAccount
        default_bank_account = BankAccount.objects.filter(
            company=company_profile, is_default=True
        ).first()
        if not default_bank_account:
            default_bank_account = BankAccount.objects.filter(company=company_profile).first()
        bank_accounts = list(BankAccount.objects.filter(
            company=company_profile, is_active=True
        ).order_by('-is_default', 'bank_name'))
    
    # User profile for display (use given user for name/email)
    user_profile = {
        'full_name': user.get_full_name(),
        'email': user.email,
        'phone': getattr(user, 'phone', None),
        'location': getattr(user, 'location', None),
        'website': getattr(user, 'website', None),
    }
    
    # Current default template (account-scoped so team members see account templates)
    account = get_account_for_user(user)
    if account:
        current_template = InvoiceTemplate.objects.filter(user__account=account, is_default=True).first()
        if not current_template:
            current_template = InvoiceTemplate.objects.filter(user__account=account).first()
    else:
        current_template = InvoiceTemplate.objects.filter(user=user).first()
    if not current_template and user:
        current_template = InvoiceTemplate.objects.create(
            user=user,
            name="Default Invoice Template",
            description="Automatically created default template",
            is_default=True
        )
    
    # Get theme colors from company profile (for templates that don't extend base.html)
    theme_primary_color = getattr(company_profile, 'primary_color', '#1976d2') if company_profile else '#1976d2'
    theme_secondary_color = getattr(company_profile, 'secondary_color', '#f8f9fa') if company_profile else '#f8f9fa'
    theme_accent_color = getattr(company_profile, 'accent_color', '#e9ecef') if company_profile else '#e9ecef'
    theme_text_color = getattr(company_profile, 'text_color', '#333333') if company_profile else '#333333'
    
    # Get currency symbol / code
    currency_symbol = getattr(company_profile, 'currency_symbol', '₦') if company_profile else '₦'
    currency_code = getattr(company_profile, 'currency_code', 'NGN') if company_profile else 'NGN'

    from apps.core.utils import number_to_words
    amount_for_words = invoice.amount_paid if invoice.amount_paid and invoice.amount_paid > 0 else invoice.grand_total
    amount_in_words = number_to_words(amount_for_words, currency_code)
    
    return {
        'invoice': invoice,
        'company_profile': company_profile,
        'company_logo': company_logo,
        'company_signature': company_signature,
        'default_bank_account': default_bank_account,
        'bank_accounts': bank_accounts,
        'user_profile': user_profile,
        'current_template': current_template,  # Use current template instead of invoice.template
        'currency_symbol': currency_symbol,
        'currency_code': currency_code,
        'amount_in_words': amount_in_words,
        # Theme colors for all templates (including standalone print/PDF)
        'theme_primary_color': theme_primary_color,
        'theme_secondary_color': theme_secondary_color,
        'theme_accent_color': theme_accent_color,
        'theme_text_color': theme_text_color,
    }


@login_required
@company_admin_or_permission_required('invoices.view_invoice', raise_exception=True)
def invoice_detail(request, pk):
    """View invoice details (per-team-member: admin sees all, team member sees own only)"""
    from apps.accounts.services import _clear_user_permission_cache
    from apps.accounts.models import SubUser

    if SubUser.objects.filter(linked_user=request.user).exists():
        _clear_user_permission_cache(request.user)

    from apps.accounts.rbac import is_company_admin as _is_company_admin
    is_company_admin = _is_company_admin(request)
    can_change_invoice = is_company_admin or request.user.has_perm('invoices.change_invoice')
    can_print_invoice = is_company_admin or request.user.has_perm('invoices.print_invoice')
    can_create_invoice = request.user.has_perm('invoices.add_invoice')

    qs = for_user_queryset(Invoice, request.user, request, account_lookup='account').select_related('user', 'created_by').prefetch_related('items')
    invoice, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return response
    context = get_invoice_context(invoice, request.user, request)
    context.update({
        'is_company_admin': is_company_admin,
        'can_change_invoice': can_change_invoice,
        'can_print_invoice': can_print_invoice,
        'can_create_invoice': can_create_invoice,
    })
    return render(request, 'invoices/invoice_detail.html', context)


def _invoice_create_post(request):
    """Save a new invoice from the create form POST. Raises on unexpected errors."""
    invoice = Invoice(user=request.user)

    invoice.client_name = request.POST.get('client_name', '')
    invoice.client_email = request.POST.get('client_email', '')
    invoice.client_phone = request.POST.get('client_phone', '')
    invoice.client_address = request.POST.get('client_address', '')

    invoice_date = request.POST.get('invoice_date')
    invoice.invoice_date = invoice_date if invoice_date and invoice_date.strip() else None

    due_date = request.POST.get('due_date')
    invoice.due_date = due_date if due_date and due_date.strip() else None

    invoice.notes = request.POST.get('notes', '')

    tax_input = request.POST.get('tax_input') or request.POST.get('tax_rate', '0')
    discount_input = request.POST.get('total_discount') or request.POST.get('discount', '0')
    tax_type = request.POST.get('tax_type', 'percentage')
    discount_type = request.POST.get('discount_type', 'percentage')

    _, detected_tax_type, tax_value = Invoice.parse_number_with_type(tax_input)
    if '%' in str(tax_input):
        tax_type = 'percentage'

    _, detected_discount_type, discount_value = Invoice.parse_number_with_type(discount_input)
    if '%' in str(discount_input):
        discount_type = 'percentage'

    shipping_fee = safe_decimal_for_db(Invoice.parse_number(request.POST.get('shipping_fee', '0')))
    other_charges = safe_decimal_for_db(Invoice.parse_number(request.POST.get('other_charges', '0')))
    amount_paid = safe_decimal_for_db(Invoice.parse_number(request.POST.get('amount_paid', '0')))

    invoice.tax_type = tax_type
    invoice.tax_value = tax_value
    invoice.discount_type = discount_type
    invoice.discount_value = discount_value

    if tax_type == 'percentage':
        invoice._tax_rate = tax_value
    else:
        invoice._tax_rate = None
        invoice.total_tax = tax_value

    if discount_type == 'percentage':
        invoice._discount_rate = discount_value
    else:
        invoice._discount_rate = None
        invoice._discount_fixed = discount_value

    invoice.shipping_fee = shipping_fee
    invoice.other_charges = other_charges
    invoice.amount_paid = amount_paid

    acc = get_account_for_user(request.user)
    template_id = request.POST.get('template')
    if template_id:
        try:
            if acc:
                template = InvoiceTemplate.objects.get(id=template_id, user__account=acc)
            else:
                template = InvoiceTemplate.objects.get(id=template_id, user=request.user)
            invoice.template = template
        except InvoiceTemplate.DoesNotExist:
            pass
    else:
        default_template = (
            InvoiceTemplate.objects.filter(user__account=acc, is_default=True).first()
            if acc else InvoiceTemplate.objects.filter(user=request.user, is_default=True).first()
        )
        if default_template:
            invoice.template = default_template
    if acc and not invoice.account_id:
        invoice.account_id = acc.id

    if 'display_settings_submitted' in request.POST:
        invoice.show_bank_details = 'show_bank_details' in request.POST or request.POST.get('show_bank_details') == 'on'
        invoice.show_signature = 'show_signature' in request.POST or request.POST.get('show_signature') == 'on'
    else:
        invoice.show_bank_details = True
        invoice.show_signature = True

    from apps.invoices.signals import suppress_invoice_movements, _create_movement, write_invoice_activity

    items_data = {}
    for key, value in request.POST.items():
        if key.startswith('items[') and '][' in key:
            item_index = key.split('[')[1].split(']')[0]
            field_name = key.split('[')[2].split(']')[0]
            if item_index not in items_data:
                items_data[item_index] = {}
            items_data[item_index][field_name] = value

    new_items = []
    subtotal = Decimal("0")

    for index, item_data in items_data.items():
        product_service = item_data.get('product_service', '').strip()
        description = item_data.get('description', '').strip()
        quantity = item_data.get('quantity', '').strip()
        unit_price = item_data.get('unit_price', '').strip()

        if product_service or description or quantity or unit_price:
            parsed_quantity = Invoice.parse_number(quantity or '0')
            parsed_price = Invoice.parse_number(unit_price or '0')
            safe_quantity = safe_decimal_for_db(parsed_quantity, 2)
            safe_unit_price = safe_decimal_for_db(parsed_price, 2)
            line_total = safe_decimal_for_db(safe_quantity * safe_unit_price, 2)

            new_items.append(InvoiceItem(
                invoice=invoice,
                product_service=product_service or '',
                description=description or '',
                quantity=safe_quantity,
                quantity_display=quantity or '',
                unit_price=safe_unit_price,
                line_total=line_total,
            ))
            subtotal += line_total

    def _do_create():
        if invoice.pk:
            invoice.pk = None
        with suppress_invoice_movements():
            with transaction.atomic():
                invoice.save()
                for item in new_items:
                    item.pk = None
                    item.invoice = invoice
                if new_items:
                    InvoiceItem.objects.bulk_create(new_items)
                invoice.subtotal = subtotal
                invoice.calculate_totals()
                invoice.save(update_fields=[
                    'subtotal', 'total_tax', 'tax_type', 'tax_value',
                    'total_discount', 'discount_type', 'discount_value',
                    'grand_total', 'balance_due', 'status',
                    'shipping_fee', 'other_charges', 'amount_paid',
                ])
        _create_movement(invoice)
        return invoice

    _retry_on_db_lock(_do_create)
    write_invoice_activity(invoice, created=True)

    messages.success(request, f'Invoice {invoice.invoice_number} created successfully!')
    return redirect('invoices:detail', pk=invoice.pk)


@login_required
@company_admin_or_permission_required('invoices.add_invoice', raise_exception=True)
def invoice_create(request):
    """Create new invoice with dynamic preview"""
    if request.method == 'POST':
        try:
            return _invoice_create_post(request)
        except Exception as exc:
            logger.exception('Invoice create failed for user_id=%s', getattr(request.user, 'pk', None))
            if _is_db_lock_error(exc):
                messages.error(request, _INVOICE_DB_BUSY_MSG)
            else:
                # Keep message short; include exception type so support can spot
                # InvoiceMovement / auth_user FK issues vs other failures.
                detail = f'{type(exc).__name__}: {exc}'
                if len(detail) > 180:
                    detail = detail[:177] + '...'
                messages.error(
                    request,
                    f'Could not save the invoice. Please try again. ({detail})',
                )

    # GET request - show the dynamic form
    company_profile = get_company_profile_for_user(request.user, request)
    company_logo = None
    company_signature = None
    default_bank_account = None
    bank_accounts = []
    if company_profile:
        from apps.core.models import BankAccount
        if company_profile.logo:
            company_logo = company_profile.logo.url
        if company_profile.signature:
            company_signature = company_profile.signature.url

        # Get default bank account
        default_bank_account = BankAccount.objects.filter(
            company=company_profile,
            is_default=True
        ).first()

        # If no default, get the first bank account
        if not default_bank_account:
            default_bank_account = BankAccount.objects.filter(
                company=company_profile
            ).first()

        # All active bank accounts (default first) - always load for create form
        bank_accounts = list(BankAccount.objects.filter(
            company=company_profile, is_active=True
        ).order_by('-is_default', 'bank_name'))

    # Invoice templates (account-scoped so team members see account templates)
    account = get_account_for_user(request.user)
    templates = InvoiceTemplate.objects.filter(user__account=account) if account else InvoiceTemplate.objects.filter(user=request.user)
    default_template = templates.filter(is_default=True).first()
    
    if not templates.exists():
        default_template = InvoiceTemplate.objects.create(
            user=request.user,
            name="My First Invoice Template",
            description="Automatically created default template with standard colors",
            is_default=True
        )
        templates = InvoiceTemplate.objects.filter(user__account=account) if account else InvoiceTemplate.objects.filter(user=request.user)
    
    # Get theme colors from company profile
    theme_primary_color = getattr(company_profile, 'primary_color', '#1976d2') if company_profile else '#1976d2'
    theme_secondary_color = getattr(company_profile, 'secondary_color', '#f8f9fa') if company_profile else '#f8f9fa'
    theme_accent_color = getattr(company_profile, 'accent_color', '#e9ecef') if company_profile else '#e9ecef'
    theme_text_color = getattr(company_profile, 'text_color', '#333333') if company_profile else '#333333'
    
    # Get currency symbol
    currency_symbol = getattr(company_profile, 'currency_symbol', '₦') if company_profile else '₦'
    
    context = {
        'title': 'Create Invoice',
        'company_profile': company_profile,
        'company_logo': company_logo,
        'company_signature': company_signature,
        'default_bank_account': default_bank_account,
        'bank_accounts': bank_accounts,
        'templates': templates,
        'default_template': default_template,
        # Theme colors
        'theme_primary_color': theme_primary_color,
        'theme_secondary_color': theme_secondary_color,
        'theme_accent_color': theme_accent_color,
        'theme_text_color': theme_text_color,
        'currency_symbol': currency_symbol,
    }
    response = render(request, 'invoices/invoice_create_dynamic.html', context)
    # Prevent browser caching so bank accounts and profile data are always fresh on first open
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    return response


@login_required
@company_admin_or_permission_required('invoices.change_invoice', raise_exception=True)
def invoice_edit(request, pk):
    """Edit existing invoice (per-team-member: admin sees all, team member edits own only)"""
    qs = for_user_queryset(Invoice, request.user, request, account_lookup='account')
    invoice, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return response
    company_profile = get_company_profile_for_user(request.user, request)
    company_signature = None
    default_bank_account = None
    bank_accounts = []
    if company_profile:
        from apps.core.models import BankAccount
        if company_profile.signature:
            company_signature = company_profile.signature.url
        
        # Get default bank account and all active bank accounts
        if company_profile:
            default_bank_account = BankAccount.objects.filter(
                company=company_profile, 
                is_default=True
            ).first()
            if not default_bank_account:
                default_bank_account = BankAccount.objects.filter(
                    company=company_profile
                ).first()
            bank_accounts = list(BankAccount.objects.filter(
                company=company_profile, is_active=True
            ).order_by('-is_default', 'bank_name'))

    if request.method == 'POST':
        form = InvoiceForm(request.POST, instance=invoice, user=request.user)
        formset = InvoiceItemFormSet(request.POST, instance=invoice)
        
        if form.is_valid() and formset.is_valid():
            try:
                from apps.invoices.signals import suppress_invoice_movements, _create_movement, write_invoice_activity

                new_items = []
                subtotal = Decimal("0")

                for i, item_form in enumerate(formset.forms):
                    if not hasattr(item_form, "cleaned_data"):
                        continue

                    data = item_form.cleaned_data

                    if data.get("DELETE"):
                        continue

                    product_service = (data.get("product_service") or "").strip()
                    description = (data.get("description") or "").strip()
                    quantity = safe_decimal_for_db(data.get("quantity") or Decimal("0"), 2)
                    unit_price = safe_decimal_for_db(data.get("unit_price") or Decimal("0"), 2)
                    quantity_display = (data.get("quantity_display") or "").strip() or str(quantity)

                    if not (product_service or description or quantity or unit_price):
                        continue

                    line_total = safe_decimal_for_db(quantity * unit_price, 2)

                    new_items.append(InvoiceItem(
                        invoice=invoice,
                        product_service=product_service,
                        description=description,
                        quantity=quantity,
                        quantity_display=quantity_display,
                        unit_price=unit_price,
                        line_total=line_total,
                    ))
                    subtotal += line_total

                def _do_save():
                    with suppress_invoice_movements():
                        with transaction.atomic():
                            saved = form.save()

                            _replace_invoice_line_items(saved, new_items)

                            saved.subtotal = subtotal
                            tax_input_value = request.POST.get('tax_input', '0')
                            discount_input_value = request.POST.get('total_discount', '0')
                            tax_type = request.POST.get('tax_type', 'percentage')
                            discount_type = request.POST.get('discount_type', 'percentage')

                            _, _, tax_value = Invoice.parse_number_with_type(tax_input_value)
                            _, _, discount_value = Invoice.parse_number_with_type(discount_input_value)

                            saved.tax_type = tax_type
                            saved.tax_value = tax_value
                            saved.discount_type = discount_type
                            saved.discount_value = discount_value
                            if tax_type == 'percentage':
                                saved._tax_rate = tax_value
                            else:
                                saved._tax_rate = None
                                saved.total_tax = tax_value
                            if discount_type == 'percentage':
                                saved._discount_rate = discount_value
                            else:
                                saved._discount_rate = None
                                saved._discount_fixed = discount_value

                            saved.shipping_fee = form.cleaned_data.get('shipping_fee', 0)
                            saved.other_charges = form.cleaned_data.get('other_charges', 0)
                            saved.amount_paid = form.cleaned_data.get('amount_paid', 0)

                            if 'display_settings_submitted' in request.POST:
                                saved.show_bank_details = 'showBankDetails' in request.POST or request.POST.get('showBankDetails') == 'on'
                                saved.show_signature = 'showSignature' in request.POST or request.POST.get('showSignature') == 'on'

                            saved.calculate_totals()
                            saved.save()
                    _create_movement(saved)
                    return saved

                invoice = _retry_on_db_lock(_do_save)
                write_invoice_activity(invoice, created=False)

                messages.success(request, f'Invoice {invoice.invoice_number} updated successfully!')
                return redirect('invoices:detail', pk=invoice.pk)
            except Exception as exc:
                logger.exception('Invoice edit failed for invoice_id=%s user_id=%s', pk, getattr(request.user, 'pk', None))
                if _is_db_lock_error(exc):
                    messages.error(request, _INVOICE_DB_BUSY_MSG)
                else:
                    detail = f'{type(exc).__name__}: {exc}'
                    if len(detail) > 180:
                        detail = detail[:177] + '...'
                    messages.error(
                        request,
                        f'Could not save the invoice. Please try again. ({detail})',
                    )
        else:
            # Add error messages for debugging
            logger.debug("Form validation failed!")
            if not form.is_valid():
                logger.debug(f"Main form errors: {form.errors}")
                for field, errors in form.errors.items():
                    for error in errors:
                        messages.error(request, f'Error in {field}: {error}')
            if not formset.is_valid():
                logger.debug(f"Formset errors: {formset.errors}")
                logger.debug(f"Formset non-form errors: {formset.non_form_errors()}")
                for i, form_errors in enumerate(formset.errors):
                    if form_errors:
                        for field, errors in form_errors.items():
                            if field in ('id', 'invoice', 'DELETE'):
                                continue
                            for error in errors:
                                messages.error(request, f'Error in item {i+1} {field}: {error}')
                for error in formset.non_form_errors():
                    messages.error(request, f'Formset error: {error}')
    else:
        form = InvoiceForm(instance=invoice, user=request.user)
        formset = InvoiceItemFormSet(instance=invoice)
        
        # Set discount and tax types for display
        form.fields['tax_type'].initial = invoice.tax_type or 'percentage'
        form.fields['discount_type'].initial = invoice.discount_type or 'percentage'
    
    # Debug: Print formset prefix for JavaScript (enabled for troubleshooting)
    logger.debug(f"Formset prefix: {formset.prefix}")
    logger.debug(f"Form fields: {list(form.fields.keys())}")
    logger.debug(f"Formset forms count: {len(formset.forms)}")
    
    # Debug: Show what's in the formset
    for i, form_instance in enumerate(formset.forms):
        if hasattr(form_instance, 'instance') and form_instance.instance.pk:
            logger.debug(f"  Formset form {i}: {form_instance.instance.product_service!r} (ID: {form_instance.instance.pk})")
    
    # Get theme colors from company profile
    theme_primary_color = getattr(company_profile, 'primary_color', '#1976d2') if company_profile else '#1976d2'
    theme_secondary_color = getattr(company_profile, 'secondary_color', '#f8f9fa') if company_profile else '#f8f9fa'
    theme_accent_color = getattr(company_profile, 'accent_color', '#e9ecef') if company_profile else '#e9ecef'
    theme_text_color = getattr(company_profile, 'text_color', '#333333') if company_profile else '#333333'
    
    context = {
        'form': form,
        'formset': formset,
        'invoice': invoice,
        'title': f'Edit Invoice {invoice.invoice_number}',
        'company_profile': company_profile,
        'company_signature': company_signature,
        'default_bank_account': default_bank_account,
        'bank_accounts': bank_accounts,
        'currency_symbol': company_profile.currency_symbol if company_profile else '₦',
        'formset_prefix': formset.prefix,
        # Theme colors
        'theme_primary_color': theme_primary_color,
        'theme_secondary_color': theme_secondary_color,
        'theme_accent_color': theme_accent_color,
        'theme_text_color': theme_text_color,
    }
    return render(request, 'invoices/invoice_form.html', context)


@login_required
@company_admin_or_permission_required('invoices.delete_invoice', raise_exception=True)
def invoice_delete(request, pk):
    """Delete invoice with confirmation (per-team-member: only own or admin)"""
    qs = for_user_queryset(Invoice, request.user, request, account_lookup='account')
    invoice, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return response
    if request.method == 'POST':
        invoice_number = invoice.invoice_number
        invoice.delete()
        messages.success(request, f'Invoice {invoice_number} deleted successfully!')
        return redirect('invoices:list')
    
    context = {'invoice': invoice}
    return render(request, 'invoices/invoice_delete.html', context)


@login_required
@company_admin_or_permission_required('invoices.delete_invoice', raise_exception=True)
def invoice_delete_ajax(request, pk):
    """AJAX delete invoice (per-team-member: only own or admin)"""
    if request.method == 'POST':
        try:
            qs = for_user_queryset(Invoice, request.user, request, account_lookup='account')
            invoice, response = get_object_or_unauthorized(request, qs, pk=pk)
            if response:
                return response
            invoice_number = invoice.invoice_number
            invoice.delete()
            
            return JsonResponse({
                'success': True,
                'message': f'Invoice {invoice_number} deleted successfully!'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})


@login_required
@company_admin_or_permission_required('invoices.print_invoice', raise_exception=True)
def invoice_pdf(request, pk):
    """Redirect to invoice print page (same as Print button - users can print or save as PDF from browser)."""
    return redirect('invoices:print', pk=pk)


@login_required
@company_admin_or_permission_required('invoices.print_invoice', raise_exception=True)
def invoice_print(request, pk):
    """Print-friendly invoice view (per-team-member: only own or admin)"""
    qs = for_user_queryset(Invoice, request.user, request, account_lookup='account')
    invoice, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return response
    # Use the same context as the detail and PDF views
    context = get_invoice_context(invoice, request.user, request)
    
    return render(request, 'invoices/invoice_print.html', context)


# ==============================================================================
# INVOICE TEMPLATE VIEWS
# ==============================================================================

@login_required
@permission_required('invoices.view_invoicetemplate', raise_exception=True)
def template_list(request):
    """List user's invoice templates - Staff only"""
    account = get_account_for_user(request.user)
    templates = (InvoiceTemplate.objects.filter(user__account=account) if account else InvoiceTemplate.objects.filter(user=request.user)).select_related('user')
    
    context = {
        'templates': templates,
    }
    return render(request, 'invoices/template_list.html', context)


@login_required
@permission_required('invoices.add_invoicetemplate', raise_exception=True)
def template_create(request):
    """Create new invoice template"""
    account = get_account_for_user(request.user)
    if request.method == 'POST':
        form = InvoiceTemplateForm(request.POST, user=request.user)
        if form.is_valid():
            template = form.save(commit=False)
            template.user = request.user
            
            # Check if template name already exists for this user
            if (InvoiceTemplate.objects.filter(user__account=account, name=template.name) if account else InvoiceTemplate.objects.filter(user=request.user, name=template.name)).exclude(pk=template.pk).exists():
                form.add_error('name', f'You already have a template named "{template.name}". Please choose a different name.')
            else:
                try:
                    template.save()
                    messages.success(request, f'Template "{template.name}" created successfully!')
                    return redirect('invoices:template_detail', pk=template.pk)
                except Exception as e:
                    messages.error(request, f'Error creating template: {str(e)}')
    else:
        form = InvoiceTemplateForm(user=request.user)
    
    context = {
        'form': form,
        'title': 'Create Invoice Template',
    }
    return render(request, 'invoices/template_form.html', context)


@login_required
@permission_required('invoices.change_invoicetemplate', raise_exception=True)
def template_edit(request, pk):
    """Edit invoice template"""
    account = get_account_for_user(request.user)
    template = get_object_or_404(InvoiceTemplate, pk=pk, user__account=account) if account else get_object_or_404(InvoiceTemplate, pk=pk, user=request.user)
    
    if request.method == 'POST':
        form = InvoiceTemplateForm(request.POST, instance=template, user=request.user)
        if form.is_valid():
            template = form.save()
            messages.success(request, f'Template "{template.name}" updated successfully!')
            
            # Update all existing invoices (visible to user) with this template to reflect color changes
            invoices_updated = for_user_queryset(Invoice, request.user, request, account_lookup='account').filter(
                template=template
            ).update(updated_at=template.updated_at)
            
            if invoices_updated > 0:
                messages.info(request, f'Color changes applied to {invoices_updated} existing invoices.')
            
            return redirect('invoices:template_detail', pk=template.pk)
    else:
        form = InvoiceTemplateForm(instance=template, user=request.user)
    
    context = {
        'form': form,
        'template': template,
        'title': f'Edit Template: {template.name}',
    }
    return render(request, 'invoices/template_form.html', context)


@login_required
@permission_required('invoices.view_invoicetemplate', raise_exception=True)
def template_detail(request, pk):
    """View template details and preview"""
    account = get_account_for_user(request.user)
    template = get_object_or_404(InvoiceTemplate, pk=pk, user__account=account) if account else get_object_or_404(InvoiceTemplate, pk=pk, user=request.user)
    
    # Count invoices (visible to user) using this template
    invoices_count = for_user_queryset(Invoice, request.user, request, account_lookup='account').filter(template=template).count()
    
    context = {
        'template': template,
        'invoices_count': invoices_count,
    }
    return render(request, 'invoices/template_detail.html', context)


@login_required
@permission_required('invoices.delete_invoicetemplate', raise_exception=True)
def template_delete(request, pk):
    """Delete template"""
    account = get_account_for_user(request.user)
    template = get_object_or_404(InvoiceTemplate, pk=pk, user__account=account) if account else get_object_or_404(InvoiceTemplate, pk=pk, user=request.user)
    
    if request.method == 'POST':
        # Check if any invoices (visible to user) use this template
        invoices_count = for_user_queryset(Invoice, request.user, request, account_lookup='account').filter(template=template).count()
        
        if invoices_count > 0:
            messages.warning(request, f'Cannot delete template "{template.name}" - it is used by {invoices_count} invoices.')
            return redirect('invoices:template_detail', pk=template.pk)
        
        template_name = template.name
        template.delete()
        messages.success(request, f'Template "{template_name}" deleted successfully!')
        return redirect('invoices:template_list')
    
    context = {'template': template}
    return render(request, 'invoices/template_delete.html', context)


@login_required
@permission_required('invoices.add_invoicetemplate', raise_exception=True)
def template_duplicate(request, pk):
    """Duplicate template"""
    account = get_account_for_user(request.user)
    template = get_object_or_404(InvoiceTemplate, pk=pk, user__account=account) if account else get_object_or_404(InvoiceTemplate, pk=pk, user=request.user)
    
    # Create duplicate
    new_template = InvoiceTemplate.objects.create(
        user=request.user,
        name=f"{template.name} (Copy)",
        description=template.description,
        primary_color=template.primary_color,
        secondary_color=template.secondary_color,
        text_color=template.text_color,
        accent_color=template.accent_color,
        show_company_logo=template.show_company_logo,
        show_company_details=template.show_company_details,
        show_bank_details=template.show_bank_details,
        show_signature=template.show_signature,
        document_title=template.document_title,
        number_prefix=template.number_prefix,
        default_payment_terms=template.default_payment_terms,
        footer_text=template.footer_text,
        is_default=False  # Copy is never default
    )
    
    messages.success(request, f'Template duplicated as "{new_template.name}"!')
    return redirect('invoices:template_edit', pk=new_template.pk)


@login_required
@permission_required('invoices.change_invoicetemplate', raise_exception=True)
def template_apply_to_all(request, pk):
    """Apply template colors to all invoices visible to user (admin: all; team member: own)"""
    account = get_account_for_user(request.user)
    template = get_object_or_404(InvoiceTemplate, pk=pk, user__account=account) if account else get_object_or_404(InvoiceTemplate, pk=pk, user=request.user)
    
    if request.method == 'POST':
        qs = for_user_queryset(Invoice, request.user, request, account_lookup='account')
        invoices_updated = qs.update(template=template, updated_at=template.updated_at)
        
        messages.success(request, f'Applied template "{template.name}" to all {invoices_updated} invoices!')
        return redirect('invoices:template_detail', pk=template.pk)
    
    # Get count for confirmation (visible to user only)
    total_invoices = for_user_queryset(Invoice, request.user, request, account_lookup='account').count()
    
    context = {
        'template': template,
        'total_invoices': total_invoices,
    }
    return render(request, 'invoices/template_apply_all.html', context)


@login_required
@permission_required('invoices.view_invoicetemplate', raise_exception=True)
def api_templates(request):
    """API endpoint to get user's invoice templates"""
    if request.method == 'GET':
        account = get_account_for_user(request.user)
        qs = InvoiceTemplate.objects.filter(user__account=account) if account else InvoiceTemplate.objects.filter(user=request.user)
        templates = qs.values(
            'id', 'name', 'primary_color', 'secondary_color', 
            'text_color', 'accent_color', 'is_default'
        )
        
        return JsonResponse({
            'templates': list(templates),
            'status': 'success'
        })
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required
@company_admin_or_permission_required('invoices.can_approve_invoice', raise_exception=True)
def invoice_update_status(request, pk):
    """Update invoice status via AJAX"""
    if request.method == 'POST':
        try:
            import json
            data = json.loads(request.body)
            status = data.get('status')
            
            logger.debug(f"Received status update request for invoice {pk}: {status}")
            
            # Validate status
            valid_statuses = ['unpaid', 'partial', 'paid', 'delivered']
            if status not in valid_statuses:
                logger.debug(f"Invalid status received: {status}")
                return JsonResponse({
                    'success': False,
                    'error': f'Invalid status. Must be one of: {", ".join(valid_statuses)}'
                })
            
            # Get invoice (per-team-member: only own or admin)
            qs = for_user_queryset(Invoice, request.user, request, account_lookup='account')
            invoice, response = get_object_or_unauthorized(request, qs, pk=pk)
            if response:
                return response
            old_status = invoice.status

            # Single source of truth: set amount_paid via model; save() runs calculate_totals() which
            # sets balance_due and derives status. This keeps DB and all calculations in sync.
            invoice.set_payment_status(status)

            try:
                invoice.save()
                logger.debug(f"Invoice {pk} save() completed")
            except Exception as save_error:
                logger.error(f"Save failed: {save_error}")
                return JsonResponse({
                    'success': False,
                    'error': f'Database save failed: {str(save_error)}'
                })

            invoice.refresh_from_db()
            actual_status = invoice.status

            # Status in DB is derived from amount_paid (e.g. if we zeroed payment for "Pending", status becomes "unpaid")
            return JsonResponse({
                'success': True,
                'message': f'Invoice updated from {old_status} to {actual_status}',
                'old_status': old_status,
                'new_status': actual_status
            })
            
        except Exception as e:
            logger.error(f"Exception in invoice_update_status: {str(e)}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required
@company_admin_or_permission_required('invoices.can_approve_invoice', raise_exception=True)
def invoice_toggle_payment(request, pk):
    """Toggle invoice payment status (for backward compatibility)"""
    if request.method == 'POST':
        try:
            import json
            data = json.loads(request.body)
            mark_as_paid = data.get('mark_as_paid', False)
            
            # Get invoice (per-team-member: only own or admin)
            qs = for_user_queryset(Invoice, request.user, request, account_lookup='account')
            invoice, response = get_object_or_unauthorized(request, qs, pk=pk)
            if response:
                return response
            # Use same logic as status dropdown: amount_paid is source of truth; status derived on save()
            invoice.set_payment_status('paid' if mark_as_paid else 'unpaid')
            invoice.save()
            invoice.refresh_from_db()
            return JsonResponse({
                'success': True,
                'message': f'Invoice marked as {"paid" if mark_as_paid else "unpaid"}',
                'new_status': invoice.status
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required
@company_admin_or_permission_required('invoices.download_invoice', raise_exception=True)
def export_excel(request):
    """Export invoices to Excel (per-team-member: only visible invoices)"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Invoices"
    headers = ["Invoice #", "Client", "Date", "Due Date", "Amount", "Status"]
    ws.append(headers)
    for invoice in for_user_queryset(Invoice, request.user, request, account_lookup='account'):
        ws.append([
            invoice.invoice_number,
            invoice.client_name,
            invoice.invoice_date.strftime("%Y-%m-%d") if invoice.invoice_date else "",
            invoice.due_date.strftime("%Y-%m-%d") if invoice.due_date else "",
            invoice.grand_total,
            invoice.get_status_display(),
        ])
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename=invoices.xlsx'
    wb.save(response)
    return response

@login_required
@company_admin_or_permission_required('invoices.download_invoice', raise_exception=True)
def export_pdf(request):
    invoices = get_filtered_invoices(request)
    company_profile = get_company_profile_for_user(request.user, request)
    company_logo_base64 = None
    if company_profile and company_profile.logo and hasattr(company_profile.logo, 'path') and os.path.isfile(company_profile.logo.path):
        try:
            with open(company_profile.logo.path, 'rb') as img_file:
                company_logo_base64 = 'data:image/png;base64,' + base64.b64encode(img_file.read()).decode('utf-8')
        except Exception:
            company_logo_base64 = None
    from apps.accounts.rbac import is_company_admin as _is_company_admin
    html_string = render_to_string('invoices/invoice_list_export_pdf.html', {
        'invoices': invoices,
        'company_profile': company_profile,
        'company_logo_base64': company_logo_base64,
        'is_company_admin': _is_company_admin(request),
    })
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename=invoices.pdf'
    pisa_status = pisa.CreatePDF(html_string, dest=response)
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html_string + '</pre>')
    return response


@login_required
@permission_required('invoices.view_invoice', raise_exception=True)
def export_report_pdf(request):
    """Export invoice report to PDF with charts and company details"""
    from xhtml2pdf import pisa
    from django.template.loader import render_to_string
    from django.db.models import Sum, Count, F, Value, DecimalField
    from django.db.models.functions import Coalesce, Least
    from django.utils import timezone
    from datetime import timedelta
    
    filter_type = (request.GET.get('filter') or 'month').strip().lower()
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    
    company_profile = get_company_profile_for_user(request.user, request)
    currency_symbol = (company_profile.currency_symbol or "₦") if company_profile else "₦"
    currency_code = (company_profile.currency_code or "NGN") if company_profile else "NGN"
    
    company_logo_base64 = None
    if company_profile and company_profile.logo and hasattr(company_profile.logo, 'path') and os.path.isfile(company_profile.logo.path):
        try:
            with open(company_profile.logo.path, 'rb') as img_file:
                company_logo_base64 = 'data:image/png;base64,' + base64.b64encode(img_file.read()).decode('utf-8')
        except Exception:
            company_logo_base64 = None
    
    base_qs = for_user_queryset(Invoice, request.user, request, account_lookup='account')
    base_qs = base_qs.annotate(
        rev_cap=Least(F('amount_paid'), F('grand_total')),
        effective_date=Coalesce('invoice_date', 'created_at__date')
    )
    
    today = timezone.now().date()
    
    if filter_type == 'today':
        date_from = today
        date_to = today
    elif filter_type == 'week':
        week_start = today - timedelta(days=today.weekday())
        date_from = week_start
        date_to = week_start + timedelta(days=6)
    elif filter_type == 'month':
        date_from = today.replace(day=1)
        next_month = today.replace(day=28) + timedelta(days=4)
        date_to = next_month.replace(day=1) - timedelta(days=1)
    elif filter_type == 'quarter':
        quarter = (today.month - 1) // 3
        q_start_month = quarter * 3 + 1
        date_from = today.replace(month=q_start_month, day=1)
        next_quarter = date_from + timedelta(days=90)
        date_to = (next_quarter.replace(day=1) - timedelta(days=1))
    elif filter_type == 'year':
        date_from = today.replace(month=1, day=1)
        date_to = today.replace(month=12, day=31)
    
    if date_from:
        try:
            if isinstance(date_from, str):
                date_from = timezone.datetime.strptime(date_from, '%Y-%m-%d').date()
            base_qs = base_qs.filter(effective_date__gte=date_from)
        except (ValueError, TypeError):
            pass
    
    if date_to:
        try:
            if isinstance(date_to, str):
                date_to = timezone.datetime.strptime(date_to, '%Y-%m-%d').date()
            base_qs = base_qs.filter(effective_date__lte=date_to)
        except (ValueError, TypeError):
            pass
    
    filtered_qs = base_qs
    
    total_invoices = filtered_qs.count()
    total_amount = filtered_qs.aggregate(total=Sum('grand_total'))['total'] or 0
    paid_amount = filtered_qs.aggregate(total=Sum('amount_paid'))['total'] or 0
    outstanding = filtered_qs.filter(balance_due__gt=0).aggregate(total=Sum('balance_due'))['total'] or 0
    revenue = filtered_qs.aggregate(total=Sum('rev_cap'))['total'] or 0
    
    status_breakdown = filtered_qs.values('status').annotate(
        count=Count('id'),
        total=Sum('grand_total')
    ).order_by('-count')
    
    status_data = []
    for item in status_breakdown:
        status_data.append({
            'status': item['status'],
            'count': item['count'],
            'total': float(item['total'] or 0)
        })
    
    client_breakdown = filtered_qs.values('client_name').annotate(
        invoice_count=Count('id'),
        total_amount=Sum('grand_total'),
        total_paid=Sum('amount_paid')
    ).order_by('-total_amount')[:10]
    
    client_data = []
    for item in client_breakdown:
        client_data.append({
            'client_name': item['client_name'] or 'Unknown',
            'invoice_count': item['invoice_count'],
            'total_amount': float(item['total_amount'] or 0),
            'total_paid': float(item['total_paid'] or 0)
        })
    
    daily_revenue = filtered_qs.filter(rev_cap__gt=0).values('effective_date').annotate(
        revenue=Sum('rev_cap'),
        count=Count('id')
    ).order_by('effective_date')[:30]
    
    daily_data = []
    for item in daily_revenue:
        daily_data.append({
            'date': str(item['effective_date']),
            'revenue': float(item['revenue'] or 0),
            'count': item['count']
        })
    
    recent_invoices = filtered_qs.select_related('created_by').order_by('-created_at')[:50]
    recent_data = []
    for inv in recent_invoices:
        recent_data.append({
            'invoice_number': inv.invoice_number or '',
            'client_name': inv.client_name or '',
            'invoice_date': inv.invoice_date.strftime('%Y-%m-%d') if inv.invoice_date else '',
            'grand_total': float(inv.grand_total or 0),
            'amount_paid': float(inv.amount_paid or 0),
            'balance_due': float(inv.balance_due or 0),
            'status': inv.status or 'unpaid',
        })
    
    avg_invoice_value = float(total_amount) / total_invoices if total_invoices > 0 else 0
    paid_percentage = (float(paid_amount) / float(total_amount) * 100) if total_amount > 0 else 0
    
    filter_labels = {
        'today': "Today",
        'week': "This Week",
        'month': "This Month",
        'quarter': "This Quarter",
        'year': "This Year",
        'custom': "Custom Range"
    }
    report_period = filter_labels.get(filter_type, "This Month")
    if date_from and date_to:
        report_period = f"{date_from} to {date_to}"
    
    context = {
        'company_profile': company_profile,
        'company_logo_base64': company_logo_base64,
        'currency_symbol': currency_symbol,
        'currency_code': currency_code,
        'report_period': report_period,
        'summary': {
            'total_invoices': total_invoices,
            'total_amount': float(total_amount),
            'paid_amount': float(paid_amount),
            'outstanding': float(outstanding),
            'revenue': float(revenue),
            'avg_invoice_value': float(avg_invoice_value),
            'paid_percentage': float(paid_percentage),
        },
        'status_breakdown': status_data,
        'client_breakdown': client_data,
        'daily_revenue': daily_data,
        'recent_invoices': recent_data,
    }
    
    html_string = render_to_string('invoices/report_pdf.html', context)
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename=Invoice_Report_{report_period.replace(" ", "_")}.pdf'
    pisa_status = pisa.CreatePDF(html_string, dest=response)
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html_string + '</pre>')
    return response


def _invoice_report_context(request, invoice, movements, filters):
    """Build context dict shared by the report view and AJAX refresh."""
    def _fmt(num):
        """Format numbers with thousands separators, preserving decimals."""
        try:
            return f'{float(num):,.15g}'
        except Exception:
            return f'{float(num):g}'
    
    status_display_map = {
        'unpaid': 'Not Paid',
        'partial': 'Partially Paid',
        'paid': 'Paid',
        'delivered': 'Delivered',
    }
    
    return {
        'invoice': invoice,
        'movements': movements,
        'search': filters.get('search', ''),
        'status_filter': filters.get('status', ''),
        'date_from': filters.get('date_from', ''),
        'date_to': filters.get('date_to', ''),
        'current_client_name': invoice.client_name or '',
        'current_client_phone': invoice.client_phone or '',
        'current_client_email': invoice.client_email or '',
        'current_subtotal': invoice.subtotal or 0,
        'current_total_tax': invoice.total_tax or 0,
        'current_total_discount': invoice.total_discount or 0,
        'current_shipping_fee': invoice.shipping_fee or 0,
        'current_other_charges': invoice.other_charges or 0,
        'current_grand_total': invoice.grand_total or 0,
        'current_amount_paid': invoice.amount_paid or 0,
        'current_balance_due': invoice.balance_due or 0,
        'current_status': invoice.status or 'unpaid',
        'current_status_display': status_display_map.get(invoice.status, invoice.get_status_display() if hasattr(invoice, 'get_status_display') else invoice.status or 'unpaid'),
        'current_notes': invoice.notes or '',
        'fmt': _fmt,
        'status_display_map': status_display_map,
    }


@login_required
@permission_required('invoices.view_invoice', raise_exception=True)
@never_cache
def invoice_product_report(request, pk):
    """Invoice ledger / report: full movement history for one invoice record."""
    from apps.core.ownership import for_user_queryset
    from .models import InvoiceMovement

    try:
        invoice = get_object_or_404(
            for_user_queryset(Invoice, request.user, request, account_lookup='account'),
            pk=pk,
        )
    except Http404:
        return render(request, 'invoices/invoice_report_404.html', {
            'invoice_id': pk,
        }, status=404)

    movements = (
        invoice.movements.all()
        .only(
            'id',
            'invoice_id',
            'created_at',
            'created_by_id',
            'client_name',
            'client_phone',
            'client_email',
            'subtotal',
            'total_tax',
            'total_discount',
            'shipping_fee',
            'other_charges',
            'grand_total',
            'amount_paid',
            'balance_due',
            'status',
            'notes',
            'items_snapshot',
        )
        .order_by('-created_at', '-pk')
    )

    filters = {
        'search': (request.GET.get('search') or '').strip(),
        'status': (request.GET.get('status') or '').strip(),
        'date_from': (request.GET.get('date_from') or '').strip(),
        'date_to': (request.GET.get('date_to') or '').strip(),
    }

    if filters['status'] and filters['status'] in dict(Invoice.STATUS_CHOICES):
        movements = movements.filter(status=filters['status'])
    if filters['date_from']:
        movements = movements.filter(created_at__date__gte=filters['date_from'])
    if filters['date_to']:
        movements = movements.filter(created_at__date__lte=filters['date_to'])
    if filters['search']:
        terms = [t.strip() for t in filters['search'].split() if t.strip()]
        if not terms:
            terms = [filters['search']]
        for term in terms:
            movements = movements.filter(
                Q(notes__icontains=term)
                | Q(client_name__icontains=term)
                | Q(client_email__icontains=term)
                | Q(status__icontains=term)
            )

    paginator = Paginator(movements, 100)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    movements_page = page_obj.object_list

    get_copy = request.GET.copy()
    if 'page' in get_copy:
        get_copy.pop('page', None)
    pagination_base_query = get_copy.urlencode()

    company = get_company_profile_for_user(request.user, request)
    currency_symbol = getattr(company, 'currency_symbol', '₦') if company else '₦'

    user_ids = {m.created_by_id for m in movements_page if m.created_by_id}
    if user_ids:
        from django.db.models import Value
        from django.db.models.functions import Concat
        from apps.accounts.models import User
        user_map = {
            u.pk: f"{u.first_name} {u.last_name}".strip() or u.email
            for u in User.objects.filter(pk__in=user_ids)
        }
        for m in movements_page:
            m.created_by_name = user_map.get(m.created_by_id, '—')
    else:
        for m in movements_page:
            m.created_by_name = '—'

    context = _invoice_report_context(request, invoice, movements_page, filters)
    context.update({
        'page_obj': page_obj,
        'pagination_base_query': pagination_base_query,
        'status_choices': Invoice.STATUS_CHOICES,
        'user_currency_symbol': currency_symbol,
    })

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' and request.GET.get('format') == 'json':
        rows_html = render_to_string(
            'invoices/invoice_product_report_rows_partial.html',
            context,
            request=request,
        )
        resp = JsonResponse({
            'rows_html': rows_html,
            'current_client_name': invoice.client_name or '',
            'current_client_phone': invoice.client_phone or '',
            'current_client_email': invoice.client_email or '',
            'current_subtotal': str(invoice.subtotal or 0),
            'current_total_tax': str(invoice.total_tax or 0),
            'current_total_discount': str(invoice.total_discount or 0),
            'current_shipping_fee': str(invoice.shipping_fee or 0),
            'current_other_charges': str(invoice.other_charges or 0),
            'current_grand_total': str(invoice.grand_total or 0),
            'current_amount_paid': str(invoice.amount_paid or 0),
            'current_balance_due': str(invoice.balance_due or 0),
            'current_status': invoice.status or 'unpaid',
            'current_notes': invoice.notes or '',
            'invoice_number': invoice.invoice_number,
            'status_choices': list(Invoice.STATUS_CHOICES),
            'status_display_map': {
                'unpaid': 'Not Paid',
                'partial': 'Partially Paid',
                'paid': 'Paid',
                'delivered': 'Delivered',
            },
        })
        apply_no_cache_headers(resp)
        return resp

    response = render(request, 'invoices/invoice_product_report.html', context)
    apply_no_cache_headers(response)
    return response
