"""
Phase 3 — Server-side aggregation.
Centralize dashboard metrics: totals, counts, sums, statuses.
Return exact values from DB; no cached approximations.
When user is provided and not company admin, metrics are restricted to that user's
own records (per-team-member isolation). When user is None or is admin, account-wide.
"""
from decimal import Decimal
from django.db.models import Sum, Count, F, Case, When, Value
from django.db.models.functions import Least
from django.db.models.fields import DecimalField
from django.utils import timezone
from datetime import timedelta, date as date_type

from apps.core.ownership import for_user_queryset, is_company_admin
from apps.core.utils import get_revenue_period_boundaries


def get_account_id_from_instance(instance):
    """
    Resolve account_id for scoping. Used by emitter to target the right channel.
    - Models with account FK (Employee, Department, LeaveRequest, etc.): instance.account_id
    - Models with company FK (CompanyProfile): company.account_id
    - Models with user FK: user.account_id
    """
    if instance is None:
        return None
    # Account-scoped (HR Employee, Department, LeaveRequest, etc.)
    if hasattr(instance, 'account_id') and getattr(instance, 'account_id', None):
        return instance.account_id
    # CompanyProfile / Expense-style (company FK)
    if hasattr(instance, 'company_id') and getattr(instance, 'company_id', None):
        try:
            company = getattr(instance, 'company', None)
            if company and getattr(company, 'account_id', None):
                return company.account_id
        except Exception:
            pass
    # User-scoped (Invoice, Quotation, Waybill, Receipt, Job Order Product, InventoryItem)
    for attr in ('user_id', 'created_by_id'):
        if hasattr(instance, attr):
            user_id = getattr(instance, attr, None)
            if not user_id:
                continue
            try:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                user = User.objects.filter(pk=user_id).values_list('account_id', flat=True).first()
                if user:
                    return user
            except Exception:
                pass
    # Receipt: can also use invoice.user
    if hasattr(instance, 'invoice_id') and getattr(instance, 'invoice_id', None):
        try:
            from apps.invoices.models import Invoice
            inv = Invoice.objects.filter(pk=instance.invoice_id).values_list('user_id', flat=True).first()
            if inv:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                acc = User.objects.filter(pk=inv).values_list('account_id', flat=True).first()
                if acc:
                    return acc
        except Exception:
            pass
    return None


def aggregate_dashboard(account_id, user=None):
    """
    Compute dashboard metrics for an account (exact DB values).
    If user is provided and not company admin, metrics are restricted to that user's records.
    If user is None or is company admin, returns account-wide metrics.
    Used after model change (emitter, no user) or for WebSocket initial/update (consumer passes user).
    """
    if not account_id:
        return {}
    from django.contrib.auth import get_user_model
    User = get_user_model()
    # Revenue periods with strict boundaries (week=Mon–Sun, month, quarter, year).
    periods = get_revenue_period_boundaries()
    today = periods['today']

    # request=None in aggregation context; is_company_admin(user, None) is False → team member sees own only
    use_visibility = user is not None and not is_company_admin(user, None)

    def _invoice_qs():
        from apps.invoices.models import Invoice
        if use_visibility:
            return for_user_queryset(Invoice, user, None, account_lookup='account')
        return Invoice.objects.filter(user__account_id=account_id)
    invoices = _invoice_qs()
    inv_totals = invoices.aggregate(
        total_count=Count('id'),
        total_amount=Sum('grand_total'),
        paid_amount=Sum('amount_paid'),
    )
    # Outstanding = what customers still owe (positive balance_due). Refund = what we owe (overpayments).
    outstanding = invoices.aggregate(
        s=Sum(Case(When(balance_due__gt=0, then=F('balance_due')), default=Value(Decimal('0')), output_field=DecimalField()))
    )['s'] or 0
    refund_due = invoices.aggregate(
        s=Sum(Case(When(amount_paid__gt=F('grand_total'), then=F('amount_paid') - F('grand_total')), default=Value(Decimal('0')), output_field=DecimalField()))
    )['s'] or 0
    # Revenue = earned only (cap at grand_total per invoice; overpayment does not inflate revenue)
    invoices_capped = invoices.annotate(rev_cap=Least(F('amount_paid'), F('grand_total')))
    revenue_generated = invoices_capped.aggregate(s=Sum('rev_cap'))['s'] or 0
    monthly_inv = invoices.filter(
        invoice_date__gte=periods['start_of_month'],
        invoice_date__lte=periods['end_of_month']
    )
    monthly_revenue = monthly_inv.aggregate(t=Sum('grand_total'))['t'] or 0
    today_inv = invoices.filter(invoice_date=today)
    rev_today = invoices_capped.filter(invoice_date=today).aggregate(s=Sum('rev_cap'))['s'] or 0
    rev_week = invoices_capped.filter(
        invoice_date__gte=periods['week_start'],
        invoice_date__lte=periods['week_end']
    ).aggregate(s=Sum('rev_cap'))['s'] or 0
    rev_month = invoices_capped.filter(
        invoice_date__gte=periods['start_of_month'],
        invoice_date__lte=periods['end_of_month']
    ).aggregate(s=Sum('rev_cap'))['s'] or 0
    rev_quarter = invoices_capped.filter(
        invoice_date__gte=periods['quarter_start'],
        invoice_date__lte=periods['quarter_end']
    ).aggregate(s=Sum('rev_cap'))['s'] or 0
    rev_year = invoices_capped.filter(
        invoice_date__gte=periods['year_start'],
        invoice_date__lte=periods['year_end']
    ).aggregate(s=Sum('rev_cap'))['s'] or 0

    # Quotations
    from apps.quotations.models import Quotation
    if use_visibility:
        quotations = for_user_queryset(Quotation, user, None, account_lookup='account')
    else:
        quotations = Quotation.objects.filter(user__account_id=account_id)
    quo_totals = quotations.aggregate(total_count=Count('id'), total_value=Sum('grand_total'))
    quo_by_status = dict(quotations.values_list('status').annotate(c=Count('id')).values_list('status', 'c'))

    # Waybills
    from apps.waybills.models import Waybill
    if use_visibility:
        waybills = for_user_queryset(Waybill, user, None, account_lookup='account')
    else:
        waybills = Waybill.objects.filter(user__account_id=account_id)
    wb_totals = waybills.aggregate(total_count=Count('id'))
    wb_by_status = dict(waybills.values_list('status').annotate(c=Count('id')).values_list('status', 'c'))

    # Receipts
    from apps.receipts.models import Receipt
    if use_visibility:
        receipts = for_user_queryset(Receipt, user, None, account_lookup='account')
    else:
        receipts = Receipt.objects.filter(created_by__account_id=account_id)
    rec_today = receipts.filter(date_received=today).aggregate(s=Sum('amount_received'))['s'] or 0
    rec_week = receipts.filter(date_received__gte=periods['week_start']).aggregate(s=Sum('amount_received'))['s'] or 0
    rec_month = receipts.filter(date_received__gte=periods['start_of_month']).aggregate(s=Sum('amount_received'))['s'] or 0

    # Clients
    from apps.clients.models import Client
    if use_visibility:
        clients = for_user_queryset(Client, user, None, account_lookup='company__account')
    else:
        try:
            clients = Client.objects.filter(company__account_id=account_id)
        except Exception:
            clients = Client.objects.filter(created_by__account_id=account_id)
    clients_total = clients.count()
    clients_active = clients.filter(is_active=True).count() if hasattr(Client, 'is_active') else clients_total
    from datetime import timedelta as td
    recent_clients = clients.filter(created_at__gte=timezone.now() - td(days=30)).count()

    # Job orders (Product)
    from apps.job_orders.models import Product
    if use_visibility:
        products = for_user_queryset(Product, user, None, account_lookup='account')
    else:
        products = Product.objects.filter(created_by__account_id=account_id)
    total_products = products.count()
    pending_orders = products.filter(approval_status='pending').count()

    # Inventory (company-scoped; filter by account)
    try:
        from apps.inventory.models import Inventory
        if use_visibility:
            inv_items = Inventory.objects.filter(created_by=user)
        else:
            inv_items = Inventory.objects.filter(account_id=account_id)
        inventory_total = inv_items.count()
    except Exception:
        inventory_total = 0

    # Invoice / Quotation / Waybill templates (user__account or user when use_visibility)
    from apps.invoices.models import InvoiceTemplate
    from apps.quotations.models import QuotationTemplate
    from apps.waybills.models import WaybillTemplate
    if use_visibility:
        inv_tpl_count = InvoiceTemplate.objects.filter(user=user).count()
        quo_tpl_count = QuotationTemplate.objects.filter(user=user).count()
        wb_tpl_count = WaybillTemplate.objects.filter(user=user).count()
    else:
        inv_tpl_count = InvoiceTemplate.objects.filter(user__account_id=account_id).count()
        quo_tpl_count = QuotationTemplate.objects.filter(user__account_id=account_id).count()
        wb_tpl_count = WaybillTemplate.objects.filter(user__account_id=account_id).count()

    def dec(v):
        if v is None:
            return 0
        return float(v) if isinstance(v, (Decimal, int, float)) else 0

    return {
        'core': {
            'total_invoices': inv_totals['total_count'] or 0,
            'total_quotations': quo_totals['total_count'] or 0,
            'total_waybills': wb_totals['total_count'] or 0,
            'total_clients': clients_total,
            'active_clients': clients_active,
            'recent_clients_30': recent_clients,
            'monthly_revenue': dec(monthly_revenue),
            'today_revenue': dec(today_inv.aggregate(t=Sum('grand_total'))['t']),
            'outstanding_invoices': dec(outstanding),
            'monthly_invoice_count': monthly_inv.count(),
            'today_invoice_count': today_inv.count(),
        },
        'invoice': {
            'total_count': inv_totals['total_count'] or 0,
            'total_amount': dec(inv_totals['total_amount']),
            'paid_amount': dec(inv_totals['paid_amount']),
            'revenue_generated': dec(revenue_generated),
            'outstanding': dec(outstanding),
            'refund_due': dec(refund_due),
            'revenue_today': dec(rev_today),
            'revenue_week': dec(rev_week),
            'revenue_month': dec(rev_month),
            'revenue_quarter': dec(rev_quarter),
            'revenue_year': dec(rev_year),
        },
        'quotation': {
            'total_count': quo_totals['total_count'] or 0,
            'total_value': dec(quo_totals['total_value']),
            'sent': quo_by_status.get('sent', 0),
            'accepted': quo_by_status.get('accepted', 0),
            'drafts': quo_by_status.get('draft', 0),
        },
        'waybill': {
            'total_count': wb_totals['total_count'] or 0,
            'pending': wb_by_status.get('pending', 0),
            'in_transit': wb_by_status.get('dispatched', 0) + wb_by_status.get('processing', 0),
            'delivered': wb_by_status.get('delivered', 0),
        },
        'receipt': {
            'total_today': dec(rec_today),
            'total_week': dec(rec_week),
            'total_month': dec(rec_month),
        },
        'job_order': {
            'total_products': total_products,
            'total_orders': total_products,
            'pending_orders': pending_orders,
            'active_customers': len(set(products.values_list('organization_name', flat=True))) if total_products else 0,
        },
        'inventory': {
            'total_products': inventory_total,
            'total_count': inventory_total,
        },
        'client': {
            'total_clients': clients_total,
            'active_clients': clients_active,
            'recent_30': recent_clients,
            'total_quotations': quo_totals['total_count'] or 0,
        },
        'templates': {
            'invoice_templates': inv_tpl_count,
            'quotation_templates': quo_tpl_count,
            'waybill_templates': wb_tpl_count,
        },
    }
