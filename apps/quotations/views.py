from django.shortcuts import render, get_object_or_404, redirect
from business_app.views import get_object_or_unauthorized
from django.urls import reverse
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from apps.core.permissions import company_admin_or_permission_required
from django.db.models import Q, Sum, Count
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.forms import modelformset_factory
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from decimal import Decimal
from django.conf import settings
from django.core.mail import send_mail
from .models import Quotation, QuotationItem, QuotationTemplate
from .forms import QuotationForm, QuotationItemFormSet, QuotationFilterForm, QuotationTemplateForm
from apps.clients.models import Client
from apps.core.models import CompanyProfile
from apps.core.utils import get_company_context, format_currency, get_company_profile_for_user
from apps.core.ownership import for_user_queryset, get_account_for_user
from apps.accounts.rbac import is_company_admin
from apps.core.utils import get_account_users_for_filter
import openpyxl
from xhtml2pdf import pisa
from io import BytesIO
import os
import base64
import json
from django.utils import timezone


def _quotation_templates_for_user(user):
    """QuotationTemplate queryset for user's account (owner + team members)."""
    acc = get_account_for_user(user)
    if acc:
        return QuotationTemplate.objects.filter(user__account=acc)
    return QuotationTemplate.objects.filter(user=user)


def get_filtered_quotations(request):
    """Get filtered quotations based on search parameters"""
    # Filter by current user; exclude soft-deleted (offline sync). Omit template join for list speed.
    quotations = for_user_queryset(Quotation, request.user, request, account_lookup='account').filter(is_deleted=False).select_related('client', 'created_by')
    filter_form = QuotationFilterForm(request.GET, user=request.user)
    if is_company_admin(request):
        filter_form.fields['created_by'].queryset = get_account_users_for_filter(request.user)
    if filter_form.is_valid():
        search = filter_form.cleaned_data.get('search')
        status = filter_form.cleaned_data.get('status')
        date_from = filter_form.cleaned_data.get('date_from')
        date_to = filter_form.cleaned_data.get('date_to')
        client = filter_form.cleaned_data.get('client')
        if is_company_admin(request) and filter_form.cleaned_data.get('created_by'):
            quotations = quotations.filter(created_by=filter_form.cleaned_data['created_by'])
        
        if search:
            quotations = quotations.filter(
                Q(quotation_number__icontains=search) |
                Q(client__name__icontains=search) |
                Q(client__email__icontains=search) |
                Q(client__phone__icontains=search) |
                Q(notes__icontains=search) |
                Q(terms__icontains=search)
            )
        
        if status:
            quotations = quotations.filter(status=status)
        
        if date_from:
            quotations = quotations.filter(quotation_date__gte=date_from)
        
        if date_to:
            quotations = quotations.filter(quotation_date__lte=date_to)
        
        if client:
            quotations = quotations.filter(client=client)
    
    return quotations.order_by('-created_at')


@login_required
@permission_required('quotations.view_quotation', raise_exception=True)
def quotation_list(request):
    """Display paginated list of quotations with filters"""
    quotations = get_filtered_quotations(request)
    filter_form = QuotationFilterForm(request.GET, user=request.user)
    
    # Update client choices for current user's company (also set in form __init__)
    try:
        company_profile = get_company_profile_for_user(request.user, request)
        if company_profile:
            filter_form.fields['client'].queryset = Client.objects.filter(company=company_profile)
        else:
            filter_form.fields['client'].queryset = Client.objects.none()
    except Exception:
        filter_form.fields['client'].queryset = Client.objects.none()
    
    paginator = Paginator(quotations, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Calculate totals
    totals = quotations.aggregate(
        total_count=Count('id'),
        total_amount=Sum('grand_total') or 0,
        draft_count=Count('id', filter=Q(status='draft')),
        sent_count=Count('id', filter=Q(status='sent')),
        accepted_count=Count('id', filter=Q(status='accepted')),
        declined_count=Count('id', filter=Q(status='declined')),
        expired_count=Count('id', filter=Q(status='expired')),
    )
    
    # Get current template
    current_template = _quotation_templates_for_user(request.user).filter(is_default=True).first()
    if not current_template:
        current_template = _quotation_templates_for_user(request.user).first()
        if not current_template:
            current_template = QuotationTemplate.objects.create(
                user=request.user,
                name="Default Quotation Template",
                description="Automatically created default template",
                is_default=True,
                primary_color="#1976d2",
                secondary_color="#f8f9fa",
                show_company_logo=True,
                show_company_details=True,
                show_bank_details=True,
                show_signature=True,
                document_title="QUOTATION"
            )
    
    # Get company context for currency
    company_context = get_company_context(request.user, request)
    if is_company_admin(request):
        filter_form.fields['created_by'].queryset = get_account_users_for_filter(request.user)
    account_users = get_account_users_for_filter(request.user) if is_company_admin(request) else []
    context = {
        'page_obj': page_obj,
        'filter_form': filter_form,
        'total_quotations': totals['total_count'],
        'total_amount': totals['total_amount'],
        'formatted_total_amount': totals['total_amount'],
        'draft_count': totals['draft_count'],
        'sent_count': totals['sent_count'],
        'accepted_count': totals['accepted_count'],
        'declined_count': totals['declined_count'],
        'expired_count': totals['expired_count'],
        'current_template': current_template,
        'company_profile': company_context['company_profile'],
        'user_currency_symbol': company_context['currency_symbol'],
        'user_currency_code': company_context['currency_code'],
    }
    return render(request, 'quotations/quotation_list.html', context)


def get_quotation_context(quotation, user, request=None):
    """Get context data for quotation rendering. Pass request so team members get account company currency."""
    # Get company profile data for display
    company_profile = None
    company_logo = None
    company_signature = None
    default_bank_account = None
    bank_accounts = []
    
    try:
        from apps.core.models import BankAccount
        if user and user.is_authenticated:
            company_profile = get_company_profile_for_user(user, request)
            
            if company_profile.logo:
                company_logo = company_profile.logo.url
            if company_profile.signature:
                company_signature = company_profile.signature.url
                
            # Get default bank account
            default_bank_account = BankAccount.objects.filter(
                company=company_profile, 
                is_default=True
            ).first()
            if not default_bank_account:
                default_bank_account = BankAccount.objects.filter(company=company_profile).first()
            # All active bank accounts (default first) for showing multiple accounts
            bank_accounts = list(BankAccount.objects.filter(
                company=company_profile, is_active=True
            ).order_by('-is_default', 'bank_name'))
    except:
        pass
    
    # Format currency and numbers (from company admin settings; fallback ₦/NGN)
    currency_symbol = getattr(company_profile, 'currency_symbol', '₦') if company_profile else '₦'
    currency_code = getattr(company_profile, 'currency_code', 'NGN') if company_profile else 'NGN'
    
    # Import the number_to_words function from core.api_views
    from apps.core.api_views import number_to_words
    
    total_words = number_to_words(quotation.grand_total, currency=currency_code)
    formatted_total = format_currency(quotation.grand_total, currency_symbol)
    
    # Get theme colors from company profile
    theme_primary_color = getattr(company_profile, 'primary_color', '#1976d2') if company_profile else '#1976d2'
    theme_secondary_color = getattr(company_profile, 'secondary_color', '#f8f9fa') if company_profile else '#f8f9fa'
    theme_accent_color = getattr(company_profile, 'accent_color', '#e9ecef') if company_profile else '#e9ecef'
    theme_text_color = getattr(company_profile, 'text_color', '#333333') if company_profile else '#333333'
    
    return {
        'quotation': quotation,
        'company_profile': company_profile,
        'company_logo': company_logo,
        'company_signature': company_signature,
        'default_bank_account': default_bank_account,
        'bank_accounts': bank_accounts,
        'currency_symbol': currency_symbol,
        'total_words': total_words,
        'formatted_total': formatted_total,
        # Theme colors for all templates
        'theme_primary_color': theme_primary_color,
        'theme_secondary_color': theme_secondary_color,
        'theme_accent_color': theme_accent_color,
        'theme_text_color': theme_text_color,
    }


@login_required
@permission_required('quotations.view_quotation', raise_exception=True)
def quotation_detail(request, pk):
    """Display detailed view of a quotation. Scoped to current user's account."""
    qs = for_user_queryset(Quotation, request.user, request, account_lookup='account').filter(is_deleted=False)
    quotation, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return response
    context = get_quotation_context(quotation, request.user, request)
    
    # Get company context for currency
    company_context = get_company_context(request.user, request)
    context.update({
        'user_currency_symbol': company_context['currency_symbol'],
        'user_currency_code': company_context['currency_code'],
    })
    
    return render(request, 'quotations/quotation_detail.html', context)


@login_required
@permission_required('quotations.add_quotation', raise_exception=True)
def quotation_create(request):
    """Create a new quotation"""
    if request.method == 'POST':
        form = QuotationForm(request.POST, user=request.user)
        formset = QuotationItemFormSet(request.POST, instance=Quotation())
        
        if form.is_valid() and formset.is_valid():
            try:
                quotation = form.save(commit=False)
                # Use default template when template field is not submitted (hidden from form)
                if quotation.template is None and request.user.is_authenticated:
                    default_tpl = _quotation_templates_for_user(request.user).filter(is_default=True).first()
                    if not default_tpl:
                        default_tpl = _quotation_templates_for_user(request.user).first()
                    if default_tpl:
                        quotation.template = default_tpl
                
                # Handle client name - create or find client
                client_name = form.cleaned_data.get('client_name', '').strip()
                if client_name:
                    # Try to find existing client by name
                    # Get the first available company profile for client creation
                    from apps.core.models import CompanyProfile
                    company = CompanyProfile.objects.first()
                    
                    client_address = form.cleaned_data.get('client_address', '').strip()
                    client, created = Client.objects.get_or_create(
                        name=client_name,
                        defaults={
                            'email': '',
                            'phone': '',
                            'address': client_address,
                            'company': company
                        }
                    )
                    if not created and client_address:
                        client.address = client_address
                        client.save(update_fields=['address'])
                    quotation.client = client
                else:
                    quotation.client = None
                
                # Set user if authenticated, otherwise leave as None
                if request.user.is_authenticated:
                    quotation.user = request.user
                
                # Check for duplicate quotation (same user, client, and recent timestamp)
                if quotation.user:
                    recent_duplicate = Quotation.objects.filter(
                        user=quotation.user,
                        client=quotation.client,
                        quotation_date=timezone.now().date(),
                        created_at__gte=timezone.now() - timezone.timedelta(minutes=1)
                    ).exclude(pk=quotation.pk if quotation.pk else None).first()
                    
                    if recent_duplicate:
                        # Return the existing quotation instead of creating a duplicate
                        quotation = recent_duplicate
                        messages.info(request, f'Using existing quotation {quotation.quotation_number}')
                    else:
                        # Save quotation first
                        quotation.save()
                else:
                    # Save quotation first
                    quotation.save()
                
                # Save formset items
                formset.instance = quotation
                formset.save()
                
                # Handle flexible tax and discount calculation (percentage or fixed)
                from decimal import Decimal
                tax_value = Decimal(str(form.cleaned_data.get('total_tax', 0)))
                discount_value = Decimal(str(form.cleaned_data.get('total_discount', 0)))
                
                # Get types from form (auto-detected in clean methods or from selector)
                tax_type = form.cleaned_data.get('tax_type', 'percentage')
                discount_type = form.cleaned_data.get('discount_type', 'percentage')
                
                # Calculate subtotal first
                quotation.subtotal = sum(item.line_total for item in quotation.items.all())
                
                # Store types and values
                quotation.tax_type = tax_type
                quotation.tax_value = tax_value
                quotation.discount_type = discount_type
                quotation.discount_value = discount_value
                
                # Calculate tax based on type
                if tax_type == 'percentage':
                    quotation.total_tax = quotation.subtotal * (tax_value / Decimal('100'))
                else:  # fixed
                    quotation.total_tax = tax_value
                
                # Calculate discount based on type
                if discount_type == 'percentage':
                    quotation.total_discount = quotation.subtotal * (discount_value / Decimal('100'))
                else:  # fixed
                    quotation.total_discount = discount_value
                
                # Calculate grand total
                quotation.grand_total = (
                    quotation.subtotal +
                    quotation.total_tax +
                    quotation.shipping_fee +
                    quotation.other_charges -
                    quotation.total_discount
                )
                
                # Save the quotation with calculated values
                quotation.save()
                
                # Handle Ajax requests
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json':
                    return JsonResponse({
                        'success': True,
                        'message': f'Quotation {quotation.quotation_number} created successfully!',
                        'quotation_id': quotation.pk,
                        'quotation_number': quotation.quotation_number,
                        'redirect_url': reverse('quotations:quotation_list')
                    })
                
                messages.success(request, f'Quotation {quotation.quotation_number} created successfully!')
                return redirect('quotations:quotation_list')
                
            except Exception as e:
                # Handle Ajax requests
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json':
                    return JsonResponse({
                        'success': False,
                        'message': f'Error creating quotation: {str(e)}'
                    })
                
                messages.error(request, f'Error creating quotation: {str(e)}')
        else:
            # Handle Ajax requests with validation errors
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json':
                errors = {}
                if not form.is_valid():
                    errors.update(form.errors)
                if not formset.is_valid():
                    errors.update(formset.errors)
                return JsonResponse({
                    'success': False,
                    'message': 'Please correct the errors below.',
                    'errors': errors
                })
    else:
        form = QuotationForm(user=request.user)
        formset = QuotationItemFormSet(instance=Quotation())
    
    # Get company context for currency - handle anonymous users
    company_context = get_company_context(request.user, request)
    
    context = {
        'form': form,
        'formset': formset,
        'create': True,
        'company_profile': company_context['company_profile'],
        'user_currency_symbol': company_context['currency_symbol'],
        'user_currency_code': company_context['currency_code'],
        'user': request.user,  # Add user to context for template
        # Theme colors
        'theme_primary_color': company_context.get('theme_primary_color', '#1976d2'),
        'theme_secondary_color': company_context.get('theme_secondary_color', '#f8f9fa'),
        'theme_accent_color': company_context.get('theme_accent_color', '#e9ecef'),
        'theme_text_color': company_context.get('theme_text_color', '#333333'),
    }
    return render(request, 'quotations/quotation_form.html', context)


@login_required
@company_admin_or_permission_required('quotations.change_quotation', raise_exception=True)
def quotation_edit(request, pk):
    """Edit an existing quotation"""
    qs = for_user_queryset(Quotation, request.user, request, account_lookup='account').filter(is_deleted=False)
    quotation, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return response
    
    if request.method == 'POST':
        form = QuotationForm(request.POST, instance=quotation, user=request.user)
        formset = QuotationItemFormSet(request.POST, instance=quotation)
        
        if form.is_valid() and formset.is_valid():
            try:
                quotation = form.save(commit=False)
                
                # Handle client name and address - create or find client
                client_name = form.cleaned_data.get('client_name', '').strip()
                client_address = form.cleaned_data.get('client_address', '').strip()
                if client_name:
                    # Try to find existing client by name first (company-scoped)
                    try:
                        company_profile = get_company_profile_for_user(request.user, request)
                        client = Client.objects.filter(company=company_profile, name=client_name).first() if company_profile else None
                        if not client and company_profile:
                            client, created = Client.objects.get_or_create(
                                name=client_name,
                                company=company_profile,
                                defaults={
                                    'email': '',
                                    'phone': '',
                                    'address': client_address,
                                }
                            )
                        if client:
                            if client_address:
                                client.address = client_address
                                client.save(update_fields=['address'])
                            quotation.client = client
                        else:
                            quotation.client = None
                    except Exception as e:
                        # If client creation fails, just set to None
                        quotation.client = None
                        print(f"Warning: Could not create/find client '{client_name}': {e}")
                else:
                    quotation.client = None
                
                # Set user if authenticated and not already set
                if request.user.is_authenticated and not quotation.user:
                    quotation.user = request.user
                
                # Save quotation first
                quotation.save()
                
                # Save formset items
                formset.save()
                
                # Handle flexible tax and discount calculation (percentage or fixed)
                from decimal import Decimal
                tax_value = Decimal(str(form.cleaned_data.get('total_tax', 0)))
                discount_value = Decimal(str(form.cleaned_data.get('total_discount', 0)))
                
                # Get types from form (auto-detected in clean methods or from selector)
                tax_type = form.cleaned_data.get('tax_type', 'percentage')
                discount_type = form.cleaned_data.get('discount_type', 'percentage')
                
                # Calculate subtotal first
                quotation.subtotal = sum(item.line_total for item in quotation.items.all())
                
                # Store types and values
                quotation.tax_type = tax_type
                quotation.tax_value = tax_value
                quotation.discount_type = discount_type
                quotation.discount_value = discount_value
                
                # Calculate tax based on type
                if tax_type == 'percentage':
                    quotation.total_tax = quotation.subtotal * (tax_value / Decimal('100'))
                else:  # fixed
                    quotation.total_tax = tax_value
                
                # Calculate discount based on type
                if discount_type == 'percentage':
                    quotation.total_discount = quotation.subtotal * (discount_value / Decimal('100'))
                else:  # fixed
                    quotation.total_discount = discount_value
                
                # Calculate grand total
                quotation.grand_total = (
                    quotation.subtotal +
                    quotation.total_tax +
                    quotation.shipping_fee +
                    quotation.other_charges -
                    quotation.total_discount
                )
                
                # Save the quotation with calculated values
                quotation.save()
                
                # Handle Ajax requests
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json':
                    return JsonResponse({
                        'success': True,
                        'message': f'Quotation {quotation.quotation_number} updated successfully!',
                        'quotation_id': quotation.pk,
                        'quotation_number': quotation.quotation_number,
                        'redirect_url': reverse('quotations:quotation_list')
                    })
                
                messages.success(request, f'Quotation {quotation.quotation_number} updated successfully!')
                return redirect('quotations:quotation_list')
                
            except Exception as e:
                # Handle Ajax requests
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json':
                    return JsonResponse({
                        'success': False,
                        'message': f'Error updating quotation: {str(e)}'
                    })
                
                messages.error(request, f'Error updating quotation: {str(e)}')
        else:
            # Handle Ajax requests with validation errors
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json':
                errors = {}
                if not form.is_valid():
                    errors.update(form.errors)
                if not formset.is_valid():
                    errors.update(formset.errors)
                return JsonResponse({
                    'success': False,
                    'message': 'Please correct the errors below.',
                    'errors': errors
                })
    else:
        form = QuotationForm(instance=quotation, user=request.user)
        formset = QuotationItemFormSet(instance=quotation)
        
        # Set discount and tax types and values for display
        form.initial['tax_type'] = quotation.tax_type or 'percentage'
        form.initial['discount_type'] = quotation.discount_type or 'percentage'
        
        # Display the stored value (percentage number or fixed amount)
        if quotation.tax_value:
            form.initial['total_tax'] = quotation.tax_value
        elif quotation.subtotal > 0 and quotation.total_tax > 0:
            # Backward compatibility: calculate percentage from amount
            tax_percentage = (quotation.total_tax / quotation.subtotal) * 100
            form.initial['total_tax'] = tax_percentage
        
        if quotation.discount_value:
            form.initial['total_discount'] = quotation.discount_value
        elif quotation.subtotal > 0 and quotation.total_discount > 0:
            # Backward compatibility: calculate percentage from amount
            discount_percentage = (quotation.total_discount / quotation.subtotal) * 100
            form.initial['total_discount'] = discount_percentage
    
    # Get company context for currency - handle anonymous users
    company_context = get_company_context(request.user, request)
    
    context = {
        'form': form,
        'formset': formset,
        'quotation': quotation,
        'create': False,
        'company_profile': company_context['company_profile'],
        'user_currency_symbol': company_context['currency_symbol'],
        'user_currency_code': company_context['currency_code'],
        'user': request.user,  # Add user to context for template
        # Theme colors
        'theme_primary_color': company_context.get('theme_primary_color', '#1976d2'),
        'theme_secondary_color': company_context.get('theme_secondary_color', '#f8f9fa'),
        'theme_accent_color': company_context.get('theme_accent_color', '#e9ecef'),
        'theme_text_color': company_context.get('theme_text_color', '#333333'),
    }
    return render(request, 'quotations/quotation_form.html', context)


@login_required
@company_admin_or_permission_required('quotations.delete_quotation', raise_exception=True)
def quotation_delete(request, pk):
    """Delete a quotation"""
    qs = for_user_queryset(Quotation, request.user, request, account_lookup='account').filter(is_deleted=False)
    quotation, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return response
    
    if request.method == 'POST':
        quotation_number = quotation.quotation_number
        quotation.delete()
        messages.success(request, f'Quotation {quotation_number} deleted successfully!')
        return redirect('quotations:quotation_list')
    
    context = {'quotation': quotation}
    return render(request, 'quotations/quotation_delete.html', context)


@login_required
@company_admin_or_permission_required('quotations.delete_quotation', raise_exception=True)
def quotation_delete_ajax(request, pk):
    """Delete a quotation via AJAX"""
    if request.method == 'POST':
        try:
            qs = for_user_queryset(Quotation, request.user, request, account_lookup='account').filter(is_deleted=False)
            quotation, response = get_object_or_unauthorized(request, qs, pk=pk)
            if response:
                return response
            quotation_number = quotation.quotation_number
            quotation.delete()
            return JsonResponse({
                'success': True,
                'message': f'Quotation {quotation_number} deleted successfully!'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Error deleting quotation: {str(e)}'
            })
    
    return JsonResponse({'success': False, 'message': 'Invalid request method'})


@login_required
@company_admin_or_permission_required('quotations.download_quotation', raise_exception=True)
def quotation_pdf(request, pk):
    """Generate PDF for a quotation (requires quotations.download_quotation)"""
    qs = for_user_queryset(Quotation, request.user, request, account_lookup='account').filter(is_deleted=False)
    quotation, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return response
    context = get_quotation_context(quotation, request.user, request)
    
    # Get template
    template = quotation.template
    if not template:
        template = _quotation_templates_for_user(request.user).filter(is_default=True).first()
        if not template:
            template = QuotationTemplate.objects.create(
                user=request.user,
                name="Default Template",
                is_default=True,
                primary_color="#1976d2",
                secondary_color="#f8f9fa"
            )
    
    context['template'] = template
    
    # Get company context for currency - handle anonymous users
    company_context = get_company_context(request.user, request)
    from apps.accounts.rbac import is_company_admin as _is_company_admin
    context.update({
        'user_currency_symbol': company_context['currency_symbol'],
        'user_currency_code': company_context['currency_code'],
        'is_company_admin': _is_company_admin(request),
    })
    
    try:
        html_string = render_to_string('quotations/quotation_pdf.html', context)
        result = BytesIO()
        pdf = pisa.pisaDocument(BytesIO(html_string.encode("UTF-8")), result)
        
        if not pdf.err:
            response = HttpResponse(result.getvalue(), content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="quotation_{quotation.quotation_number}.pdf"'
            return response
        else:
            return HttpResponse("Error generating PDF", content_type="text/plain", status=500)
    except Exception as e:
        return HttpResponse(f"Error generating PDF: {str(e)}", content_type="text/plain", status=500)


@login_required
@company_admin_or_permission_required('quotations.print_quotation', raise_exception=True)
def quotation_print(request, pk):
    """Print-friendly view of a quotation (requires quotations.print_quotation)"""
    qs = for_user_queryset(Quotation, request.user, request, account_lookup='account').filter(is_deleted=False)
    quotation, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return response
    context = get_quotation_context(quotation, request.user, request)
    
    # Get company context for currency
    company_context = get_company_context(request.user, request)
    context.update({
        'user_currency_symbol': company_context['currency_symbol'],
        'user_currency_code': company_context['currency_code'],
    })
    
    return render(request, 'quotations/quotation_print.html', context)


@login_required
@permission_required('quotations.view_quotationtemplate', raise_exception=True)
def template_list(request):
    """List all quotation templates - Staff only"""
    templates = _quotation_templates_for_user(request.user).order_by('-is_default', 'name')
    
    # Get company context for currency
    company_context = get_company_context(request.user, request)
    
    context = {
        'templates': templates,
        'company_profile': company_context['company_profile'],
        'user_currency_symbol': company_context['currency_symbol'],
        'user_currency_code': company_context['currency_code'],
    }
    return render(request, 'quotations/template_list.html', context)


@login_required
@permission_required('quotations.add_quotationtemplate', raise_exception=True)
def template_create(request):
    """Create a new quotation template"""
    if request.method == 'POST':
        form = QuotationTemplateForm(request.POST)
        if form.is_valid():
            template = form.save(commit=False)
            template.user = request.user
            template.save()
            messages.success(request, f'Template "{template.name}" created successfully!')
            return redirect('quotations:template_list')
    else:
        form = QuotationTemplateForm()
    
    # Get company context for currency
    company_context = get_company_context(request.user, request)
    
    context = {
        'form': form,
        'company_profile': company_context['company_profile'],
        'user_currency_symbol': company_context['currency_symbol'],
        'user_currency_code': company_context['currency_code'],
    }
    return render(request, 'quotations/template_form.html', context)


@login_required
@permission_required('quotations.change_quotationtemplate', raise_exception=True)
def template_edit(request, pk):
    """Edit a quotation template"""
    template = get_object_or_404(_quotation_templates_for_user(request.user), pk=pk)
    
    if request.method == 'POST':
        form = QuotationTemplateForm(request.POST, instance=template)
        if form.is_valid():
            form.save()
            messages.success(request, f'Template "{template.name}" updated successfully!')
            return redirect('quotations:template_list')
    else:
        form = QuotationTemplateForm(instance=template)
    
    # Get company context for currency
    company_context = get_company_context(request.user, request)
    
    context = {
        'form': form,
        'template': template,
        'company_profile': company_context['company_profile'],
        'user_currency_symbol': company_context['currency_symbol'],
        'user_currency_code': company_context['currency_code'],
    }
    return render(request, 'quotations/template_form.html', context)


@login_required
@permission_required('quotations.view_quotationtemplate', raise_exception=True)
def template_detail(request, pk):
    """View template details"""
    template = get_object_or_404(_quotation_templates_for_user(request.user), pk=pk)
    
    # Get company context for currency
    company_context = get_company_context(request.user, request)
    
    context = {
        'template': template,
        'company_profile': company_context['company_profile'],
        'user_currency_symbol': company_context['currency_symbol'],
        'user_currency_code': company_context['currency_code'],
    }
    return render(request, 'quotations/template_detail.html', context)


@login_required
@permission_required('quotations.delete_quotationtemplate', raise_exception=True)
def template_delete(request, pk):
    """Delete a quotation template"""
    template = get_object_or_404(_quotation_templates_for_user(request.user), pk=pk)
    
    if request.method == 'POST':
        template_name = template.name
        template.delete()
        messages.success(request, f'Template "{template_name}" deleted successfully!')
        return redirect('quotations:template_list')
    
    # Get company context for currency
    company_context = get_company_context(request.user, request)
    
    context = {
        'template': template,
        'company_profile': company_context['company_profile'],
        'user_currency_symbol': company_context['currency_symbol'],
        'user_currency_code': company_context['currency_code'],
    }
    return render(request, 'quotations/template_delete.html', context)


@login_required
@permission_required('quotations.add_quotationtemplate', raise_exception=True)
def template_duplicate(request, pk):
    """Duplicate a quotation template"""
    template = get_object_or_404(QuotationTemplate, pk=pk)
    
    if request.method == 'POST':
        new_template = QuotationTemplate.objects.create(
            user=request.user,
            name=f"{template.name} (Copy)",
            description=template.description,
            primary_color=template.primary_color,
            secondary_color=template.secondary_color,
            show_company_logo=template.show_company_logo,
            show_company_details=template.show_company_details,
            show_bank_details=template.show_bank_details,
            document_title=template.document_title,
            footer_text=template.footer_text,
            is_default=False
        )
        messages.success(request, f'Template "{new_template.name}" created successfully!')
        return redirect('quotations:template_list')
    
    # Get company context for currency
    company_context = get_company_context(request.user, request)
    
    context = {
        'template': template,
        'company_profile': company_context['company_profile'],
        'user_currency_symbol': company_context['currency_symbol'],
        'user_currency_code': company_context['currency_code'],
    }
    return render(request, 'quotations/template_duplicate.html', context)


@login_required
@permission_required('quotations.change_quotationtemplate', raise_exception=True)
def template_apply_to_all(request, pk):
    """Apply template to all quotations"""
    template = get_object_or_404(_quotation_templates_for_user(request.user), pk=pk)
    
    if request.method == 'POST':
        updated_count = for_user_queryset(Quotation, request.user, request, account_lookup='account').filter(is_deleted=False).update(template=template)
        messages.success(request, f'Template "{template.name}" applied to {updated_count} quotations!')
        return redirect('quotations:template_list')
    
    # Get company context for currency
    company_context = get_company_context(request.user, request)
    
    context = {
        'template': template,
        'company_profile': company_context['company_profile'],
        'user_currency_symbol': company_context['currency_symbol'],
        'user_currency_code': company_context['currency_code'],
    }
    return render(request, 'quotations/template_apply.html', context)


@login_required
@permission_required('quotations.view_quotationtemplate', raise_exception=True)
def api_templates(request):
    """API endpoint to get templates for AJAX requests"""
    templates = _quotation_templates_for_user(request.user).values('id', 'name', 'is_default')
    return JsonResponse({'templates': list(templates)})


@login_required
@company_admin_or_permission_required('quotations.can_approve_quotation', raise_exception=True)
def quotation_update_status(request, pk):
    """Update quotation status"""
    qs = for_user_queryset(Quotation, request.user, request, account_lookup='account').filter(is_deleted=False)
    quotation, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return response
    
    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status in dict(Quotation.STATUS_CHOICES):
            old_status = quotation.get_status_display()
            quotation.status = new_status
            quotation.save()
            
            # Check if this is an AJAX request
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                from django.http import JsonResponse
                return JsonResponse({
                    'success': True,
                    'message': f'Quotation status updated from {old_status} to {quotation.get_status_display()}',
                    'status': quotation.status,
                    'status_display': quotation.get_status_display()
                })
            else:
                messages.success(request, f'Quotation status updated from {old_status} to {quotation.get_status_display()}')
                return redirect('quotations:quotation_detail', pk=quotation.pk)
        else:
            # Check if this is an AJAX request
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                from django.http import JsonResponse
                return JsonResponse({
                    'success': False,
                    'message': 'Invalid status provided'
                })
            else:
                messages.error(request, 'Invalid status provided')
    
    # Get company context for currency
    company_context = get_company_context(request.user, request)
    
    context = {
        'quotation': quotation,
        'status_choices': Quotation.STATUS_CHOICES,
        'company_profile': company_context['company_profile'],
        'user_currency_symbol': company_context['currency_symbol'],
        'user_currency_code': company_context['currency_code'],
    }
    return render(request, 'quotations/quotation_update_status.html', context)


@login_required
@company_admin_or_permission_required('quotations.change_quotation', raise_exception=True)
@permission_required('invoices.add_invoice', raise_exception=True)
def convert_to_invoice(request, pk):
    """Convert quotation to invoice"""
    qs = for_user_queryset(Quotation, request.user, request, account_lookup='account').filter(is_deleted=False)
    quotation, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return response
    
    if request.method == 'POST':
        try:
            from apps.invoices.models import Invoice, InvoiceItem
            
            # Build client fields from quotation.client (Invoice uses client_name/phone/email/address, not client FK)
            client = quotation.client
            client_name = (client.name or '') if client else ''
            client_phone = (client.phone or '') if client else ''
            client_email = (client.email or '') if client else ''
            client_address = (client.address or '') if client else ''
            # Create invoice with flexible discount/tax types (ownership for per-team-member isolation)
            invoice = Invoice.objects.create(
                user=request.user,
                client_name=client_name,
                client_phone=client_phone,
                client_email=client_email,
                client_address=client_address,
                invoice_date=timezone.now().date(),
                due_date=timezone.now().date() + timezone.timedelta(days=30),
                subtotal=quotation.subtotal,
                total_tax=quotation.total_tax,
                tax_type=getattr(quotation, 'tax_type', 'percentage') or 'percentage',
                tax_value=getattr(quotation, 'tax_value', 0) or 0,
                total_discount=quotation.total_discount,
                discount_type=getattr(quotation, 'discount_type', 'percentage') or 'percentage',
                discount_value=getattr(quotation, 'discount_value', 0) or 0,
                shipping_fee=quotation.shipping_fee,
                other_charges=quotation.other_charges,
                grand_total=quotation.grand_total,
                notes=f"Converted from quotation {quotation.quotation_number}",
                status='unpaid'
            )
            
            # Copy line items
            for item in quotation.items.all():
                InvoiceItem.objects.create(
                    invoice=invoice,
                    product_service=item.product_service,
                    description=item.description,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    line_total=item.line_total
                )
            
            # Update quotation
            quotation.converted_invoice = invoice
            quotation.conversion_date = timezone.now()
            quotation.status = 'accepted'
            quotation.save()
            
            messages.success(request, f'Quotation converted to invoice {invoice.invoice_number} successfully!')
            return redirect('invoices:detail', pk=invoice.pk)
            
        except Exception as e:
            messages.error(request, f'Error converting quotation: {str(e)}')
    
    # Get company context for currency
    company_context = get_company_context(request.user, request)
    
    context = {
        'quotation': quotation,
        'company_profile': company_context['company_profile'],
        'user_currency_symbol': company_context['currency_symbol'],
        'user_currency_code': company_context['currency_code'],
    }
    return render(request, 'quotations/convert_to_invoice.html', context)


@login_required
@company_admin_or_permission_required('quotations.download_quotation', raise_exception=True)
def quotation_export_excel(request, pk=None):
    """Export quotations to Excel (requires quotations.download_quotation)"""
    if pk:
        quotations = for_user_queryset(Quotation, request.user, request, account_lookup='account').filter(is_deleted=False).filter(pk=pk)
    else:
        quotations = get_filtered_quotations(request)
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Quotations"
    
    # Headers
    headers = [
        "Quotation #", "Date", "Client", "Status", "Subtotal", 
        "Tax", "Discount", "Shipping", "Other Charges", "Grand Total"
    ]
    ws.append(headers)
    
    # Data
    for quotation in quotations:
        ws.append([
            quotation.quotation_number,
            quotation.quotation_date.strftime("%Y-%m-%d"),
            quotation.client.name if quotation.client else "No Client",
            quotation.get_status_display(),
            float(quotation.subtotal),
            float(quotation.total_tax),
            float(quotation.total_discount),
            float(quotation.shipping_fee),
            float(quotation.other_charges),
            float(quotation.grand_total),
        ])
    
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename=quotations.xlsx'
    wb.save(response)
    return response


@login_required
@permission_required('quotations.view_quotation', raise_exception=True)
def quotation_stats(request):
    """Get quotation statistics for dashboard and list-page real-time card updates."""
    quotations = for_user_queryset(Quotation, request.user, request, account_lookup='account').filter(is_deleted=False)
    company_context = get_company_context(request.user, request)
    currency_symbol = company_context.get('currency_symbol') or '₦'
    total_sum = quotations.aggregate(Sum('grand_total'))['grand_total__sum'] or Decimal('0')
    
    stats = {
        'total_quotations': quotations.count(),
        'total_value': float(total_sum),
        'formatted_total_value': format_currency(total_sum, currency_symbol),
        'draft_count': quotations.filter(status='draft').count(),
        'sent_count': quotations.filter(status='sent').count(),
        'accepted_count': quotations.filter(status='accepted').count(),
        'declined_count': quotations.filter(status='declined').count(),
        'expired_count': quotations.filter(status='expired').count(),
        'conversion_rate': 0,
    }
    
    if stats['total_quotations'] > 0:
        stats['conversion_rate'] = (stats['accepted_count'] / stats['total_quotations']) * 100
    
    return JsonResponse(stats)


# Allowed filter values for card modal
QUOTATION_CARD_FILTERS = {
    'all': ('Total Quotations', None),
    'sent': ('Sent', 'sent'),
    'accepted': ('Accepted', 'accepted'),
    'draft': ('Drafts', 'draft'),
    'total_value': ('Total Value', None),
}
# Limit modal records so response is fast (< 200ms)
MODAL_RECORDS_LIMIT = 150
# Only fetch columns needed for modal table (keeps query and JSON small)
MODAL_QUOTATION_ONLY_FIELDS = (
    'id', 'quotation_number', 'quotation_date', 'status', 'grand_total',
    'valid_until', 'created_at', 'client_id', 'created_by_id',
)


@login_required
@permission_required('quotations.view_quotation', raise_exception=True)
def quotation_list_by_filter(request):
    """API: return quotations filtered by card type for modal. Fast path: minimal columns, limited rows."""
    filter_key = (request.GET.get('filter') or 'all').strip().lower()
    if filter_key not in QUOTATION_CARD_FILTERS:
        return JsonResponse({'error': 'Invalid filter'}, status=400)
    
    title, status_filter = QUOTATION_CARD_FILTERS[filter_key]
    base_qs = for_user_queryset(Quotation, request.user, request, account_lookup='account').filter(
        is_deleted=False
    ).only(*MODAL_QUOTATION_ONLY_FIELDS).select_related('client', 'created_by').order_by('-created_at')
    
    if status_filter:
        base_qs = base_qs.filter(status=status_filter)
    
    company_context = get_company_context(request.user, request)
    currency_symbol = company_context.get('currency_symbol') or '₦'
    show_created_by = is_company_admin(request)
    
    # One aggregate for count and/or sum (single DB round-trip)
    from django.db.models import Sum
    agg = base_qs.aggregate(
        total_count=Count('id'),
        total_sum=Sum('grand_total'),
    )
    total_count = agg['total_count'] or 0
    total_sum = agg['total_sum'] or Decimal('0')
    
    if filter_key == 'total_value':
        count_display = format_currency(total_sum, currency_symbol)
    else:
        count_display = str(total_count)
    
    # Fetch only the slice we need (no full table scan for iteration)
    quotations_slice = list(base_qs[:MODAL_RECORDS_LIMIT])
    detail_base = request.build_absolute_uri(
        reverse('quotations:quotation_detail', args=[1])
    ).replace('/1/', '/')
    
    records = []
    for idx, q in enumerate(quotations_slice, 1):
        c = q.client
        client_name = c.name if c else ''
        client_email = getattr(c, 'email', '') or '' if c else ''
        client_address = (getattr(c, 'address', '') or '')[:80] if c else ''
        cb = q.created_by
        created_by_str = (cb.get_full_name() or getattr(cb, 'email', '')) if cb else ''
        records.append({
            'sn': idx,
            'id': q.pk,
            'quotation_number': q.quotation_number or '',
            'client_name': client_name,
            'client_email': client_email,
            'client_address': client_address,
            'quotation_date': q.quotation_date.strftime('%b %d, %Y') if q.quotation_date else '',
            'quotation_date_iso': q.quotation_date.strftime('%Y-%m-%d') if q.quotation_date else '',
            'status': q.status,
            'status_display': q.get_status_display(),
            'grand_total_formatted': format_currency(q.grand_total or 0, currency_symbol),
            'valid_until': q.valid_until.strftime('%b %d, %Y') if q.valid_until else '',
            'valid_until_iso': q.valid_until.strftime('%Y-%m-%d') if q.valid_until else '',
            'created_by': created_by_str,
            'created_at': q.created_at.strftime('%b %d, %Y') if q.created_at else '',
            'detail_url': detail_base + str(q.pk) + '/',
        })
    
    return JsonResponse({
        'title': title,
        'count_display': count_display,
        'filter': filter_key,
        'show_created_by': show_created_by,
        'total_count': total_count,
        'records': records,
    })


@login_required
@permission_required('quotations.add_quotation', raise_exception=True)
def quotation_duplicate(request, pk):
    """Duplicate a quotation"""
    qs = for_user_queryset(Quotation, request.user, request, account_lookup='account').filter(is_deleted=False)
    quotation, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return response
    
    if request.method == 'POST':
        try:
            # Create new quotation with flexible discount/tax types (ownership for per-team-member isolation)
            new_quotation = Quotation.objects.create(
                user=request.user,
                template=quotation.template,
                valid_until=quotation.valid_until,
                client=quotation.client,
                subtotal=quotation.subtotal,
                total_tax=quotation.total_tax,
                tax_type=getattr(quotation, 'tax_type', 'percentage') or 'percentage',
                tax_value=getattr(quotation, 'tax_value', 0) or 0,
                total_discount=quotation.total_discount,
                discount_type=getattr(quotation, 'discount_type', 'percentage') or 'percentage',
                discount_value=getattr(quotation, 'discount_value', 0) or 0,
                shipping_fee=quotation.shipping_fee,
                other_charges=quotation.other_charges,
                grand_total=quotation.grand_total,
                terms=quotation.terms,
                notes=quotation.notes,
                status='draft'
            )
            
            # Copy line items
            for item in quotation.items.all():
                QuotationItem.objects.create(
                    quotation=new_quotation,
                    product_service=item.product_service,
                    description=item.description,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    line_total=item.line_total
                )
            
            messages.success(request, f'Quotation duplicated successfully! New quotation: {new_quotation.quotation_number}')
            return redirect('quotations:quotation_detail', pk=new_quotation.pk)
            
        except Exception as e:
            messages.error(request, f'Error duplicating quotation: {str(e)}')
    
    # Get company context for currency
    company_context = get_company_context(request.user, request)
    
    context = {
        'quotation': quotation,
        'company_profile': company_context['company_profile'],
        'user_currency_symbol': company_context['currency_symbol'],
        'user_currency_code': company_context['currency_code'],
    }
    return render(request, 'quotations/quotation_duplicate.html', context)


@login_required
@company_admin_or_permission_required('quotations.change_quotation', raise_exception=True)
def quotation_bulk_actions(request):
    """Handle bulk actions on quotations (Staff only; respects RBAC)"""
    if request.method == 'POST':
        action = request.POST.get('action')
        quotation_ids = request.POST.getlist('quotation_ids[]')
        
        if not quotation_ids:
            return JsonResponse({'success': False, 'message': 'No quotations selected'})
        
        # Account isolation: only operate on quotations belonging to this account
        quotations = for_user_queryset(Quotation, request.user, request, account_lookup='account').filter(is_deleted=False).filter(pk__in=quotation_ids)
        
        if action == 'delete':
            count = quotations.count()
            quotations.delete()
            return JsonResponse({
                'success': True, 
                'message': f'{count} quotation(s) deleted successfully!'
            })
        
        elif action == 'update_status':
            # Bulk status/approval changes require explicit approval permission
            # (or company admin) even though the overall view uses change_quotation.
            if not (is_company_admin(request) or request.user.has_perm('quotations.can_approve_quotation')):
                return JsonResponse({
                    'success': False,
                    'message': 'You do not have permission to approve quotations.'
                }, status=403)
            new_status = request.POST.get('status')
            if new_status in dict(Quotation.STATUS_CHOICES):
                count = quotations.update(status=new_status)
                return JsonResponse({
                    'success': True,
                    'message': f'Status updated for {count} quotation(s)'
                })
            else:
                return JsonResponse({
                    'success': False,
                    'message': 'Invalid status provided'
                })
        
        elif action == 'export':
            # Handle export logic
            return JsonResponse({
                'success': True,
                'message': f'Exporting {quotations.count()} quotation(s)'
            })
    
    return JsonResponse({'success': False, 'message': 'Invalid request'})


@login_required
@permission_required('quotations.view_quotation', raise_exception=True)
def quotation_preview(request, pk):
    """Preview quotation before sending"""
    qs = for_user_queryset(Quotation, request.user, request, account_lookup='account').filter(is_deleted=False)
    quotation, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return response
    context = get_quotation_context(quotation, request.user, request)
    
    # Get company context for currency
    company_context = get_company_context(request.user, request)
    context.update({
        'user_currency_symbol': company_context['currency_symbol'],
        'user_currency_code': company_context['currency_code'],
    })
    
    return render(request, 'quotations/quotation_preview.html', context)


@login_required
@permission_required('quotations.view_quotation', raise_exception=True)
def quotation_send_email(request, pk):
    """Send quotation via email"""
    qs = for_user_queryset(Quotation, request.user, request, account_lookup='account').filter(is_deleted=False)
    quotation, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return response

    # Get company context for currency and company details
    company_context = get_company_context(request.user, request)
    company_profile = company_context.get('company_profile')
    company_name = getattr(company_profile, 'name', None) or getattr(
        company_profile, 'company_name', ''
    ) or 'Your Company'

    default_to_email = ''
    client = quotation.client
    if client and getattr(client, 'email', None):
        default_to_email = client.email

    default_subject = f"Quotation {quotation.quotation_number} from {company_name}".strip()
    detail_url = request.build_absolute_uri(
        reverse('quotations:quotation_detail', args=[quotation.pk])
    )

    client_name = client.name if client and getattr(client, 'name', None) else ''
    greeting_name = client_name or 'Customer'

    default_message = (
        f"Dear {greeting_name},\n\n"
        f"Please find quotation {quotation.quotation_number} for your review.\n"
        f"You can view it online at: {detail_url}\n\n"
        f"Total amount: {quotation.grand_total}\n\n"
        f"Best regards,\n"
        f"{company_name}"
    )

    if request.method == 'POST':
        to_email = (request.POST.get('to_email') or default_to_email or '').strip()
        subject = (request.POST.get('subject') or default_subject).strip()
        message_body = (request.POST.get('message') or default_message).strip()

        if not to_email:
            messages.error(request, 'Recipient email is required.')
        else:
            from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None) or None
            try:
                send_mail(
                    subject=subject,
                    message=message_body,
                    from_email=from_email,
                    recipient_list=[to_email],
                    fail_silently=False,
                )
                messages.success(
                    request,
                    f'Quotation email sent successfully to {to_email}.',
                )
                return redirect('quotations:quotation_detail', pk=quotation.pk)
            except Exception as exc:
                messages.error(
                    request,
                    f'Error sending email: {exc}',
                )

        # If we reach here, re-render the form with posted values and errors
        context = {
            'quotation': quotation,
            'company_profile': company_profile,
            'user_currency_symbol': company_context['currency_symbol'],
            'user_currency_code': company_context['currency_code'],
            'default_to_email': to_email or default_to_email,
            'default_subject': subject or default_subject,
            'default_message': message_body or default_message,
        }
        return render(request, 'quotations/quotation_send_email.html', context)

    context = {
        'quotation': quotation,
        'company_profile': company_profile,
        'user_currency_symbol': company_context['currency_symbol'],
        'user_currency_code': company_context['currency_code'],
        'default_to_email': default_to_email,
        'default_subject': default_subject,
        'default_message': default_message,
    }
    return render(request, 'quotations/quotation_send_email.html', context)


@login_required
@company_admin_or_permission_required('quotations.download_quotation', raise_exception=True)
def quotation_export_pdf(request):
    """Export quotations list to PDF (requires quotations.download_quotation)"""
    quotations = get_filtered_quotations(request)
    
    # Get company info and currency from company admin settings
    company_context = get_company_context(request.user, request)
    company_profile = company_context.get('company_profile')
    company_logo_base64 = None
    try:
        if company_profile and company_profile.logo:
            logo_path = company_profile.logo.path
            if os.path.isfile(logo_path):
                with open(logo_path, 'rb') as img_file:
                    company_logo_base64 = 'data:image/png;base64,' + base64.b64encode(img_file.read()).decode('utf-8')
    except Exception:
        pass
    currency_symbol = company_context.get('currency_symbol', '₦')
    
    # Calculate totals
    total_amount = quotations.aggregate(total=Sum('grand_total'))['total'] or 0
    
    from apps.accounts.rbac import is_company_admin as _is_company_admin
    context = {
        'quotations': quotations,
        'total_amount': total_amount,
        'company_profile': company_profile,
        'company_logo_base64': company_logo_base64,
        'currency_symbol': currency_symbol,
        'current_date': timezone.now(),
        'user_currency_symbol': company_context['currency_symbol'],
        'user_currency_code': company_context['currency_code'],
        'is_company_admin': _is_company_admin(request),
    }
    
    html_string = render_to_string('quotations/quotation_list_pdf.html', context)
    result = BytesIO()
    pdf = pisa.pisaDocument(BytesIO(html_string.encode("UTF-8")), result)
    
    if not pdf.err:
        response = HttpResponse(result.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename=quotations_list.pdf'
        return response
    else:
        return HttpResponse("Error generating PDF", content_type="text/plain", status=500)


@login_required
@permission_required('quotations.add_quotation', raise_exception=True)
def quotation_debug(request):
    """Debug view to test quotation creation"""
    if request.method == 'POST':
        try:
            # Create a test quotation (ownership for per-team-member isolation)
            quotation = Quotation.objects.create(
                user=request.user,
                quotation_number="TEST-001",
                client=None,
                subtotal=Decimal('1000.00'),
                grand_total=Decimal('1000.00'),
                status='draft'
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Test quotation created: {quotation.quotation_number}',
                'quotation_id': quotation.pk
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Error creating test quotation: {str(e)}'
            })
    
    return render(request, 'quotations/quotation_debug.html')


# Removed @login_required - no permission requirements
def test_quotation_creation(request):
    """Test quotation creation with minimal data"""
    if request.method == 'POST':
        try:
            # Get or create a test client (ownership for per-team-member isolation)
            company_profile = get_company_profile_for_user(request.user, request)
            client, created = Client.objects.get_or_create(
                name="Test Client",
                defaults={
                    'email': 'test@example.com',
                    'phone': '1234567890',
                    'company': company_profile,
                    'created_by': request.user,
                }
            )
            
            # Create quotation (ownership for per-team-member isolation)
            quotation = Quotation.objects.create(
                user=request.user,
                client=client,
                subtotal=Decimal('500.00'),
                grand_total=Decimal('500.00'),
                status='draft'
            )
            
            # Add a line item
            QuotationItem.objects.create(
                quotation=quotation,
                product_service="Test Product",
                description="Test Description",
                quantity=1,
                unit_price=Decimal('500.00'),
                line_total=Decimal('500.00')
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Test quotation created successfully: {quotation.quotation_number}',
                'quotation_id': quotation.pk
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Error: {str(e)}'
            })
    
    return render(request, 'quotations/test_quotation.html')


# Removed @login_required - no permission requirements
def test_simple_quotation(request):
    """Create a simple test quotation"""
    try:
        # Create quotation without client (ownership when authenticated)
        user = getattr(request, 'user', None)
        user = user if (user and getattr(user, 'is_authenticated', False)) else None
        quotation = Quotation.objects.create(
            user=user,
            subtotal=Decimal('100.00'),
            grand_total=Decimal('100.00'),
            status='draft'
        )
        
        # Add line item
        QuotationItem.objects.create(
            quotation=quotation,
            product_service="Simple Test Product",
            quantity=1,
            unit_price=Decimal('100.00'),
            line_total=Decimal('100.00')
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Simple quotation created: {quotation.quotation_number}',
            'quotation_id': quotation.pk
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        })


# Ajax endpoints for enhanced quotation form functionality

@login_required
@company_admin_or_permission_required('quotations.change_quotation', raise_exception=True)
@require_http_methods(["POST"])
def ajax_add_line_item(request):
    """Ajax endpoint to add a new line item to quotation form"""
    try:
        data = json.loads(request.body)
        
        # Get the current form count
        form_count = data.get('form_count', 0)
        
        # Create a new line item form
        formset = QuotationItemFormSet(instance=Quotation())
        new_form = formset.empty_form
        
        # Update form indices
        new_form_html = str(new_form).replace('__prefix__', str(form_count))
        
        return JsonResponse({
            'success': True,
            'form_html': new_form_html,
            'form_count': form_count + 1
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error adding line item: {str(e)}'
        })


@login_required
@permission_required('quotations.view_quotation', raise_exception=True)
@require_http_methods(["POST"])
def ajax_calculate_totals(request):
    """Ajax endpoint to calculate quotation totals"""
    try:
        data = json.loads(request.body)
        
        # Extract line items data
        line_items = data.get('line_items', [])
        additional_charges = data.get('additional_charges', {})
        
        # Calculate subtotal
        subtotal = Decimal('0.00')
        for item in line_items:
            if item.get('quantity') and item.get('unit_price'):
                quantity = Decimal(str(item['quantity']))
                unit_price = Decimal(str(item['unit_price']))
                subtotal += quantity * unit_price
        
        # Calculate additional charges
        tax = Decimal(str(additional_charges.get('tax', 0)))
        discount = Decimal(str(additional_charges.get('discount', 0)))
        shipping = Decimal(str(additional_charges.get('shipping', 0)))
        other = Decimal(str(additional_charges.get('other', 0)))
        
        # Calculate grand total
        grand_total = subtotal + tax + shipping + other - discount
        
        return JsonResponse({
            'success': True,
            'subtotal': float(subtotal),
            'tax': float(tax),
            'discount': float(discount),
            'shipping': float(shipping),
            'other_charges': float(other),
            'grand_total': float(grand_total),
            'amount_in_words': number_to_words(grand_total)
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error calculating totals: {str(e)}'
        })


@login_required
@permission_required('quotations.add_quotation', raise_exception=True)
@require_http_methods(["POST"])
def ajax_save_quotation_draft(request):
    """Ajax endpoint to save quotation as draft"""
    try:
        data = json.loads(request.body)
        
        # Create quotation form
        form = QuotationForm(data.get('quotation_data', {}))
        
        if form.is_valid():
            quotation = form.save(commit=False)
            quotation.user = request.user
            quotation.status = 'draft'
            quotation.save()
            
            # Save line items
            line_items_data = data.get('line_items', [])
            for item_data in line_items_data:
                if item_data.get('product_service') and item_data.get('quantity') and item_data.get('unit_price'):
                    QuotationItem.objects.create(
                        quotation=quotation,
                        product_service=item_data['product_service'],
                        description=item_data.get('description', ''),
                        quantity=Decimal(str(item_data['quantity'])),
                        unit_price=Decimal(str(item_data['unit_price']))
                    )
            
            # Calculate totals
            quotation.calculate_totals()
            
            return JsonResponse({
                'success': True,
                'quotation_id': quotation.pk,
                'quotation_number': quotation.quotation_number,
                'message': 'Quotation saved as draft successfully'
            })
        else:
            return JsonResponse({
                'success': False,
                'message': 'Form validation failed',
                'errors': form.errors
            })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error saving draft: {str(e)}'
        })


@login_required
@permission_required('quotations.view_quotation', raise_exception=True)
@require_http_methods(["POST"])
def ajax_validate_line_item(request):
    """Ajax endpoint to validate line item data"""
    try:
        data = json.loads(request.body)
        
        # Validate required fields
        required_fields = ['product_service', 'quantity', 'unit_price']
        errors = {}
        
        for field in required_fields:
            if not data.get(field):
                errors[field] = f'{field.replace("_", " ").title()} is required'
        
        # Validate numeric fields
        try:
            quantity = float(data.get('quantity', 0))
            if quantity < 0:
                errors['quantity'] = 'Quantity must be positive'
        except (ValueError, TypeError):
            errors['quantity'] = 'Quantity must be a valid number'
        
        try:
            unit_price = float(data.get('unit_price', 0))
            if unit_price < 0:
                errors['unit_price'] = 'Unit price must be positive'
        except (ValueError, TypeError):
            errors['unit_price'] = 'Unit price must be a valid number'
        
        # Calculate line total
        line_total = 0
        if not errors:
            line_total = quantity * unit_price
        
        return JsonResponse({
            'success': len(errors) == 0,
            'errors': errors,
            'line_total': line_total
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error validating line item: {str(e)}'
        })


@login_required
@permission_required('quotations.view_quotation', raise_exception=True)
@require_http_methods(["GET"])
def ajax_get_client_details(request, client_id):
    """Ajax endpoint to get client details. Visibility-scoped: only clients visible to the user."""
    try:
        qs = for_user_queryset(Client, request.user, request, account_lookup='company__account')
        client = get_object_or_404(qs, id=client_id)
        return JsonResponse({
            'success': True,
            'client': {
                'id': client.id,
                'name': client.name,
                'email': client.email,
                'phone': client.phone,
                'address': client.address,
                'city': getattr(client, 'city', ''),
                'state': getattr(client, 'state', ''),
                'country': getattr(client, 'country', ''),
                'postal_code': getattr(client, 'postal_code', '')
            }
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error getting client details: {str(e)}'
        })


@login_required
@permission_required('quotations.view_quotation', raise_exception=True)
def debug_quotation(request, pk):
    """Debug view for a specific quotation"""
    try:
        qs = for_user_queryset(Quotation, request.user, request, account_lookup='account').filter(is_deleted=False)
        quotation, response = get_object_or_unauthorized(request, qs, pk=pk)
        if response:
            return response
        debug_info = {
            'quotation_id': quotation.pk,
            'quotation_number': quotation.quotation_number,
            'user_id': quotation.user.id,
            'client_id': quotation.client.id if quotation.client else None,
            'template_id': quotation.template.id if quotation.template else None,
            'status': quotation.status,
            'subtotal': float(quotation.subtotal),
            'grand_total': float(quotation.grand_total),
            'items_count': quotation.items.count(),
            'created_at': quotation.created_at.isoformat(),
            'updated_at': quotation.updated_at.isoformat(),
        }
        
        return JsonResponse({
            'success': True,
            'debug_info': debug_info
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        })


# Ajax endpoints for enhanced quotation form functionality

@login_required
@permission_required('quotations.add_quotation', raise_exception=True)
@require_http_methods(["POST"])
def test_quotation_state(request):
    """Test quotation state and calculations"""
    try:
        # Create a test quotation (ownership for per-team-member isolation)
        user = getattr(request, 'user', None)
        user = user if (user and getattr(user, 'is_authenticated', False)) else None
        quotation = Quotation.objects.create(
            user=user,
            subtotal=Decimal('1000.00'),
            total_tax=Decimal('100.00'),
            total_discount=Decimal('50.00'),
            shipping_fee=Decimal('25.00'),
            other_charges=Decimal('10.00'),
            grand_total=Decimal('1085.00'),
            status='draft'
        )
        
        # Test calculations
        calculated_total = (
            quotation.subtotal + 
            quotation.total_tax + 
            quotation.shipping_fee + 
            quotation.other_charges - 
            quotation.total_discount
        )
        
        return JsonResponse({
            'success': True,
            'quotation_id': quotation.pk,
            'quotation_number': quotation.quotation_number,
            'subtotal': float(quotation.subtotal),
            'tax': float(quotation.total_tax),
            'discount': float(quotation.total_discount),
            'shipping': float(quotation.shipping_fee),
            'other_charges': float(quotation.other_charges),
            'grand_total': float(quotation.grand_total),
            'calculated_total': float(calculated_total),
            'calculation_correct': quotation.grand_total == calculated_total
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        })


# Ajax endpoints for enhanced quotation form functionality

@login_required
@permission_required('quotations.view_quotation', raise_exception=True)
@require_http_methods(["GET"])
def ajax_get_client_details(request, client_id):
    """Ajax endpoint to get client details. Visibility-scoped: only clients visible to the user."""
    try:
        qs = for_user_queryset(Client, request.user, request, account_lookup='company__account')
        client = get_object_or_404(qs, id=client_id)
        return JsonResponse({
            "success": True,
            "client": {
                "id": client.id,
                "name": client.name,
                "email": client.email,
                "phone": client.phone,
                "address": client.address,
                "city": getattr(client, 'city', ''),
                "state": getattr(client, 'state', ''),
                "country": getattr(client, 'country', ''),
                "postal_code": getattr(client, 'postal_code', '')
            }
        })
    except Exception as e:
        return JsonResponse({
            "success": False,
            "message": f"Error getting client details: {str(e)}"
        })
