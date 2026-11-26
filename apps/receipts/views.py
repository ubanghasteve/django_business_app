from django.shortcuts import render, get_object_or_404, redirect
from business_app.views import get_object_or_unauthorized
from django.contrib.auth.decorators import login_required, permission_required
from django.views.decorators.cache import never_cache
from apps.core.permissions import company_admin_or_permission_required
from django.contrib import messages
from django.urls import reverse
from django.http import HttpResponse, HttpResponseForbidden
from .models import Receipt
from .forms import ReceiptForm
from apps.invoices.models import Invoice, InvoiceTemplate
from django.db.models import Sum, Count
from django.utils import timezone
import openpyxl
from django.template.loader import render_to_string
from xhtml2pdf import pisa
from django.template.loader import render_to_string
from django.http import HttpResponse
import json
import os
import urllib.parse
from apps.core.models import CompanyProfile, BankAccount
from apps.core.utils import get_company_context, get_account_users_for_filter
from apps.core.ownership import for_user_queryset, get_account_for_user
import base64


def _receipt_primary_color(receipt, fallback='#1976d2'):
    """Prefer the receipt's saved custom_color for detail/print/PDF; else company theme."""
    color = (getattr(receipt, 'custom_color', None) or '').strip()
    return color or fallback or '#1976d2'


def _invoice_payload(invoice, user, company_context=None):
    """Compact invoice payload embedded in the create/edit page for instant UI (no wait)."""
    if not invoice:
        return None
    ctx = company_context or {}
    receiver = ''
    if user is not None:
        receiver = user.get_full_name() or user.get_username() or ''
    return {
        'id': invoice.pk,
        'client_name': invoice.client_name or '',
        'client_email': getattr(invoice, 'client_email', '') or '',
        'client_phone': invoice.client_phone or '',
        'client_address': invoice.client_address or '',
        'grand_total': str(invoice.grand_total or 0),
        'amount_paid': str(invoice.amount_paid or 0),
        'balance_due': str(invoice.balance_due or 0),
        'status': invoice.status or 'unpaid',
        'invoice_number': invoice.invoice_number or '',
        'received_by': receiver,
        'custom_color': ctx.get('theme_primary_color') or getattr(
            ctx.get('company_profile'), 'primary_color', None
        ) or '#1976d2',
        'currency_code': ctx.get('currency_code') or 'NGN',
        'currency_symbol': ctx.get('currency_symbol') or '₦',
        'transaction_id': invoice.invoice_number or '',
    }


def heal_receipt_payment_fields(receipt):
    """Repair stale balance/payment_type for this receipt and its whole invoice chain."""
    if not receipt or not getattr(receipt, 'invoice_id', None):
        return receipt
    from .models import resync_invoice_and_receipts
    inv = receipt.invoice
    needs_heal = receipt.payment_fields_out_of_sync()
    if not needs_heal:
        total = (
            inv.receipts.filter(is_deleted=False).aggregate(total=Sum('amount_received'))['total']
            or 0
        )
        from decimal import Decimal
        total = Decimal(str(total))
        expected_due = Decimal(str(inv.grand_total or 0)) - total
        if total == 0 or Decimal(str(inv.grand_total or 0)) <= 0:
            expected_status = 'unpaid'
        elif total >= Decimal(str(inv.grand_total or 0)):
            expected_status = 'delivered' if inv.status == 'delivered' else 'paid'
        else:
            expected_status = 'partial'
        needs_heal = (
            Decimal(str(inv.amount_paid or 0)) != total
            or Decimal(str(inv.balance_due or 0)) != expected_due
            or inv.status != expected_status
        )
    if needs_heal:
        resync_invoice_and_receipts(inv)
        receipt.refresh_from_db()
    return receipt



def get_current_template(user):
    """Get the current default invoice template (account-scoped for team members)."""
    account = get_account_for_user(user)
    if account:
        current_template = InvoiceTemplate.objects.filter(user__account=account, is_default=True).first()
        if not current_template:
            current_template = InvoiceTemplate.objects.filter(user__account=account).first()
    else:
        current_template = InvoiceTemplate.objects.filter(user=user).first()
    return current_template

def resolve_branch(receipt, company_profile):
    """Return the most relevant branch/location string for a receipt."""
    def cleaned(value):
        if not value:
            return None
        value = str(value).strip()
        return value or None
    preferred_state = cleaned(getattr(company_profile, 'state', None))
    if preferred_state:
        return preferred_state
    fallback_city = cleaned(getattr(company_profile, 'city', None))
    if fallback_city:
        return fallback_city
    fallback_country = cleaned(getattr(company_profile, 'country', None))
    if fallback_country:
        return fallback_country
    return '-'

def get_filtered_receipts(request):
    # Per-team-member isolation: admin sees all company receipts, team member sees only own; exclude soft-deleted (offline sync)
    receipts = for_user_queryset(Receipt, request.user, request, account_lookup='account').filter(is_deleted=False).select_related('invoice', 'created_by')
    search = request.GET.get('search', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    status = request.GET.get('status', '')
    amount = request.GET.get('amount', '')
    payment_method = request.GET.get('payment_method', '')
    received_by = request.GET.get('received_by', '')
    if search:
        receipts = receipts.filter(client_name__icontains=search)
    if date_from:
        receipts = receipts.filter(date_received__gte=date_from)
    if date_to:
        receipts = receipts.filter(date_received__lte=date_to)
    if status:
        receipts = receipts.filter(invoice__status=status)
    if amount:
        try:
            amount_val = float(amount.replace(',', ''))
            receipts = receipts.filter(amount_received=amount_val)
        except ValueError:
            pass
    if payment_method:
        receipts = receipts.filter(payment_method=payment_method)
    if received_by:
        receipts = receipts.filter(received_by__icontains=received_by)
    # Admin-only: filter by creator
    from apps.accounts.rbac import is_company_admin as _is_company_admin
    if _is_company_admin(request):
        created_by_id = request.GET.get('created_by', '').strip()
        if created_by_id:
            try:
                receipts = receipts.filter(created_by_id=int(created_by_id))
            except (ValueError, TypeError):
                pass
    return receipts

@login_required
@permission_required('receipts.view_receipt', raise_exception=True)
@never_cache
def receipt_list_view(request):
    """List all receipts with search/filter and dashboard stats."""
    # Base queryset (visibility-scoped only): used for dashboard stats so cards show
    # accurate account-wide totals regardless of active filters. Exclude soft-deleted.
    base_receipts = for_user_queryset(Receipt, request.user, request, account_lookup='account').filter(is_deleted=False)
    receipts = get_filtered_receipts(request)

    from apps.accounts.rbac import is_company_admin as _is_company_admin
    account_users = get_account_users_for_filter(request.user) if _is_company_admin(request) else []

    today = timezone.now().date()
    week_start = today - timezone.timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    # Dashboard stats: always from full (unfiltered) visibility-scoped data for accuracy
    stats = {
        'total_today': base_receipts.filter(date_received=today).aggregate(Sum('amount_received'))['amount_received__sum'] or 0,
        'total_week': base_receipts.filter(date_received__gte=week_start).aggregate(Sum('amount_received'))['amount_received__sum'] or 0,
        'total_month': base_receipts.filter(date_received__gte=month_start).aggregate(Sum('amount_received'))['amount_received__sum'] or 0,
        'top_clients': base_receipts.values('client_name').annotate(total=Sum('amount_received')).order_by('-total')[:5],
        'by_method': base_receipts.values('payment_method').annotate(total=Sum('amount_received')).order_by('-total'),
    }
    
    # Get company context for currency
    company_context = get_company_context(request.user, request)
    
    context = {
        'receipts': receipts.order_by('-date_received', '-created_at'),
        'search': request.GET.get('search', ''),
        'date_from': request.GET.get('date_from', ''),
        'date_to': request.GET.get('date_to', ''),
        'stats': stats,
        'company_profile': company_context['company_profile'],
        'user_currency_symbol': company_context['currency_symbol'],
        'user_currency_code': company_context['currency_code'],
        'is_company_admin': _is_company_admin(request),
        'account_users': account_users,
    }
    return render(request, 'receipts/receipt_list.html', context)

@login_required
@permission_required('receipts.add_receipt', raise_exception=True)
@never_cache
def receipt_create_view(request, invoice_id=None):
    """Create a new receipt, optionally linked to an invoice. No-cache so form is always fresh."""
    invoice = None
    if invoice_id:
        inv_qs = for_user_queryset(Invoice, request.user, request, account_lookup='account')
        invoice, response = get_object_or_unauthorized(request, inv_qs, pk=invoice_id)
        if response:
            return response
    company_context = get_company_context(request.user, request)
    profile = company_context.get('company_profile')
    theme_color = (
        (getattr(profile, 'primary_color', None) if profile else None)
        or company_context.get('theme_primary_color')
        or '#1976d2'
    )

    if request.method == 'POST':
        form = ReceiptForm(request.POST, invoice=invoice, user=request.user, default_color=theme_color)
        if form.is_valid():
            receipt = form.save(commit=False)
            # Set ownership for per-team-member isolation (required for list/dashboard visibility)
            if not receipt.pk:
                receipt.created_by = request.user
                acc = get_account_for_user(request.user)
                if acc:
                    receipt.account_id = acc.id
            # Do NOT set receipt.received_by = request.user; use the typed value from the form
            # Explicitly set display options from POST so checkboxes always save correctly (unchecked = not in POST)
            receipt.show_bank_details = request.POST.get('show_bank_details') == 'on' or request.POST.get('show_bank_details') == 'true'
            receipt.show_signature = request.POST.get('show_signature') == 'on' or request.POST.get('show_signature') == 'true'
            if not (receipt.custom_color or '').strip():
                receipt.custom_color = theme_color
            # balance_after_payment / payment_type / refund_due are calculated in Receipt.save()
            # from the linked invoice (form invoice), including prior receipts.
            receipt.save()
            messages.success(request, f'Receipt {receipt.receipt_no} created successfully!')
            # Redirect with cache-bust so browser fetches fresh receipt (signature/bank details) without hard refresh
            detail_url = reverse('receipts:detail', kwargs={'receipt_id': receipt.pk})
            return redirect(f'{detail_url}?_={receipt.updated_at.timestamp():.0f}')
    else:
        form = ReceiptForm(invoice=invoice, user=request.user, default_color=theme_color)
        if not form.initial.get('received_by'):
            form.initial['received_by'] = (
                request.user.get_full_name() or request.user.get_username() or ''
            )

    selected_invoice = invoice or (
        form.instance.invoice if getattr(form, 'instance', None) and getattr(form.instance, 'invoice_id', None) else None
    )
    form_config = {
        'currency_symbol': company_context.get('currency_symbol') or '₦',
        'currency_code': company_context.get('currency_code') or 'NGN',
        'existing_receipt_amount': '0',
        'is_editing': False,
        'receiver_name': request.user.get_full_name() or request.user.get_username() or '',
        'selected_invoice': _invoice_payload(selected_invoice, request.user, company_context),
    }
    context = {
        'form': form,
        'invoice': invoice,
        'receipt_form_config': form_config,
        'user_currency_symbol': company_context['currency_symbol'],
        'user_currency_code': company_context['currency_code'],
        'receiver_name': form_config['receiver_name'],
        'theme_primary_color': company_context.get('theme_primary_color', '#1976d2'),
        'theme_secondary_color': company_context.get('theme_secondary_color', '#f8f9fa'),
        'theme_accent_color': company_context.get('theme_accent_color', '#e9ecef'),
        'theme_text_color': company_context.get('theme_text_color', '#333333'),
    }
    return render(request, 'receipts/receipt_form.html', context)

@login_required
@permission_required('receipts.view_receipt', raise_exception=True)
@never_cache
def receipt_detail_view(request, receipt_id):
    """Show receipt details (per-team-member: admin sees all, team member sees own only)."""
    qs = for_user_queryset(Receipt, request.user, request, account_lookup='account').filter(is_deleted=False)
    receipt, response = get_object_or_unauthorized(request, qs, pk=receipt_id)
    if response:
        return response
    heal_receipt_payment_fields(receipt)
    # Get company context for currency from current user
    company_context = get_company_context(request.user, request)
    company_profile = company_context['company_profile']
    company_logo = company_context['company_logo']
    company_signature = company_context['company_signature']
    
    # All active bank accounts (default first) for Bank Details section
    bank_accounts = []
    if company_profile:
        bank_accounts = list(BankAccount.objects.filter(
            company=company_profile, is_active=True
        ).order_by('-is_default', 'bank_name'))
    
    # Build absolute URLs for images
    if company_logo:
        company_logo = request.build_absolute_uri(company_logo)
    if company_signature:
        company_signature = request.build_absolute_uri(company_signature)
    
    # Get current template for colors
    current_template = get_current_template(request.user)
    
    # Theme colors: receipt custom color drives detail/print accents
    company_primary = getattr(company_profile, 'primary_color', '#1976d2') if company_profile else '#1976d2'
    theme_primary_color = _receipt_primary_color(receipt, company_primary)
    theme_secondary_color = getattr(company_profile, 'secondary_color', '#f8f9fa') if company_profile else '#f8f9fa'
    theme_accent_color = getattr(company_profile, 'accent_color', '#e9ecef') if company_profile else '#e9ecef'
    theme_text_color = getattr(company_profile, 'text_color', '#333333') if company_profile else '#333333'
    
    context = {
        'receipt': receipt, 
        'company_profile': company_profile, 
        'company_logo': company_logo, 
        'company_signature': company_signature,
        'bank_accounts': bank_accounts,
        'user_currency_symbol': company_context['currency_symbol'],
        'user_currency_code': company_context['currency_code'],
        'branch_display': resolve_branch(receipt, company_profile),
        'current_template': current_template,
        'receipt_primary_color': theme_primary_color,
        # Theme colors for all templates (primary overridden by receipt color)
        'theme_primary_color': theme_primary_color,
        'theme_secondary_color': theme_secondary_color,
        'theme_accent_color': theme_accent_color,
        'theme_text_color': theme_text_color,
    }
    return render(request, 'receipts/receipt_detail.html', context)

@login_required
@company_admin_or_permission_required('receipts.change_receipt', raise_exception=True)
@never_cache
def receipt_edit_view(request, receipt_id):
    """Edit an existing receipt (per-team-member: only own or admin)."""
    qs = for_user_queryset(Receipt, request.user, request, account_lookup='account').filter(is_deleted=False)
    receipt, response = get_object_or_unauthorized(request, qs, pk=receipt_id)
    if response:
        return response
    company_context = get_company_context(request.user, request)
    profile = company_context.get('company_profile')
    theme_color = (
        (getattr(profile, 'primary_color', None) if profile else None)
        or company_context.get('theme_primary_color')
        or '#1976d2'
    )

    if request.method == 'POST':
        form = ReceiptForm(request.POST, instance=receipt, user=request.user, default_color=theme_color)
        if form.is_valid():
            receipt = form.save(commit=False)
            # Explicitly set display options from POST so checkboxes always save correctly
            receipt.show_bank_details = request.POST.get('show_bank_details') == 'on' or request.POST.get('show_bank_details') == 'true'
            receipt.show_signature = request.POST.get('show_signature') == 'on' or request.POST.get('show_signature') == 'true'
            if not (receipt.custom_color or '').strip():
                receipt.custom_color = theme_color
            receipt.save()
            messages.success(request, f'Receipt {receipt.receipt_no} updated successfully!')
            # Redirect with cache-bust so browser fetches fresh receipt (signature/bank details) without hard refresh
            detail_url = reverse('receipts:detail', kwargs={'receipt_id': receipt.pk})
            return redirect(f'{detail_url}?_={receipt.updated_at.timestamp():.0f}')
    else:
        form = ReceiptForm(instance=receipt, user=request.user, default_color=theme_color)
    form_config = {
        'currency_symbol': company_context.get('currency_symbol') or '₦',
        'currency_code': company_context.get('currency_code') or 'NGN',
        'existing_receipt_amount': str(receipt.amount_received or 0),
        'is_editing': True,
        'receiver_name': request.user.get_full_name() or request.user.get_username() or '',
        'selected_invoice': _invoice_payload(receipt.invoice, request.user, company_context),
    }
    context = {
        'form': form,
        'receipt': receipt,
        'receipt_form_config': form_config,
        'user_currency_symbol': company_context['currency_symbol'],
        'user_currency_code': company_context['currency_code'],
        'receiver_name': form_config['receiver_name'],
        'theme_primary_color': company_context.get('theme_primary_color', '#1976d2'),
        'theme_secondary_color': company_context.get('theme_secondary_color', '#f8f9fa'),
        'theme_accent_color': company_context.get('theme_accent_color', '#e9ecef'),
        'theme_text_color': company_context.get('theme_text_color', '#333333'),
    }
    return render(request, 'receipts/receipt_form.html', context)

@login_required
@company_admin_or_permission_required('receipts.delete_receipt', raise_exception=True)
def receipt_delete_view(request, receipt_id):
    """Delete a receipt (per-team-member: only own or admin)."""
    qs = for_user_queryset(Receipt, request.user, request, account_lookup='account').filter(is_deleted=False)
    receipt, response = get_object_or_unauthorized(request, qs, pk=receipt_id)
    if response:
        return response
    if request.method == 'POST':
        receipt_no = receipt.receipt_no
        receipt.delete()
        messages.success(request, f'Receipt {receipt_no} deleted.')
        return redirect('receipts:list')
    context = {'receipt': receipt}
    return render(request, 'receipts/receipt_confirm_delete.html', context)

@login_required
@company_admin_or_permission_required('receipts.print_receipt', raise_exception=True)
@never_cache
def receipt_print_view(request, receipt_id):
    """Print-friendly view (per-team-member: only own or admin)."""
    qs = for_user_queryset(Receipt, request.user, request, account_lookup='account').filter(is_deleted=False)
    receipt, response = get_object_or_unauthorized(request, qs, pk=receipt_id)
    if response:
        return response
    heal_receipt_payment_fields(receipt)
    # Get company context for currency from current user
    company_context = get_company_context(request.user, request)
    company_profile = company_context['company_profile']
    company_logo = company_context['company_logo']
    company_signature = company_context['company_signature']
    
    # All active bank accounts (default first) for Bank Details section
    bank_accounts = []
    if company_profile:
        bank_accounts = list(BankAccount.objects.filter(
            company=company_profile, is_active=True
        ).order_by('-is_default', 'bank_name'))
    
    # Build absolute URLs for images
    if company_logo:
        company_logo = request.build_absolute_uri(company_logo)
    if company_signature:
        company_signature = request.build_absolute_uri(company_signature)
    
    # Get current template for colors
    current_template = get_current_template(request.user)
    
    company_primary = getattr(company_profile, 'primary_color', '#1976d2') if company_profile else '#1976d2'
    theme_primary_color = _receipt_primary_color(receipt, company_primary)
    theme_secondary_color = getattr(company_profile, 'secondary_color', '#f8f9fa') if company_profile else '#f8f9fa'
    theme_accent_color = getattr(company_profile, 'accent_color', '#e9ecef') if company_profile else '#e9ecef'
    theme_text_color = getattr(company_profile, 'text_color', '#333333') if company_profile else '#333333'
    
    context = {
        'receipt': receipt, 
        'company_profile': company_profile, 
        'company_logo': company_logo, 
        'company_signature': company_signature,
        'bank_accounts': bank_accounts,
        'user_currency_symbol': company_context['currency_symbol'],
        'user_currency_code': company_context['currency_code'],
        'branch_display': resolve_branch(receipt, company_profile),
        'current_template': current_template,
        'receipt_primary_color': theme_primary_color,
        'theme_primary_color': theme_primary_color,
        'theme_secondary_color': theme_secondary_color,
        'theme_accent_color': theme_accent_color,
        'theme_text_color': theme_text_color,
    }
    return render(request, 'receipts/receipt_print.html', context)

@login_required
@company_admin_or_permission_required('receipts.download_receipt', raise_exception=True)
def receipt_pdf_view(request, receipt_id):
    """Export receipt as PDF (per-team-member: only own or admin)."""
    qs = for_user_queryset(Receipt, request.user, request, account_lookup='account').filter(is_deleted=False)
    receipt, response = get_object_or_unauthorized(request, qs, pk=receipt_id)
    if response:
        return response
    heal_receipt_payment_fields(receipt)
    # Get company context for currency from current user
    company_context = get_company_context(request.user, request)
    company_profile = company_context['company_profile']
    company_logo = company_context['company_logo']
    company_signature = company_context['company_signature']
    
    # All active bank accounts (default first) for Bank Details section
    bank_accounts = []
    if company_profile:
        bank_accounts = list(BankAccount.objects.filter(
            company=company_profile, is_active=True
        ).order_by('-is_default', 'bank_name'))
    
    # Build absolute URLs for images so PDF can load signature/logo
    if company_logo:
        company_logo = request.build_absolute_uri(company_logo)
    if company_signature:
        company_signature = request.build_absolute_uri(company_signature)
    
    # Get current template for colors
    current_template = get_current_template(request.user)
    from apps.accounts.rbac import is_company_admin as _is_company_admin
    company_primary = getattr(company_profile, 'primary_color', '#1976d2') if company_profile else '#1976d2'
    receipt_primary_color = _receipt_primary_color(receipt, company_primary)
    context = {
        'receipt': receipt, 
        'company_profile': company_profile, 
        'company_logo': company_logo, 
        'company_signature': company_signature,
        'bank_accounts': bank_accounts,
        'user_currency_symbol': company_context['currency_symbol'],
        'user_currency_code': company_context['currency_code'],
        'branch_display': resolve_branch(receipt, company_profile),
        'current_template': current_template,
        'is_company_admin': _is_company_admin(request),
        'receipt_primary_color': receipt_primary_color,
        'theme_primary_color': receipt_primary_color,
    }
    
    try:
        from xhtml2pdf import pisa
        from django.template.loader import render_to_string
        from io import BytesIO
        html_string = render_to_string('receipts/receipt_pdf_template.html', context)
        result = BytesIO()
        pdf = pisa.pisaDocument(BytesIO(html_string.encode("UTF-8")), result)
        if not pdf.err:
            response = HttpResponse(result.getvalue(), content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="receipt_{receipt.receipt_no}.pdf"'
            return response
        else:
            return HttpResponse("Error generating PDF", content_type="text/plain", status=500)
    except ImportError:
        return HttpResponse("xhtml2pdf is not installed. Please install it: pip install xhtml2pdf", content_type="text/plain", status=500)

@login_required
@permission_required('receipts.view_receipt', raise_exception=True)
def receipt_email_view(request, receipt_id):
    """Send receipt PDF to client via email. Uses company email as From (Company Profile)."""
    from django.conf import settings
    from django.core.mail import EmailMessage, get_connection
    from email.utils import formataddr
    from io import BytesIO
    from apps.core.utils import get_company_profile_for_user

    qs = for_user_queryset(Receipt, request.user, request, account_lookup='account').filter(is_deleted=False)
    receipt, response = get_object_or_unauthorized(request, qs, pk=receipt_id)
    if response:
        return response

    to_email = (request.POST.get('to_email') or request.GET.get('to_email') or '').strip()
    if not to_email and getattr(receipt, 'invoice', None):
        to_email = (getattr(receipt.invoice, 'client_email', None) or '').strip()
    if not to_email or '@' not in to_email:
        messages.warning(request, 'No recipient email. Enter an email address or set client email on the linked invoice.')
        return redirect('receipts:detail', receipt_id=receipt.pk)

    company_context = get_company_context(request.user, request)
    company_profile = company_context['company_profile']
    company_email = (company_profile.email or '').strip() if company_profile else ''
    company_name = (getattr(company_profile, 'company_name', None) or '').strip() if company_profile else ''
    default_from = getattr(settings, 'DEFAULT_FROM_EMAIL', None) or getattr(settings, 'EMAIL_HOST_USER', '') or 'noreply@example.com'
    sender_address = company_email if (company_email and '@' in company_email) else default_from
    if company_name:
        from_email = formataddr((company_name, sender_address))
    else:
        from_email = sender_address

    company_logo = company_context.get('company_logo')
    company_signature = company_context.get('company_signature')
    bank_accounts = []
    if company_profile:
        bank_accounts = list(BankAccount.objects.filter(company=company_profile, is_active=True).order_by('-is_default', 'bank_name'))
    if company_logo:
        company_logo = request.build_absolute_uri(company_logo)
    if company_signature:
        company_signature = request.build_absolute_uri(company_signature)
    current_template = get_current_template(request.user)
    from apps.accounts.rbac import is_company_admin as _is_company_admin
    company_primary = getattr(company_profile, 'primary_color', '#1976d2') if company_profile else '#1976d2'
    receipt_primary_color = _receipt_primary_color(receipt, company_primary)
    context = {
        'receipt': receipt,
        'company_profile': company_profile,
        'company_logo': company_logo,
        'company_signature': company_signature,
        'bank_accounts': bank_accounts,
        'user_currency_symbol': company_context['currency_symbol'],
        'user_currency_code': company_context['currency_code'],
        'branch_display': resolve_branch(receipt, company_profile),
        'current_template': current_template,
        'is_company_admin': _is_company_admin(request),
        'receipt_primary_color': receipt_primary_color,
        'theme_primary_color': receipt_primary_color,
    }
    try:
        html_string = render_to_string('receipts/receipt_pdf_template.html', context)
        result = BytesIO()
        pdf_status = pisa.pisaDocument(BytesIO(html_string.encode("UTF-8")), result)
        if pdf_status.err:
            messages.error(request, 'Could not generate receipt PDF.')
            return redirect('receipts:detail', receipt_id=receipt.pk)
        pdf_bytes = result.getvalue()
    except Exception as e:
        messages.error(request, f'Could not generate PDF: {e}')
        return redirect('receipts:detail', receipt_id=receipt.pk)

    subject = f'Receipt {receipt.receipt_no}'
    body = f'Please find your receipt {receipt.receipt_no} attached.'
    msg = EmailMessage(
        subject=subject,
        body=body,
        from_email=from_email,
        to=[to_email],
    )
    msg.attach(f'receipt_{receipt.receipt_no}.pdf', pdf_bytes, 'application/pdf')
    try:
        msg.send(fail_silently=False)
        messages.success(request, f'Receipt sent to {to_email}.')
    except Exception as e:
        messages.error(request, f'Failed to send email: {e}')
    return redirect('receipts:detail', receipt_id=receipt.pk)

@login_required
@company_admin_or_permission_required('receipts.download_receipt', raise_exception=True)
def export_excel(request):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Receipts"
    headers = ["Receipt #", "Client", "Date", "Amount", "Invoice Status"]
    ws.append(headers)
    
    receipts = for_user_queryset(Receipt, request.user, request, account_lookup='account').select_related('invoice')
    for receipt in receipts:
        ws.append([
            receipt.receipt_no,
            receipt.client_name,
            receipt.date_received.strftime("%Y-%m-%d"),
            receipt.amount_received,
            receipt.invoice.get_status_display(),
        ])
    
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename=receipts.xlsx'
    wb.save(response)
    return response

@login_required
@company_admin_or_permission_required('receipts.download_receipt', raise_exception=True)
def export_pdf(request):
    receipts = get_filtered_receipts(request)
    company_logo_base64 = None
    try:
        company_profile = CompanyProfile.objects.get(user=request.user)
        if company_profile.logo and hasattr(company_profile.logo, 'path') and os.path.isfile(company_profile.logo.path):
            try:
                with open(company_profile.logo.path, 'rb') as img_file:
                    company_logo_base64 = 'data:image/png;base64,' + base64.b64encode(img_file.read()).decode('utf-8')
            except Exception as e:
                company_logo_base64 = None
        else:
            company_logo_base64 = None
    except CompanyProfile.DoesNotExist:
        company_profile = None
        company_logo_base64 = None
    
    # Get company context for currency
    company_context = get_company_context(request.user, request)
    
    from apps.accounts.rbac import is_company_admin as _is_company_admin
    context = {
        'receipts': receipts.order_by('-date_received', '-created_at'),
        'company_profile': company_profile,
        'company_logo_base64': company_logo_base64,
        'user_currency_symbol': company_context['currency_symbol'],
        'user_currency_code': company_context['currency_code'],
        'is_company_admin': _is_company_admin(request),
    }
    
    html_string = render_to_string('receipts/receipt_list_export_pdf.html', context)
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename=receipts.pdf'
    pisa_status = pisa.CreatePDF(html_string, dest=response)
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html_string + '</pre>')
    return response
