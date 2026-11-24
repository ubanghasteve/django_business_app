# -*- coding: utf-8 -*-
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from business_app.views import get_object_or_unauthorized
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_http_methods, require_POST
from apps.core.permissions import company_admin_or_permission_required
from django.db.models import Q
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.views.decorators.cache import never_cache
from django.utils import timezone

from .models import Requisition
from .forms import RequisitionForm, RequisitionFilterForm
from apps.core.ownership import for_user_queryset
from apps.core.utils import get_company_profile_for_user, get_account_users_for_filter, apply_no_cache_headers
from apps.accounts.rbac import is_company_admin as is_company_admin_fn


def get_filtered_requisitions(request):
    """Requisition queryset scoped to user's company (account) and visibility (admin sees all, team sees own)."""
    qs = for_user_queryset(
        Requisition, request.user, request, account_lookup='account'
    ).select_related('created_by', 'approved_by', 'company')
    filter_form = RequisitionFilterForm(request.GET)
    if is_company_admin_fn(request):
        filter_form.fields['created_by'].queryset = get_account_users_for_filter(request.user)
    if filter_form.is_valid():
        search = filter_form.cleaned_data.get('search')
        status = filter_form.cleaned_data.get('status')
        date_from = filter_form.cleaned_data.get('date_from')
        date_to = filter_form.cleaned_data.get('date_to')
        if search:
            search_term = search.strip()
            if search_term:
                qs = qs.filter(
                    Q(reference_number__icontains=search_term) |
                    Q(organization_name__icontains=search_term) |
                    Q(contact_number__icontains=search_term) |
                    Q(job_type__icontains=search_term) |
                    Q(print_product__icontains=search_term) |
                    Q(quantity__icontains=search_term) |
                    Q(other_info__icontains=search_term)
                )
        if status:
            qs = qs.filter(status=status)
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        if is_company_admin_fn(request) and filter_form.cleaned_data.get('created_by'):
            qs = qs.filter(created_by=filter_form.cleaned_data['created_by'])
    return qs


def get_requisition_context(requisition, user, request=None):
    """Context for requisition detail/print using company profile. Pass request so team members get account company."""
    from apps.core.utils import get_company_profile_for_user
    company_profile = get_company_profile_for_user(user, request)
    company_logo = company_profile.logo.url if company_profile and company_profile.logo else None
    company_signature = company_profile.signature.url if company_profile and company_profile.signature else None
    theme_primary_color = getattr(company_profile, 'primary_color', '#1976d2') if company_profile else '#1976d2'
    theme_secondary_color = getattr(company_profile, 'secondary_color', '#f8f9fa') if company_profile else '#f8f9fa'
    theme_accent_color = getattr(company_profile, 'accent_color', '#e9ecef') if company_profile else '#e9ecef'
    theme_text_color = getattr(company_profile, 'text_color', '#333333') if company_profile else '#333333'
    return {
        'requisition': requisition,
        'company_profile': company_profile,
        'company_logo': company_logo,
        'company_signature': company_signature,
        'theme_primary_color': theme_primary_color,
        'theme_secondary_color': theme_secondary_color,
        'theme_accent_color': theme_accent_color,
        'theme_text_color': theme_text_color,
    }


@login_required
@company_admin_or_permission_required('requisitions.view_requisition', raise_exception=True)
@never_cache
def requisition_list_modal(request):
    """Return HTML fragment for the stat-card modal: requisitions filtered by status and search (no layout)."""
    requisitions_qs = get_filtered_requisitions(request)
    status = (request.GET.get('status') or '').strip().lower()
    if status:
        valid = [c[0] for c in Requisition.STATUS_CHOICES]
        if status in valid:
            requisitions_qs = requisitions_qs.filter(status=status)
    total_count = requisitions_qs.count()
    requisitions_list = list(requisitions_qs[:50])
    status_label = dict(Requisition.STATUS_CHOICES).get(status, 'All') if status else 'All'
    context = {
        'requisitions': requisitions_list,
        'total_count': total_count,
        'status': status,
        'status_label': status_label,
        'status_choices': Requisition.STATUS_CHOICES,
        'show_created_by': is_company_admin_fn(request),  # Filter dropdown: admin only
        'show_created_by_column': True,  # Table column: all users who can view list (admin and read-only)
    }
    response = render(request, 'requisitions/requisition_list_modal_content.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('requisitions.view_requisition', raise_exception=True)
@never_cache
def requisition_list(request):
    """List requisitions with search, filter, pagination. Company isolation applied."""
    requisitions = get_filtered_requisitions(request)
    filter_form = RequisitionFilterForm(request.GET)
    if is_company_admin_fn(request):
        filter_form.fields['created_by'].queryset = get_account_users_for_filter(request.user)
    paginator = Paginator(requisitions, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    company_profile = get_company_profile_for_user(request.user, request)
    # Status counts for stats cards (from base filtered queryset)
    total_requisitions = requisitions.count()
    draft_count = requisitions.filter(status='draft').count()
    pending_count = requisitions.filter(status='pending').count()
    approved_count = requisitions.filter(status='approved').count()
    completed_count = requisitions.filter(status='completed').count()
    rejected_count = requisitions.filter(status='rejected').count()
    context = {
        'page_obj': page_obj,
        'filter_form': filter_form,
        'total_requisitions': total_requisitions,
        'draft_count': draft_count,
        'pending_count': pending_count,
        'approved_count': approved_count,
        'completed_count': completed_count,
        'rejected_count': rejected_count,
        'show_created_by': is_company_admin_fn(request),  # Filter dropdown: admin only
        'show_created_by_column': True,  # Table column: all users who can view list (admin and read-only)
        'is_company_admin': is_company_admin_fn(request),
        'status_choices': Requisition.STATUS_CHOICES,
        'theme_primary_color': getattr(company_profile, 'primary_color', '#1976d2') if company_profile else '#1976d2',
        'theme_secondary_color': getattr(company_profile, 'secondary_color', '#f8f9fa') if company_profile else '#f8f9fa',
        'theme_text_color': getattr(company_profile, 'text_color', '#333333') if company_profile else '#333333',
        'theme_accent_color': getattr(company_profile, 'accent_color', '#e9ecef') if company_profile else '#e9ecef',
    }
    response = render(request, 'requisitions/requisition_list.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('requisitions.view_requisition', raise_exception=True)
def requisition_detail(request, pk):
    """Detail view for a single requisition. Company isolation applied."""
    qs = for_user_queryset(Requisition, request.user, request, account_lookup='account').select_related('created_by', 'approved_by', 'company')
    requisition, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return response
    context = get_requisition_context(requisition, request.user, request)
    if requisition.signature:
        context['requisition_signature_url'] = request.build_absolute_uri(requisition.signature.url)
    else:
        context['requisition_signature_url'] = None
    response = render(request, 'requisitions/requisition_detail.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('requisitions.add_requisition', raise_exception=True)
@require_http_methods(['GET', 'POST'])
def requisition_create(request):
    """Create new requisition. Sets account, company, created_by from request.user."""
    if request.method == 'POST':
        form = RequisitionForm(request.POST, request.FILES)
        if form.is_valid():
            requisition = form.save(commit=False)
            requisition.created_by = request.user
            if getattr(request.user, 'account_id', None):
                requisition.account_id = request.user.account_id
            company = get_company_profile_for_user(request.user, request)
            if company:
                requisition.company_id = company.pk
            requisition.save()
            messages.success(request, f'Requisition {requisition.reference_number} created successfully.')
            return redirect('requisitions:detail', pk=requisition.pk)
    else:
        form = RequisitionForm(initial={'status': 'draft'})
    company_profile = get_company_profile_for_user(request.user, request)
    company_logo = company_profile.logo.url if company_profile and company_profile.logo else None
    context = {
        'form': form,
        'title': 'Create Requisition',
        'requisition': None,
        'company_profile': company_profile,
        'company_logo': company_logo,
        'theme_primary_color': getattr(company_profile, 'primary_color', '#1976d2') if company_profile else '#1976d2',
        'theme_secondary_color': getattr(company_profile, 'secondary_color', '#f8f9fa') if company_profile else '#f8f9fa',
        'theme_text_color': getattr(company_profile, 'text_color', '#333333') if company_profile else '#333333',
        'theme_accent_color': getattr(company_profile, 'accent_color', '#e9ecef') if company_profile else '#e9ecef',
    }
    response = render(request, 'requisitions/requisition_create.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('requisitions.change_requisition', raise_exception=True)
@require_http_methods(['GET', 'POST'])
def requisition_edit(request, pk):
    """Edit requisition. Company isolation applied."""
    qs = for_user_queryset(Requisition, request.user, request, account_lookup='account')
    requisition, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return response
    if request.method == 'POST':
        form = RequisitionForm(request.POST, request.FILES, instance=requisition)
        if form.is_valid():
            form.save()
            messages.success(request, f'Requisition {requisition.reference_number} updated successfully.')
            return redirect('requisitions:detail', pk=requisition.pk)
    else:
        form = RequisitionForm(instance=requisition)
    context = get_requisition_context(requisition, request.user, request)
    context['form'] = form
    context['title'] = 'Edit Requisition'
    response = render(request, 'requisitions/requisition_create.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('requisitions.delete_requisition', raise_exception=True)
@require_http_methods(['GET', 'POST'])
def requisition_delete(request, pk):
    """Delete requisition with confirmation. Company isolation applied."""
    qs = for_user_queryset(Requisition, request.user, request, account_lookup='account')
    requisition, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return response
    if request.method == 'POST':
        ref = requisition.reference_number
        requisition.delete()
        messages.success(request, f'Requisition {ref} deleted successfully.')
        return redirect('requisitions:list')
    response = render(request, 'requisitions/requisition_confirm_delete.html', {'requisition': requisition})
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('requisitions.print_requisition', raise_exception=True)
def requisition_print(request, pk):
    """Print-friendly requisition view. Company isolation applied."""
    qs = for_user_queryset(Requisition, request.user, request, account_lookup='account').select_related('created_by', 'approved_by', 'company')
    requisition, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return response
    context = get_requisition_context(requisition, request.user, request)
    if requisition.signature:
        context['requisition_signature_url'] = request.build_absolute_uri(requisition.signature.url)
    else:
        context['requisition_signature_url'] = None
    if context.get('company_logo'):
        context['company_logo_url'] = request.build_absolute_uri(context['company_logo'])
    response = render(request, 'requisitions/requisition_print.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('requisitions.print_requisition', raise_exception=True)
def requisition_pdf(request, pk):
    """Redirect to print view (user can save as PDF from browser)."""
    return redirect('requisitions:print', pk=pk)


@login_required
@company_admin_or_permission_required('requisitions.can_approve_requisition', raise_exception=True)
@require_POST
def requisition_update_status(request, pk):
    """Update requisition status from the list table (AJAX). Saves to DB; detail/print/edit show new status on next load."""
    qs = for_user_queryset(Requisition, request.user, request, account_lookup='account')
    requisition, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return JsonResponse({'success': False, 'error': 'Not found or access denied'}, status=403)
    status = (request.POST.get('status') or '').strip().lower()
    valid = [c[0] for c in Requisition.STATUS_CHOICES]
    if status not in valid:
        return JsonResponse({'success': False, 'error': 'Invalid status'}, status=400)
    requisition.status = status
    if status == 'approved':
        requisition.approved_by = request.user
        requisition.approved_at = timezone.now()
        requisition.save(update_fields=['status', 'updated_at', 'approved_by', 'approved_at'])
    else:
        requisition.approved_by = None
        requisition.approved_at = None
        requisition.save(update_fields=['status', 'updated_at', 'approved_by', 'approved_at'])
    return JsonResponse({
        'success': True,
        'status': requisition.status,
        'display': requisition.get_status_display(),
    })
