# -*- coding: utf-8 -*-
from django.shortcuts import render, get_object_or_404, redirect
from business_app.views import get_object_or_unauthorized
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from apps.core.permissions import company_admin_or_permission_required
from django.db.models import Q, F, Sum, Count, Case, When, Value
from django.db.models.functions import Least
from django.db.models.fields import DecimalField
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta
from .models import Invoice, InvoiceItem, InvoiceTemplate, safe_decimal_for_db
from .forms import InvoiceForm, InvoiceItemFormSet, InvoiceFilterForm, InvoiceTemplateForm
# from apps.core.utils import generate_pdf_response
import openpyxl
from django.template.loader import render_to_string
from xhtml2pdf import pisa
from django.template.loader import render_to_string
from django.http import HttpResponse
from apps.core.models import CompanyProfile
from apps.core.utils import get_company_profile_for_user, get_account_users_for_filter, get_revenue_period_boundaries
from apps.core.ownership import for_user_queryset
import os
import urllib.parse
import base64
import sys
import logging

logger = logging.getLogger(__name__)


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

@login_required
@permission_required('invoices.view_invoice', raise_exception=True)
@never_cache
def invoice_list(request):
    """List all invoices. Never cached so deletes/creates show immediately."""
    invoices = get_filtered_invoices(request)
    filter_form = InvoiceFilterForm(request.GET)
    paginator = Paginator(invoices, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
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
    periods = get_revenue_period_boundaries()
    base_capped = for_user_queryset(Invoice, request.user, request, account_lookup='account').annotate(
        rev_cap=Least(F('amount_paid'), F('grand_total'))
    )
    period_agg = base_capped.aggregate(
        rev_today=Sum(Case(When(invoice_date=periods['today'], then=F('rev_cap')), default=Value(Decimal('0')), output_field=DecimalField())),
        rev_week=Sum(Case(When(invoice_date__gte=periods['week_start'], invoice_date__lte=periods['week_end'], then=F('rev_cap')), default=Value(Decimal('0')), output_field=DecimalField())),
        rev_month=Sum(Case(When(invoice_date__gte=periods['start_of_month'], invoice_date__lte=periods['end_of_month'], then=F('rev_cap')), default=Value(Decimal('0')), output_field=DecimalField())),
        rev_quarter=Sum(Case(When(invoice_date__gte=periods['quarter_start'], invoice_date__lte=periods['quarter_end'], then=F('rev_cap')), default=Value(Decimal('0')), output_field=DecimalField())),
        rev_year=Sum(Case(When(invoice_date__gte=periods['year_start'], invoice_date__lte=periods['year_end'], then=F('rev_cap')), default=Value(Decimal('0')), output_field=DecimalField())),
    )
    rev_today = period_agg.get('rev_today') or 0
    rev_week = period_agg.get('rev_week') or 0
    rev_month = period_agg.get('rev_month') or 0
    rev_quarter = period_agg.get('rev_quarter') or 0
    rev_year = period_agg.get('rev_year') or 0
    if getattr(request.user, 'account_id', None):
        current_template = InvoiceTemplate.objects.filter(user__account=request.user.account, is_default=True).first()
        if not current_template:
            current_template = InvoiceTemplate.objects.filter(user__account=request.user.account).first()
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
    
    from apps.accounts.rbac import is_company_admin as _is_company_admin
    account_users = get_account_users_for_filter(request.user) if _is_company_admin(request) else []
    if _is_company_admin(request):
        filter_form.fields['created_by'].queryset = account_users
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
        'current_template': current_template,
        'account_users': account_users,
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
    from apps.accounts.rbac import is_company_admin as _is_company_admin
    show_created_by = _is_company_admin(request)

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
    account_id = getattr(user, 'account_id', None)
    if account_id:
        current_template = InvoiceTemplate.objects.filter(user__account_id=account_id, is_default=True).first()
        if not current_template:
            current_template = InvoiceTemplate.objects.filter(user__account_id=account_id).first()
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
    
    # Get currency symbol
    currency_symbol = getattr(company_profile, 'currency_symbol', '₦') if company_profile else '₦'
    
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
    qs = for_user_queryset(Invoice, request.user, request, account_lookup='account').select_related('user', 'created_by').prefetch_related('items')
    invoice, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return response
    context = get_invoice_context(invoice, request.user, request)
    return render(request, 'invoices/invoice_detail.html', context)


@login_required
@permission_required('invoices.add_invoice', raise_exception=True)
def invoice_create(request):
    """Create new invoice with dynamic preview"""
    if request.method == 'POST':
        # Handle dynamic form data
        invoice = Invoice(user=request.user)
        
        # Set basic invoice fields
        invoice.client_name = request.POST.get('client_name', '')
        invoice.client_email = request.POST.get('client_email', '')
        invoice.client_phone = request.POST.get('client_phone', '')
        invoice.client_address = request.POST.get('client_address', '')
        
        # Handle invoice_date - convert empty string to None for proper date handling
        invoice_date = request.POST.get('invoice_date')
        invoice.invoice_date = invoice_date if invoice_date and invoice_date.strip() else None
        
        # Handle due_date - convert empty string to None for proper date handling
        due_date = request.POST.get('due_date')
        invoice.due_date = due_date if due_date and due_date.strip() else None
        
        invoice.notes = request.POST.get('notes', '')
        
        # Parse financial fields with smart number parsing and type detection
        tax_input = request.POST.get('tax_rate', '0')
        discount_input = request.POST.get('discount', '0')
        tax_type = request.POST.get('tax_type', 'percentage')
        discount_type = request.POST.get('discount_type', 'percentage')
        
        # Parse tax with type detection
        _, detected_tax_type, tax_value = Invoice.parse_number_with_type(tax_input)
        if '%' in str(tax_input):
            tax_type = 'percentage'
        
        # Parse discount with type detection
        _, detected_discount_type, discount_value = Invoice.parse_number_with_type(discount_input)
        if '%' in str(discount_input):
            discount_type = 'percentage'
        
        shipping_fee = Invoice.parse_number(request.POST.get('shipping_fee', '0'))
        other_charges = Invoice.parse_number(request.POST.get('other_charges', '0'))
        amount_paid = Invoice.parse_number(request.POST.get('amount_paid', '0'))
        
        # Store values and types for calculation
        invoice.tax_type = tax_type
        invoice.tax_value = tax_value
        invoice.discount_type = discount_type
        invoice.discount_value = discount_value
        
        # For backward compatibility, also set the legacy attributes
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
        
        # Handle template selection
        template_id = request.POST.get('template')
        if template_id:
            try:
                template = InvoiceTemplate.objects.get(id=template_id, user__account=request.user.account)
                invoice.template = template
            except InvoiceTemplate.DoesNotExist:
                pass
        else:
            # Use default template if no template selected
            default_template = InvoiceTemplate.objects.filter(user__account=request.user.account, is_default=True).first() if getattr(request.user, 'account_id', None) else InvoiceTemplate.objects.filter(user=request.user, is_default=True).first()
            if default_template:
                invoice.template = default_template
        
        # Handle display settings toggles (per-invoice settings)
        # Default to True (show bank details and signature) unless explicitly unchecked
        # If the hidden field 'display_settings_submitted' is present, use checkbox values
        # Otherwise, default to True for new invoices
        if 'display_settings_submitted' in request.POST:
            invoice.show_bank_details = 'show_bank_details' in request.POST or request.POST.get('show_bank_details') == 'on'
            invoice.show_signature = 'show_signature' in request.POST or request.POST.get('show_signature') == 'on'
        else:
            # Default to True for new invoices
            invoice.show_bank_details = True
            invoice.show_signature = True
        
        # Save invoice first to get an ID
        invoice.save()
        
        # Process dynamic items
        subtotal = 0
        items_data = {}
        
        # Collect all item data from POST
        for key, value in request.POST.items():
            if key.startswith('items[') and '][' in key:
                # Parse items[1][description] format
                item_index = key.split('[')[1].split(']')[0]
                field_name = key.split('[')[2].split(']')[0]
                
                if item_index not in items_data:
                    items_data[item_index] = {}
                items_data[item_index][field_name] = value
        
        # Create invoice items
        created_items = []
        for index, item_data in items_data.items():
            # Get all item fields
            product_service = item_data.get('product_service', '').strip()
            description = item_data.get('description', '').strip()
            quantity = item_data.get('quantity', '').strip()
            unit_price = item_data.get('unit_price', '').strip()
            
            # Create item if we have ANY field filled (product_service, description, quantity, or price)
            # All fields are optional - save the item if any data is present
            if product_service or description or quantity or unit_price:
                # Debug logging
                logger.debug(f"Creating item - product_service: {product_service!r}, description: {description!r}, qty: {quantity!r}, price: {unit_price!r}")
                
                # Ensure we save the text content properly
                parsed_quantity = Invoice.parse_number(quantity or '0')
                parsed_price = Invoice.parse_number(unit_price or '0')
                # Ensure decimals are valid for DB (no NaN/Infinity, quantized to 2 places)
                safe_quantity = safe_decimal_for_db(parsed_quantity, 2)
                safe_unit_price = safe_decimal_for_db(parsed_price, 2)

                item = InvoiceItem.objects.create(
                    invoice=invoice,
                    product_service=product_service or '',
                    description=description or '',
                    quantity=safe_quantity,
                    quantity_display=quantity or '',
                    unit_price=safe_unit_price
                )
                subtotal += item.line_total
                
                # Debug logging
                logger.debug(f"Saved item - ID: {item.id}, product_service: {item.product_service!r}, description: {item.description!r}, qty: {item.quantity}, price: {item.unit_price}, total: {item.line_total}")
        
        # Update invoice with calculated subtotal and totals
        invoice.subtotal = subtotal
        invoice.calculate_totals()
        invoice.save()
        
        messages.success(request, f'Invoice {invoice.invoice_number} created successfully!')
        return redirect('invoices:detail', pk=invoice.pk)
    
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
    if getattr(request.user, 'account_id', None):
        templates = InvoiceTemplate.objects.filter(user__account=request.user.account)
    else:
        templates = InvoiceTemplate.objects.filter(user=request.user)
    default_template = templates.filter(is_default=True).first()
    
    if not templates.exists():
        default_template = InvoiceTemplate.objects.create(
            user=request.user,
            name="My First Invoice Template",
            description="Automatically created default template with standard colors",
            is_default=True
        )
        if getattr(request.user, 'account_id', None):
            templates = InvoiceTemplate.objects.filter(user__account=request.user.account)
        else:
            templates = InvoiceTemplate.objects.filter(user=request.user)
    
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
        
        # Debug: Show what we received
        logger.debug(f"Form valid: {form.is_valid()}")
        logger.debug(f"Formset valid: {formset.is_valid()}")
        
        if not form.is_valid():
            logger.debug(f"Form errors: {form.errors}")
        if not formset.is_valid():
            logger.debug(f"Formset errors: {formset.errors}")
            logger.debug(f"Formset non-form errors: {formset.non_form_errors()}")
        
        if form.is_valid() and formset.is_valid():
            # Save the main form first
            invoice = form.save()

            # Completely rebuild the invoice items from the cleaned formset data.
            # This avoids any hidden validators or formset quirks and ensures that
            # both positive and negative values are preserved exactly as entered.
            logger.debug(f"Rebuilding items for invoice {invoice.invoice_number}")
            invoice.items.all().delete()

            from decimal import Decimal
            subtotal = Decimal("0")
            valid_items = []

            for i, item_form in enumerate(formset.forms):
                if not hasattr(item_form, "cleaned_data"):
                    continue

                data = item_form.cleaned_data

                # Skip forms explicitly marked for deletion
                if data.get("DELETE"):
                    logger.debug(f"Skipping deleted form {i+1}")
                    continue

                product_service = (data.get("product_service") or "").strip()
                description = (data.get("description") or "").strip()
                quantity = safe_decimal_for_db(data.get("quantity") or Decimal("0"), 2)
                unit_price = safe_decimal_for_db(data.get("unit_price") or Decimal("0"), 2)
                quantity_display = (data.get("quantity_display") or "").strip() or str(quantity)

                # Skip rows that are truly empty
                if not (product_service or description or quantity or unit_price):
                    logger.debug(f"Skipping empty form {i+1}")
                    continue

                item = InvoiceItem.objects.create(
                    invoice=invoice,
                    product_service=product_service,
                    description=description,
                    quantity=quantity,
                    quantity_display=quantity_display,
                    unit_price=unit_price,
                )
                subtotal += item.line_total
                valid_items.append(item)
                logger.debug(
                    f"Saved item {i+1}: {item.product_service!r} - "
                    f"Qty: {item.quantity} - Price: {item.unit_price} - Total: {item.line_total}"
                )

            logger.debug(f"Valid items saved: {len(valid_items)}; subtotal={subtotal}")

            # Update subtotal before recalculating totals
            invoice.subtotal = subtotal
            
            # Handle flexible tax and discount calculation (percentage or fixed)
            from decimal import Decimal
            tax_value = Decimal(str(form.cleaned_data.get('total_tax', 0)))
            discount_value = Decimal(str(form.cleaned_data.get('total_discount', 0)))
            
            # Get types from form (auto-detected in clean methods or from selector)
            tax_type = form.cleaned_data.get('tax_type', 'percentage')
            discount_type = form.cleaned_data.get('discount_type', 'percentage')
            
            # Store values and types
            invoice.tax_type = tax_type
            invoice.tax_value = tax_value
            invoice.discount_type = discount_type
            invoice.discount_value = discount_value
            
            # For backward compatibility with calculate_totals
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
            
            # Store other financial fields
            invoice.shipping_fee = form.cleaned_data.get('shipping_fee', 0)
            invoice.other_charges = form.cleaned_data.get('other_charges', 0)
            invoice.amount_paid = form.cleaned_data.get('amount_paid', 0)
            
            # Handle display settings toggles (per-invoice settings)
            # Only update if display_settings_submitted is in POST (meaning form has the toggles)
            if 'display_settings_submitted' in request.POST:
                invoice.show_bank_details = 'showBankDetails' in request.POST or request.POST.get('showBankDetails') == 'on'
                invoice.show_signature = 'showSignature' in request.POST or request.POST.get('showSignature') == 'on'
            
            # Recalculate all totals
            invoice.calculate_totals()
            invoice.save()
            
            logger.debug(f"Final invoice totals - Subtotal: {invoice.subtotal}, Tax: {invoice.total_tax}, Discount: {invoice.total_discount}, Grand Total: {invoice.grand_total}")
            
            messages.success(request, f'Invoice {invoice.invoice_number} updated successfully!')
            return redirect('invoices:detail', pk=invoice.pk)
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
                            for error in errors:
                                messages.error(request, f'Error in item {i+1} {field}: {error}')
                for error in formset.non_form_errors():
                    messages.error(request, f'Formset error: {error}')
    else:
        form = InvoiceForm(instance=invoice, user=request.user)
        formset = InvoiceItemFormSet(instance=invoice)
        
        # Set discount and tax types and values for display
        form.initial['tax_type'] = invoice.tax_type or 'percentage'
        form.initial['discount_type'] = invoice.discount_type or 'percentage'
        
        # Display the stored value (percentage number or fixed amount)
        if invoice.tax_value:
            form.initial['total_tax'] = invoice.tax_value
        elif invoice.subtotal and invoice.subtotal > 0 and invoice.total_tax > 0:
            # Backward compatibility: calculate percentage from amount
            tax_percentage = (invoice.total_tax / invoice.subtotal) * 100
            form.initial['total_tax'] = round(tax_percentage, 2)
        
        if invoice.discount_value:
            form.initial['total_discount'] = invoice.discount_value
        elif invoice.subtotal and invoice.subtotal > 0 and invoice.total_discount > 0:
            # Backward compatibility: calculate percentage from amount
            discount_percentage = (invoice.total_discount / invoice.subtotal) * 100
            form.initial['total_discount'] = round(discount_percentage, 2)
        
        # Debug: Show invoice data being loaded
        logger.debug(f"Loading invoice {invoice.invoice_number} with {invoice.items.count()} items")
        for item in invoice.items.all():
            logger.debug(f"  Item: {item.product_service!r} - Qty: {item.quantity} - Price: {item.unit_price}")
    
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
    templates = InvoiceTemplate.objects.filter(user__account=request.user.account).select_related('user') if getattr(request.user, 'account_id', None) else InvoiceTemplate.objects.filter(user=request.user).select_related('user')
    
    context = {
        'templates': templates,
    }
    return render(request, 'invoices/template_list.html', context)


@login_required
@permission_required('invoices.add_invoicetemplate', raise_exception=True)
def template_create(request):
    """Create new invoice template"""
    if request.method == 'POST':
        form = InvoiceTemplateForm(request.POST, user=request.user)
        if form.is_valid():
            template = form.save(commit=False)
            template.user = request.user
            
            # Check if template name already exists for this user
            if InvoiceTemplate.objects.filter(user__account=request.user.account, name=template.name).exclude(pk=template.pk).exists() if getattr(request.user, 'account_id', None) else InvoiceTemplate.objects.filter(user=request.user, name=template.name).exclude(pk=template.pk).exists():
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
    template = get_object_or_404(InvoiceTemplate, pk=pk, user__account=request.user.account)
    
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
    template = get_object_or_404(InvoiceTemplate, pk=pk, user__account=request.user.account)
    
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
    template = get_object_or_404(InvoiceTemplate, pk=pk, user__account=request.user.account)
    
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
    template = get_object_or_404(InvoiceTemplate, pk=pk, user__account=request.user.account)
    
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
    template = get_object_or_404(InvoiceTemplate, pk=pk, user__account=request.user.account)
    
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
        qs = InvoiceTemplate.objects.filter(user__account=request.user.account) if getattr(request.user, 'account_id', None) else InvoiceTemplate.objects.filter(user=request.user)
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
