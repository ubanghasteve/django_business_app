# -*- coding: utf-8 -*-
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Q, Sum, Count
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from business_app.views import get_object_or_unauthorized
from apps.core.permissions import (
    company_admin_or_permission_required,
    company_admin_or_any_permission_required,
)
from apps.core.feature_permissions import has_feature_permission
from apps.core.ownership import for_user_queryset, get_account_for_user
from apps.core.utils import (
    get_account_users_for_filter,
    get_company_profile_for_user,
    apply_no_cache_headers,
)
from apps.accounts.rbac import is_company_admin as is_company_admin_fn

from .models import StaffOffenceRegister, StaffOffenceEntry
from .forms import (
    StaffOffenceRegisterForm,
    StaffOffenceEntryForm,
    StaffOffenceRegisterFilterForm,
)


def _base_register_qs(request):
    return for_user_queryset(
        StaffOffenceRegister, request.user, request, account_lookup='account'
    ).select_related('created_by', 'company')


def _filter_choice_options(base_qs):
    departments = list(
        base_qs.exclude(department_name='')
        .order_by('department_name')
        .values_list('department_name', flat=True)
        .distinct()
    )
    from datetime import date
    years = list(
        base_qs.order_by('-year').values_list('year', flat=True).distinct()
    )
    current_year = date.today().year
    if current_year not in years:
        years = [current_year] + years
    return departments, years


def get_filtered_registers(request):
    base_qs = _base_register_qs(request)
    departments, years = _filter_choice_options(base_qs)
    qs = base_qs.annotate(
        entry_count=Count('entries', filter=Q(entries__is_deleted=False)),
        total_amount=Sum('entries__amount', filter=Q(entries__is_deleted=False)),
    ).order_by('year', 'month', 'created_at', 'id')
    filter_form = StaffOffenceRegisterFilterForm(
        request.GET,
        department_choices=departments,
        year_choices=years,
    )
    if is_company_admin_fn(request):
        filter_form.fields['created_by'].queryset = get_account_users_for_filter(request.user)
    if filter_form.is_valid():
        search = (filter_form.cleaned_data.get('search') or '').strip()
        year_raw = filter_form.cleaned_data.get('year')
        month_raw = filter_form.cleaned_data.get('month')
        department = (filter_form.cleaned_data.get('department') or '').strip()
        if search:
            # Smart match: each typed token must appear in staff, department, or record no.
            for term in search.split():
                if not term:
                    continue
                qs = qs.filter(
                    Q(reference_number__icontains=term)
                    | Q(department_name__icontains=term)
                    | Q(staff_name__icontains=term)
                )
        if department:
            qs = qs.filter(department_name__iexact=department)
        if year_raw:
            try:
                qs = qs.filter(year=int(year_raw))
            except (TypeError, ValueError):
                pass
        if month_raw:
            try:
                qs = qs.filter(month=int(month_raw))
            except (TypeError, ValueError):
                pass
        if is_company_admin_fn(request) and filter_form.cleaned_data.get('created_by'):
            qs = qs.filter(created_by=filter_form.cleaned_data['created_by'])
        payment_status = (filter_form.cleaned_data.get('payment_status') or '').strip()
        if payment_status:
            qs = qs.filter(payment_status=payment_status)
    return qs, filter_form, base_qs


def _list_summary_stats(base_qs, currency_symbol='₦'):
    """Global summary cards (not affected by search filters)."""
    from datetime import date
    today = date.today()
    total_registers = base_qs.count()
    this_month_qs = base_qs.filter(year=today.year, month=today.month)
    this_month_offences = (
        StaffOffenceEntry.objects.filter(
            register__in=this_month_qs,
            is_deleted=False,
        ).count()
    )
    this_month_penalties = (
        StaffOffenceEntry.objects.filter(
            register__in=this_month_qs,
            is_deleted=False,
        ).aggregate(s=Sum('amount')).get('s')
    ) or Decimal('0.00')
    return {
        'total_registers': total_registers,
        'this_month_offences': this_month_offences,
        'this_month_penalties': this_month_penalties,
        'this_month_penalties_display': f'{this_month_penalties:,.0f}',
        'this_month_label': today.strftime('%B %Y'),
        'currency_symbol': currency_symbol,
    }


def _payment_status_payload(register):
    return {
        'payment_status': register.payment_status,
        'payment_status_label': register.payment_status_label,
        'payment_status_help': register.payment_status_help,
    }


def _register_list_row(reg, currency_symbol='₦'):
    total = reg.total_amount if reg.total_amount is not None else Decimal('0.00')
    row = {
        'id': reg.pk,
        'reference_number': reg.reference_number,
        'staff_name': reg.staff_name,
        'department_name': reg.department_name or '',
        'month': reg.month,
        'year': reg.year,
        'month_label': reg.month_label,
        'month_short': f'{reg.month_label[:3]} {reg.year}' if reg.month_label else f'{reg.month}/{reg.year}',
        'entry_count': reg.entry_count or 0,
        'total_amount': str(total),
        'total_amount_display': f'{total:,.0f}',
        'created_by': (
            reg.created_by.get_full_name() or str(reg.created_by)
            if reg.created_by_id else ''
        ),
        'detail_url': f'/staff-offences/{reg.pk}/',
        'print_url': f'/staff-offences/{reg.pk}/print/',
        'pdf_url': f'/staff-offences/{reg.pk}/pdf/',
        'payment_status_url': f'/staff-offences/{reg.pk}/payment-status/',
    }
    row.update(_payment_status_payload(reg))
    return row


def get_register_context(register, user, request=None):
    company_profile = get_company_profile_for_user(user, request)
    company_logo = company_profile.logo.url if company_profile and company_profile.logo else None
    signature_url = None
    if register and register.authorized_signature:
        signature_url = register.authorized_signature.url
        if request:
            signature_url = request.build_absolute_uri(signature_url)
    return {
        'register': register,
        'company_profile': company_profile,
        'company_logo': company_logo,
        'authorized_signature_url': signature_url,
        'authorized_signatory_name': (
            (register.authorized_signatory_name or '').strip()
            or (
                register.created_by.get_full_name() or str(register.created_by)
                if register and register.created_by_id else ''
            )
        ) if register else '',
        'theme_primary_color': getattr(company_profile, 'primary_color', '#f97316') if company_profile else '#f97316',
        'theme_secondary_color': getattr(company_profile, 'secondary_color', '#fff7ed') if company_profile else '#fff7ed',
        'theme_accent_color': getattr(company_profile, 'accent_color', '#ffedd5') if company_profile else '#ffedd5',
        'theme_text_color': getattr(company_profile, 'text_color', '#111827') if company_profile else '#111827',
        'currency_symbol': getattr(company_profile, 'currency_symbol', None) or '₦',
    }


def _active_entries(register):
    return register.entries.filter(is_deleted=False).order_by('date', 'id')


@login_required
@company_admin_or_permission_required('staff_offences.view_staffoffenceregister', raise_exception=True)
@never_cache
def register_list(request):
    filtered = get_filtered_registers(request)
    registers = filtered[0]
    filter_form = filtered[1]
    base_qs = filtered[2]
    paginator = Paginator(registers, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    company_profile = get_company_profile_for_user(request.user, request)
    currency_symbol = getattr(company_profile, 'currency_symbol', None) or '₦'
    summary = _list_summary_stats(base_qs, currency_symbol)
    admin = is_company_admin_fn(request)
    can_add = request.user.has_perm('staff_offences.add_staffoffenceregister') or admin
    can_change = request.user.has_perm('staff_offences.change_staffoffenceregister') or admin
    can_print = request.user.has_perm('staff_offences.print_staffoffenceregister') or admin
    can_download = request.user.has_perm('staff_offences.download_staffoffenceregister') or admin
    can_delete = request.user.has_perm('staff_offences.delete_staffoffenceregister') or admin
    can_add_entries = has_feature_permission(request.user, 'staff_offences.add_entry') or admin
    can_change_entries = has_feature_permission(request.user, 'staff_offences.change_entry') or admin
    can_delete_entries = has_feature_permission(request.user, 'staff_offences.delete_entry') or admin

    # Live refresh for the redesigned list (keeps table + summary in sync).
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        start = page_obj.start_index() if page_obj.paginator.count else 0
        rows = []
        for offset, reg in enumerate(page_obj.object_list):
            row = _register_list_row(reg, currency_symbol)
            row['sn'] = start + offset
            row['delete_url'] = f'/staff-offences/{reg.pk}/delete/'
            rows.append(row)
        row_sig = '|'.join(
            f"{r['id']}:{r['entry_count']}:{r['total_amount_display']}:{r['payment_status']}"
            for r in rows
        )
        sync_token = (
            f"{summary['total_registers']}:{summary['this_month_offences']}:"
            f"{summary['this_month_penalties_display']}:{page_obj.paginator.count}:"
            f"{page_obj.number}:{row_sig}"
        )
        return JsonResponse({
            'success': True,
            'summary': summary,
            'rows': rows,
            'sync_token': sync_token,
            'server_time': timezone.now().isoformat(),
            'pagination': {
                'number': page_obj.number,
                'num_pages': page_obj.paginator.num_pages,
                'has_previous': page_obj.has_previous(),
                'has_next': page_obj.has_next(),
                'previous_page_number': page_obj.previous_page_number() if page_obj.has_previous() else None,
                'next_page_number': page_obj.next_page_number() if page_obj.has_next() else None,
                'start_index': start,
                'end_index': page_obj.end_index() if page_obj.paginator.count else 0,
                'total': page_obj.paginator.count,
            },
            'permissions': {
                'can_add': can_add,
                'can_change': can_change,
                'can_print': can_print,
                'can_download': can_download,
                'can_delete': can_delete,
                'can_add_entries': can_add_entries,
                'can_change_entries': can_change_entries,
                'can_delete_entries': can_delete_entries,
                'show_created_by': admin,
            },
        })

    context = {
        'page_obj': page_obj,
        'filter_form': filter_form,
        'total_registers': summary['total_registers'],
        'this_month_offences': summary['this_month_offences'],
        'this_month_penalties': summary['this_month_penalties'],
        'this_month_label': summary['this_month_label'],
        'show_created_by': admin,
        'is_company_admin': admin,
        'can_add': can_add,
        'can_change': can_change,
        'can_print': can_print,
        'can_download': can_download,
        'can_delete': can_delete,
        'can_add_entries': can_add_entries,
        'can_change_entries': can_change_entries,
        'can_delete_entries': can_delete_entries,
        'payment_status_choices': StaffOffenceRegister.PAYMENT_STATUS_CHOICES,
        'payment_status_help_map': StaffOffenceRegister.PAYMENT_STATUS_HELP,
        'theme_primary_color': getattr(company_profile, 'primary_color', '#f97316') if company_profile else '#f97316',
        'theme_secondary_color': getattr(company_profile, 'secondary_color', '#fff7ed') if company_profile else '#fff7ed',
        'theme_text_color': getattr(company_profile, 'text_color', '#111827') if company_profile else '#111827',
        'theme_accent_color': getattr(company_profile, 'accent_color', '#ffedd5') if company_profile else '#ffedd5',
        'currency_symbol': currency_symbol,
    }
    response = render(request, 'staff_offences/register_list.html', context)
    apply_no_cache_headers(response)
    return response


def _workspace_theme_context(request):
    company_profile = get_company_profile_for_user(request.user, request)
    return {
        'company_profile': company_profile,
        'theme_primary_color': getattr(company_profile, 'primary_color', '#f97316') if company_profile else '#f97316',
        'theme_secondary_color': getattr(company_profile, 'secondary_color', '#fff7ed') if company_profile else '#fff7ed',
        'theme_text_color': getattr(company_profile, 'text_color', '#111827') if company_profile else '#111827',
        'theme_accent_color': getattr(company_profile, 'accent_color', '#ffedd5') if company_profile else '#ffedd5',
        'currency_symbol': getattr(company_profile, 'currency_symbol', None) or '₦',
    }


def _entry_payload(entry):
    return {
        'id': entry.pk,
        'date': entry.date.strftime('%d %b'),
        'date_iso': entry.date.isoformat(),
        'description': entry.description,
        'amount': str(entry.amount),
        'amount_display': f'{entry.amount:,.0f}',
    }


def _register_json(register):
    entries = list(_active_entries(register))
    monthly_total = sum((e.amount for e in entries), Decimal('0.00'))
    signature_url = register.authorized_signature.url if register.authorized_signature else ''
    signatory = (register.authorized_signatory_name or '').strip()
    if not signatory and register.created_by_id:
        signatory = register.created_by.get_full_name() or str(register.created_by)
    return {
        'id': register.pk,
        'reference_number': register.reference_number,
        'staff_name': register.staff_name,
        'department_name': register.department_name or '',
        'year': register.year,
        'month': register.month,
        'month_label': register.month_label,
        'offence_count': len(entries),
        'monthly_total': str(monthly_total),
        'monthly_total_display': f'{monthly_total:,.0f}',
        'entries': [_entry_payload(e) for e in entries],
        'authorized_signature_url': signature_url,
        'authorized_signatory_name': signatory,
        'payment_status': register.payment_status,
        'payment_status_label': register.payment_status_label,
        'payment_status_help': register.payment_status_help,
        'print_url': f'/staff-offences/{register.pk}/print/',
        'pdf_url': f'/staff-offences/{register.pk}/pdf/',
        'detail_url': f'/staff-offences/{register.pk}/',
        'signature_upload_url': f'/staff-offences/{register.pk}/signature/',
        'signature_clear_url': f'/staff-offences/{register.pk}/signature/clear/',
        'payment_status_url': f'/staff-offences/{register.pk}/payment-status/',
    }


def _create_or_get_register(request, form):
    """Create register from valid form, or return existing same staff/month."""
    register = form.save(commit=False)
    register.created_by = request.user
    acc = get_account_for_user(request.user)
    if acc:
        register.account_id = acc.id
    company = get_company_profile_for_user(request.user, request)
    if company:
        register.company_id = company.pk
    try:
        register.save()
        created = True
    except IntegrityError:
        register = StaffOffenceRegister.objects.filter(
            account_id=register.account_id,
            staff_name__iexact=register.staff_name,
            year=register.year,
            month=register.month,
        ).first()
        created = False
        if not register:
            raise
    return register, created


def _workspace_perm_flags(request):
    admin = is_company_admin_fn(request)
    can_change_register = request.user.has_perm('staff_offences.change_staffoffenceregister') or admin
    return {
        'can_add_register': request.user.has_perm('staff_offences.add_staffoffenceregister') or admin,
        'can_change_register': can_change_register,
        # Entry actions: dedicated entry perm OR register change (umbrella) OR company admin
        'can_add_entries': has_feature_permission(request.user, 'staff_offences.add_entry') or admin,
        'can_change_entries': has_feature_permission(request.user, 'staff_offences.change_entry') or admin,
        'can_delete_entries': has_feature_permission(request.user, 'staff_offences.delete_entry') or admin,
        'can_print': request.user.has_perm('staff_offences.print_staffoffenceregister') or admin,
        'can_download': request.user.has_perm('staff_offences.download_staffoffenceregister') or admin,
        'can_delete_register': request.user.has_perm('staff_offences.delete_staffoffenceregister') or admin,
    }


def _render_workspace(request, *, form, register=None, workspace_mode='create', title='Create Offence'):
    entries = list(_active_entries(register)) if register else []
    monthly_total = sum((e.amount for e in entries), Decimal('0.00'))
    context = _workspace_theme_context(request)
    if register:
        context.update(get_register_context(register, request.user, request))
    context.update(_workspace_perm_flags(request))
    context.update({
        'form': form,
        'title': title,
        'workspace_mode': workspace_mode,
        'register': register,
        'entries': entries,
        'offence_count': len(entries),
        'monthly_total': monthly_total,
        'register_json': _register_json(register) if register else None,
        'payment_status_choices': StaffOffenceRegister.PAYMENT_STATUS_CHOICES,
        'payment_status_help_map': StaffOffenceRegister.PAYMENT_STATUS_HELP,
    })
    response = render(request, 'staff_offences/register_workspace.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('staff_offences.add_staffoffenceregister', raise_exception=True)
@require_http_methods(['GET', 'POST'])
def register_create(request):
    """Single-page workspace: create register + manage offences without leaving the page."""
    if request.method == 'POST' and request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        form = StaffOffenceRegisterForm(request.POST)
        upload = _get_signature_upload(request)
        signature_error = _validate_signature_upload(upload) if upload else None
        if form.is_valid() and not signature_error:
            register, _created = _create_or_get_register(request, form)
            if upload:
                _apply_authorized_signature(register, upload, request.user)
            # Stay on the same workspace (no separate detail hop for no-JS fallback).
            return _render_workspace(
                request,
                form=StaffOffenceRegisterForm(instance=register),
                register=register,
                workspace_mode='active',
                title='Staff Offence Management',
            )
        if signature_error:
            form.add_error(None, signature_error)
    else:
        form = StaffOffenceRegisterForm()
    return _render_workspace(
        request,
        form=form,
        register=None,
        workspace_mode='create',
        title='Create Offence',
    )


@login_required
@company_admin_or_permission_required('staff_offences.add_staffoffenceregister', raise_exception=True)
@require_POST
def register_create_ajax(request):
    """AJAX: create (or open existing) monthly register — stays on create workspace."""
    form = StaffOffenceRegisterForm(request.POST)
    if not form.is_valid():
        return JsonResponse({'success': False, 'errors': form.errors}, status=400)
    upload = _get_signature_upload(request)
    if upload:
        signature_error = _validate_signature_upload(upload)
        if signature_error:
            return JsonResponse({'success': False, 'error': signature_error}, status=400)
    try:
        register, created = _create_or_get_register(request, form)
    except IntegrityError:
        return JsonResponse({'success': False, 'error': 'Could not create register.'}, status=400)
    if upload:
        _apply_authorized_signature(register, upload, request.user)
    return JsonResponse({
        'success': True,
        'created': created,
        'register': _register_json(register),
    })


@login_required
@company_admin_or_permission_required('staff_offences.view_staffoffenceregister', raise_exception=True)
@never_cache
def register_detail(request, pk):
    """Same single-page workspace, loaded with an existing register."""
    qs = for_user_queryset(
        StaffOffenceRegister, request.user, request, account_lookup='account'
    ).select_related('created_by', 'company')
    register, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return response
    return _render_workspace(
        request,
        form=StaffOffenceRegisterForm(instance=register),
        register=register,
        workspace_mode='active',
        title='Staff Offence Management',
    )


@login_required
@company_admin_or_permission_required('staff_offences.delete_staffoffenceregister', raise_exception=True)
@require_http_methods(['GET', 'POST'])
def register_delete(request, pk):
    qs = for_user_queryset(StaffOffenceRegister, request.user, request, account_lookup='account')
    register, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Not found or access denied'}, status=403)
        return response
    if request.method == 'POST':
        ref = register.reference_number
        register.delete()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'deleted_id': pk,
                'reference_number': ref,
                'message': f'Register {ref} deleted successfully.',
            })
        messages.success(request, f'Register {ref} deleted successfully.')
        return redirect('staff_offences:list')
    response = render(
        request,
        'staff_offences/register_confirm_delete.html',
        {'register': register},
    )
    apply_no_cache_headers(response)
    return response


def _parse_entry_ids(raw):
    """Parse comma/space-separated entry IDs from a query string value."""
    if not raw:
        return None
    ids = []
    seen = set()
    for part in str(raw).replace(' ', ',').split(','):
        part = part.strip()
        if not part:
            continue
        try:
            eid = int(part)
        except (TypeError, ValueError):
            continue
        if eid in seen:
            continue
        seen.add(eid)
        ids.append(eid)
    return ids or None


def _entries_for_print(register, request):
    """
    All active entries, or a subset when ?entries=1,2,3 is provided.
    Returns (entries, is_filtered, total_register_count).
    """
    all_entries = list(_active_entries(register))
    total_count = len(all_entries)
    requested = _parse_entry_ids(
        request.GET.get('entries') or request.GET.get('entry')
    )
    if not requested:
        return all_entries, False, total_count
    wanted = set(requested)
    filtered = [e for e in all_entries if e.pk in wanted]
    # Preserve request order when a subset is chosen
    by_id = {e.pk: e for e in filtered}
    ordered = [by_id[i] for i in requested if i in by_id]
    return ordered, True, total_count


@login_required
@company_admin_or_any_permission_required(
    ['staff_offences.print_staffoffenceregister', 'staff_offences.download_staffoffenceregister'],
    raise_exception=True,
)
def register_print(request, pk):
    qs = for_user_queryset(
        StaffOffenceRegister, request.user, request, account_lookup='account'
    ).select_related('created_by', 'company')
    register, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return response
    entries, is_filtered, total_register_count = _entries_for_print(register, request)
    context = get_register_context(register, request.user, request)
    context.update({
        'entries': entries,
        'offence_count': len(entries),
        'monthly_total': sum((e.amount for e in entries), Decimal('0.00')),
        'print_is_filtered': is_filtered,
        'print_total_register_count': total_register_count,
    })
    if context.get('company_logo'):
        context['company_logo_url'] = request.build_absolute_uri(context['company_logo'])
    response = render(request, 'staff_offences/register_print.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('staff_offences.download_staffoffenceregister', raise_exception=True)
def register_pdf(request, pk):
    from django.urls import reverse
    url = reverse('staff_offences:print', kwargs={'pk': pk})
    qs = request.META.get('QUERY_STRING', '')
    if qs:
        url = f'{url}?{qs}'
    return redirect(url)


ALLOWED_SIGNATURE_CONTENT_TYPES = {
    'image/png', 'image/jpeg', 'image/jpg', 'image/gif', 'image/webp',
}
MAX_SIGNATURE_BYTES = 2 * 1024 * 1024  # 2 MB


def _signature_payload(register):
    signature_url = register.authorized_signature.url if register.authorized_signature else ''
    signatory = (register.authorized_signatory_name or '').strip()
    if not signatory and register.created_by_id:
        signatory = register.created_by.get_full_name() or str(register.created_by)
    return {
        'authorized_signature_url': signature_url,
        'authorized_signatory_name': signatory,
    }


def _get_signature_upload(request):
    return request.FILES.get('authorized_signature') or request.FILES.get('signature')


def _validate_signature_upload(upload):
    """Return an error message if the upload is invalid, else None."""
    if not upload:
        return 'Please choose a signature image.'
    content_type = (getattr(upload, 'content_type', '') or '').lower()
    if content_type and content_type not in ALLOWED_SIGNATURE_CONTENT_TYPES:
        return 'Signature must be a PNG, JPG, GIF, or WebP image.'
    if upload.size and upload.size > MAX_SIGNATURE_BYTES:
        return 'Signature image must be under 2 MB.'
    return None


def _apply_authorized_signature(register, upload, user):
    """Save validated signature onto the register. Caller must validate first."""
    signatory_name = (user.get_full_name() or str(user) or '').strip()
    if register.authorized_signature:
        register.authorized_signature.delete(save=False)
    register.authorized_signature = upload
    register.authorized_signatory_name = signatory_name
    register.save(update_fields=['authorized_signature', 'authorized_signatory_name', 'updated_at'])


@login_required
@company_admin_or_permission_required('staff_offences.change_staffoffenceregister', raise_exception=True)
@require_POST
def payment_status_update_ajax(request, pk):
    """Update payment status for this register; list/workspace/print stay in sync via refresh + BroadcastChannel."""
    qs = for_user_queryset(
        StaffOffenceRegister, request.user, request, account_lookup='account'
    ).select_related('created_by')
    register, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return JsonResponse({'success': False, 'error': 'Not found or access denied'}, status=403)

    new_status = (request.POST.get('payment_status') or '').strip()
    if not new_status and request.body:
        import json
        try:
            payload = json.loads(request.body.decode('utf-8') or '{}')
            new_status = (payload.get('payment_status') or '').strip()
        except (ValueError, TypeError, UnicodeDecodeError):
            new_status = ''

    valid = {c[0] for c in StaffOffenceRegister.PAYMENT_STATUS_CHOICES}
    if new_status not in valid:
        return JsonResponse({
            'success': False,
            'error': 'Invalid payment status.',
            'choices': [
                {'value': v, 'label': l, 'help': StaffOffenceRegister.PAYMENT_STATUS_HELP.get(v, '')}
                for v, l in StaffOffenceRegister.PAYMENT_STATUS_CHOICES
            ],
        }, status=400)

    register.payment_status = new_status
    register.save(update_fields=['payment_status', 'updated_at'])
    return JsonResponse({
        'success': True,
        'message': f'Payment status updated to {register.payment_status_label}.',
        **_payment_status_payload(register),
        'register': _register_json(register),
    })


@login_required
@company_admin_or_permission_required('staff_offences.change_staffoffenceregister', raise_exception=True)
@require_POST
def signature_upload_ajax(request, pk):
    """Upload or replace the authorized signature for this register only."""
    qs = for_user_queryset(
        StaffOffenceRegister, request.user, request, account_lookup='account'
    ).select_related('created_by')
    register, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return JsonResponse({'success': False, 'error': 'Not found or access denied'}, status=403)

    upload = _get_signature_upload(request)
    signature_error = _validate_signature_upload(upload)
    if signature_error:
        return JsonResponse({'success': False, 'error': signature_error}, status=400)

    _apply_authorized_signature(register, upload, request.user)

    return JsonResponse({
        'success': True,
        'message': 'Authorized signature saved for this register.',
        **_signature_payload(register),
        'register': _register_json(register),
    })


@login_required
@company_admin_or_permission_required('staff_offences.change_staffoffenceregister', raise_exception=True)
@require_POST
def signature_clear_ajax(request, pk):
    """Remove the authorized signature from this register only."""
    qs = for_user_queryset(
        StaffOffenceRegister, request.user, request, account_lookup='account'
    ).select_related('created_by')
    register, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return JsonResponse({'success': False, 'error': 'Not found or access denied'}, status=403)

    if register.authorized_signature:
        register.authorized_signature.delete(save=False)
    register.authorized_signature = None
    register.authorized_signatory_name = ''
    register.save(update_fields=['authorized_signature', 'authorized_signatory_name', 'updated_at'])

    return JsonResponse({
        'success': True,
        'message': 'Authorized signature removed.',
        **_signature_payload(register),
        'register': _register_json(register),
    })


@login_required
@company_admin_or_any_permission_required(
    ['staff_offences.add_staffoffenceentry', 'staff_offences.change_staffoffenceregister'],
    raise_exception=True,
)
@require_http_methods(['GET', 'POST'])
def entry_create(request, pk):
    qs = for_user_queryset(StaffOffenceRegister, request.user, request, account_lookup='account')
    register, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return response
    if request.method == 'POST':
        form = StaffOffenceEntryForm(request.POST)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.register = register
            entry.created_by = request.user
            entry.save()
            messages.success(request, 'Offence added successfully.')
            return redirect('staff_offences:detail', pk=register.pk)
        messages.error(request, 'Please correct the errors below.')
    else:
        form = StaffOffenceEntryForm()
    context = get_register_context(register, request.user, request)
    context.update({
        'entry_form': form,
        'form_title': 'Add Offence',
        'form_action': 'create',
    })
    response = render(request, 'staff_offences/entry_form.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_any_permission_required(
    ['staff_offences.change_staffoffenceentry', 'staff_offences.change_staffoffenceregister'],
    raise_exception=True,
)
@require_http_methods(['GET', 'POST'])
def entry_edit(request, pk, entry_pk):
    qs = for_user_queryset(StaffOffenceRegister, request.user, request, account_lookup='account')
    register, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return response
    entry = _active_entries(register).filter(pk=entry_pk).first()
    if not entry:
        messages.error(request, 'Offence entry not found.')
        return redirect('staff_offences:detail', pk=register.pk)
    if request.method == 'POST':
        form = StaffOffenceEntryForm(request.POST, instance=entry)
        if form.is_valid():
            form.save()
            messages.success(request, 'Offence updated successfully.')
            return redirect('staff_offences:detail', pk=register.pk)
        messages.error(request, 'Please correct the errors below.')
    else:
        form = StaffOffenceEntryForm(instance=entry)
    context = get_register_context(register, request.user, request)
    context.update({
        'entry_form': form,
        'entry': entry,
        'form_title': 'Edit Offence',
        'form_action': 'edit',
    })
    response = render(request, 'staff_offences/entry_form.html', context)
    apply_no_cache_headers(response)
    return response


def _register_totals_payload(register):
    entries = list(_active_entries(register))
    monthly_total = sum((e.amount for e in entries), Decimal('0.00'))
    return entries, {
        'offence_count': len(entries),
        'monthly_total': str(monthly_total),
        'monthly_total_display': f'{monthly_total:,.0f}',
    }


@login_required
@company_admin_or_any_permission_required(
    ['staff_offences.delete_staffoffenceentry', 'staff_offences.change_staffoffenceregister'],
    raise_exception=True,
)
@require_POST
def entry_delete(request, pk, entry_pk):
    qs = for_user_queryset(StaffOffenceRegister, request.user, request, account_lookup='account')
    register, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return response
    entry = _active_entries(register).filter(pk=entry_pk).first()
    if entry:
        entry.delete()
        messages.success(request, 'Offence deleted successfully.')
    else:
        messages.error(request, 'Offence entry not found.')
    return redirect('staff_offences:detail', pk=register.pk)


@login_required
@company_admin_or_any_permission_required(
    ['staff_offences.delete_staffoffenceentry', 'staff_offences.change_staffoffenceregister'],
    raise_exception=True,
)
@require_POST
def entry_delete_ajax(request, pk, entry_pk):
    qs = for_user_queryset(StaffOffenceRegister, request.user, request, account_lookup='account')
    register, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return JsonResponse({'success': False, 'error': 'Not found or access denied'}, status=403)
    entry = _active_entries(register).filter(pk=entry_pk).first()
    if not entry:
        return JsonResponse({'success': False, 'error': 'Entry not found'}, status=404)
    entry.delete()
    _, totals = _register_totals_payload(register)
    return JsonResponse({'success': True, 'deleted_id': entry_pk, **totals})


@login_required
@company_admin_or_any_permission_required(
    ['staff_offences.add_staffoffenceentry', 'staff_offences.change_staffoffenceregister'],
    raise_exception=True,
)
@require_POST
def entry_create_ajax(request, pk):
    """AJAX create from the register detail modal."""
    qs = for_user_queryset(StaffOffenceRegister, request.user, request, account_lookup='account')
    register, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return JsonResponse({'success': False, 'error': 'Not found or access denied'}, status=403)
    form = StaffOffenceEntryForm(request.POST)
    if not form.is_valid():
        return JsonResponse({'success': False, 'errors': form.errors}, status=400)
    entry = form.save(commit=False)
    entry.register = register
    entry.created_by = request.user
    entry.save()
    _, totals = _register_totals_payload(register)
    return JsonResponse({
        'success': True,
        'entry': {
            'id': entry.pk,
            'date': entry.date.strftime('%d %b'),
            'date_iso': entry.date.isoformat(),
            'description': entry.description,
            'amount': str(entry.amount),
            'amount_display': f'{entry.amount:,.0f}',
        },
        **totals,
    })


@login_required
@company_admin_or_any_permission_required(
    ['staff_offences.change_staffoffenceentry', 'staff_offences.change_staffoffenceregister'],
    raise_exception=True,
)
@require_POST
def entry_edit_ajax(request, pk, entry_pk):
    qs = for_user_queryset(StaffOffenceRegister, request.user, request, account_lookup='account')
    register, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return JsonResponse({'success': False, 'error': 'Not found or access denied'}, status=403)
    entry = _active_entries(register).filter(pk=entry_pk).first()
    if not entry:
        return JsonResponse({'success': False, 'error': 'Entry not found'}, status=404)
    form = StaffOffenceEntryForm(request.POST, instance=entry)
    if not form.is_valid():
        return JsonResponse({'success': False, 'errors': form.errors}, status=400)
    entry = form.save()
    _, totals = _register_totals_payload(register)
    return JsonResponse({
        'success': True,
        'entry': {
            'id': entry.pk,
            'date': entry.date.strftime('%d %b'),
            'date_iso': entry.date.isoformat(),
            'description': entry.description,
            'amount': str(entry.amount),
            'amount_display': f'{entry.amount:,.0f}',
        },
        **totals,
    })
