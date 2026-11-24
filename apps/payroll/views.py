"""
Smart Payroll Records Views
==========================
Comprehensive views for payroll record management with file upload,
viewing, downloading, and management capabilities.
"""

import os
import mimetypes
import hashlib
import urllib.parse
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import (
    Http404, JsonResponse, HttpResponse, 
    FileResponse, StreamingHttpResponse
)
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.utils import timezone
from django.db.models import Q, Count, Sum, F
from django.conf import settings

from apps.core.utils import get_company_profile_for_user
from apps.core.ownership import get_account_for_user, drf_filter_queryset_for_user
from apps.core.permissions import company_admin_or_permission_required

from .models import (
    PayrollRecord,
    PayrollCategory,
    PayrollRecordAccessLog,
    PayrollRecordShare,
    ExtractedPayrollData,
    PayrollTemplate,
    PayrollEntry,
    PayrollNotification,
    PayrollSetting,
)
from .forms import (
    PayrollRecordForm,
    PayrollRecordBulkForm,
    PayrollCategoryForm,
    PayrollRecordFilterForm,
)
from .file_processor import SmartFileProcessor
from .services import (
    create_notification,
    log_access,
    generate_share_link,
    calculate_record_stats,
)


def _get_company(request):
    """Get company from request context (already set by middleware)."""
    return getattr(request, 'company', None)


def _get_account(request):
    """Get account from request context."""
    return getattr(request, 'account', None) or get_account_for_user(request.user)


@login_required
@never_cache
def dashboard(request):
    """
    Smart Payroll Records Dashboard.
    Shows overview of payroll records, stats, and recent activity.
    """
    company = _get_company(request)
    if not company:
        raise Http404("Company not found")
    
    # Single optimized query for all basic stats
    records_qs = PayrollRecord.objects.filter(company=company, is_deleted=False)
    
    # Get basic counts in one query
    total_records = records_qs.count()
    total_size_agg = records_qs.aggregate(total=Sum('file_size'))
    total_size = total_size_agg['total'] or 0
    
    # Get status counts
    records_by_status = {}
    status_counts = records_qs.values('status').annotate(count=Count('id'))
    for item in status_counts:
        status = item['status']
        label = dict(PayrollRecord.STATUS_CHOICES).get(status, status)
        records_by_status[status] = {'label': label, 'count': item['count']}
    
    # Get file type counts
    records_by_type = {}
    type_counts = records_qs.values('record_type').annotate(count=Count('id'))
    for item in type_counts:
        rt = item['record_type']
        label = dict(PayrollRecord.RECORD_TYPE_CHOICES).get(rt, rt)
        records_by_type[rt] = {'label': label, 'count': item['count']}
    
    # Get recent records with select_related
    recent_records = list(records_qs.select_related('category').order_by('-created_at')[:10])
    
    # Get starred records
    starred_records = list(records_qs.filter(is_starred=True).order_by('-updated_at')[:5])
    
    # Get pending counts
    pending_verification = records_qs.filter(status='draft').count()
    pending_approval = records_qs.filter(status='verified').count()
    
    # Categories with annotated record count (prevents N+1 queries!)
    categories = list(PayrollCategory.objects.filter(
        company=company, is_active=True
    ).annotate(
        record_count=Count('payroll_records', filter=~Q(payroll_records__is_deleted=True))
    ).order_by('name')[:20])  # Limit to 20 categories
    
    # Build stats dict (lightweight, no extra queries)
    stats = {
        'total_records': total_records,
        'total_size': total_size,
        'total_size_display': _format_file_size(total_size),
        'by_status': records_by_status,
        'by_type': records_by_type,
        'starred_count': records_qs.filter(is_starred=True).count(),
        'archived_count': records_qs.filter(is_archived=True).count(),
        'total_views': records_qs.aggregate(total=Sum('view_count'))['total'] or 0,
        'total_downloads': records_qs.aggregate(total=Sum('download_count'))['total'] or 0,
    }
    
    current_year = date.today().year
    years = list(range(1980, current_year + 10))
    
    context = {
        'total_records': total_records,
        'total_size': total_size,
        'total_size_display': _format_file_size(total_size),
        'records_by_type': records_by_type,
        'records_by_status': records_by_status,
        'recent_records': recent_records,
        'starred_records': starred_records,
        'recently_viewed': [],  # Skip for faster loading
        'pending_verification': pending_verification,
        'pending_approval': pending_approval,
        'categories': categories,
        'stats': stats,
        'years': years,
        'payroll_current_page': 'dashboard',
    }
    return render(request, 'payroll/dashboard.html', context)


@login_required
@never_cache
@company_admin_or_permission_required('payroll.view_payroll_record', raise_exception=True)
def record_list(request):
    """
    List all payroll records with filtering, sorting, and pagination.
    """
    company = _get_company(request)
    if not company:
        raise Http404("Company not found")
    
    # Get page number from URL
    page = request.GET.get('page', 1)
    try:
        page = int(page)
    except (ValueError, TypeError):
        page = 1
    
    # Check if showing archived records
    show_archived = request.GET.get('show_archived', 'false') == 'true'
    
    # Simple filter from URL params
    record_type = request.GET.get('record_type', '')
    file_type = request.GET.get('file_type', '')
    status = request.GET.get('status', '')
    year = request.GET.get('year', '')
    query = request.GET.get('q', '').strip()
    starred = request.GET.get('starred', '')
    
    # Build base queryset
    records_qs = PayrollRecord.objects.filter(
        company=company, is_deleted=False
    ).select_related('category')  # Only select category, not all relations
    
    # Order by updated_at if showing archived, else created_at
    order_field = '-updated_at' if show_archived else '-created_at'
    records_qs = records_qs.order_by(order_field)
    
    # Track if filters are active
    has_active_filters = False
    filter_reasons = []
    
    # Apply filters - use exact matches where possible (faster)
    if record_type:
        records_qs = records_qs.filter(record_type=record_type)
        has_active_filters = True
        filter_reasons.append(f'record_type: {record_type}')
    
    if file_type:
        records_qs = records_qs.filter(file_type=file_type)
        has_active_filters = True
        filter_reasons.append(f'file_type: {file_type}')
    
    if status:
        records_qs = records_qs.filter(status=status)
        has_active_filters = True
        filter_reasons.append(f'status: {status}')
    
    if year:
        records_qs = records_qs.filter(period_year=int(year))
        has_active_filters = True
        filter_reasons.append(f'year: {year}')
    
    if starred == 'true':
        records_qs = records_qs.filter(is_starred=True)
        has_active_filters = True
        filter_reasons.append('starred: true')
    
    # Search query - use contains only on indexed fields (slower but necessary)
    if query:
        records_qs = records_qs.filter(
            Q(title__icontains=query) |
            Q(original_filename__icontains=query)
        )
        has_active_filters = True
        filter_reasons.append(f'query: "{query}"')
    
    # Get total count before pagination
    total_count = records_qs.count()
    total_before_filters = total_count
    
    # Pagination - only fetch the page we need
    paginator = Paginator(records_qs, 25)
    try:
        records = paginator.page(page)
    except (PageNotAnInteger, EmptyPage):
        records = paginator.page(1)
    
    # Get categories for filter dropdown (lightweight)
    categories = list(PayrollCategory.objects.filter(
        company=company, is_active=True
    ).order_by('name')[:50])  # Limit to 50
    
    # Get years
    current_year = date.today().year
    years = list(range(1980, current_year + 10))
    
    # Build query params
    query_params = request.GET.urlencode()
    
    context = {
        'records': records,
        'categories': categories,
        'years': years,
        'total_count': total_count,
        'total_before_filters': total_before_filters,
        'record_type_choices': PayrollRecord.RECORD_TYPE_CHOICES,
        'file_type_choices': PayrollRecord.FILE_TYPE_CHOICES,
        'payroll_current_page': 'records',
        'query': query,
        'show_archived': show_archived,
        'query_params': query_params,
        'has_active_filters': has_active_filters,
        'filter_reasons': filter_reasons,
    }
    return render(request, 'payroll/record_list.html', context)


@login_required
@never_cache
@company_admin_or_permission_required('payroll.add_payroll_record', raise_exception=True)
def record_upload(request):
    """
    Upload new payroll records.
    Supports multiple file upload with smart file type detection.
    """
    company = _get_company(request)
    if not company:
        raise Http404("Company not found")
    
    account = _get_account(request)
    
    if request.method == 'POST':
        form = PayrollRecordForm(request.POST, request.FILES)
        
        if form.is_valid():
            files = request.FILES.getlist('file')
            
            if not files:
                messages.error(request, "Please select at least one file to upload.")
                return redirect('payroll:record_upload')
            
            uploaded_records = []
            errors = []
            
            for uploaded_file in files:
                try:
                    processor = SmartFileProcessor(uploaded_file, company, request.user)
                    result = processor.process()
                    
                    if result.get('error'):
                        errors.append(f"{uploaded_file.name}: {result['error']}")
                        continue
                    
                    record = PayrollRecord.objects.create(
                        account=account,
                        company=company,
                        created_by=request.user,
                        title=form.cleaned_data.get('title') or result.get('title', uploaded_file.name),
                        record_type=form.cleaned_data.get('record_type', 'other'),
                        file=uploaded_file,
                        original_filename=result.get('original_filename', uploaded_file.name),
                        file_type=result.get('file_type', 'other'),
                        mime_type=result.get('mime_type', ''),
                        file_size=result.get('file_size', uploaded_file.size),
                        file_hash=result.get('file_hash', ''),
                        period_month=form.cleaned_data.get('period_month'),
                        period_year=form.cleaned_data.get('period_year'),
                        period_start_date=form.cleaned_data.get('period_start_date'),
                        period_end_date=form.cleaned_data.get('period_end_date'),
                        description=form.cleaned_data.get('description', ''),
                        tags=form.cleaned_data.get('tags', ''),
                        employee=form.cleaned_data.get('employee'),
                        department=form.cleaned_data.get('department'),
                        status='draft',
                    )
                    
                    if form.cleaned_data.get('category'):
                        record.category = form.cleaned_data['category']
                        record.save(update_fields=['category'])
                    
                    uploaded_records.append(record)
                    
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    errors.append(f"{uploaded_file.name}: {str(e)}")
            
            if uploaded_records:
                count = len(uploaded_records)
                messages.success(request, f"Successfully uploaded {count} payroll record(s).")
                
                if count == 1:
                    return redirect('payroll:record_detail', record_id=uploaded_records[0].id)
                return redirect('payroll:record_list')
            
            for error in errors:
                messages.error(request, error)
            
            return redirect('payroll:record_upload')
    else:
        form = PayrollRecordForm()
    
    # Categories with annotated record count (prevents N+1 queries!)
    from django.db.models import Count, Q
    categories = PayrollCategory.objects.filter(
        company=company, is_active=True
    ).annotate(
        record_count=Count('payroll_records', filter=~Q(payroll_records__is_deleted=True))
    ).order_by('name')
    
    current_year = date.today().year
    years = list(range(1980, current_year + 10))
    months = [
        (1, 'January'), (2, 'February'), (3, 'March'),
        (4, 'April'), (5, 'May'), (6, 'June'),
        (7, 'July'), (8, 'August'), (9, 'September'),
        (10, 'October'), (11, 'November'), (12, 'December'),
    ]
    
    record_types = PayrollRecord.RECORD_TYPE_CHOICES
    file_types = PayrollRecord.FILE_TYPE_CHOICES
    
    max_file_size = settings.FILE_UPLOAD_MAX_MEMORY_SIZE
    
    context = {
        'form': form,
        'categories': categories,
        'years': years,
        'months': months,
        'record_types': record_types,
        'file_types': file_types,
        'max_file_size': max_file_size,
        'payroll_current_page': 'records',
    }
    return render(request, 'payroll/record_upload.html', context)


@login_required
@never_cache
@company_admin_or_permission_required('payroll.view_payroll_record', raise_exception=True)
def record_detail(request, record_id):
    """
    View payroll record details with file preview capability.
    """
    company = _get_company(request)
    if not company:
        raise Http404("Company not found")
    
    record = get_object_or_404(
        PayrollRecord, 
        pk=record_id, 
        company=company,
        is_deleted=False
    )
    
    five_minutes_ago = timezone.now() - timezone.timedelta(minutes=5)
    
    recent_view = PayrollRecordAccessLog.objects.filter(
        record=record,
        user=request.user,
        action='view',
        created_at__gte=five_minutes_ago
    ).exists()
    
    if not recent_view:
        record.increment_view_count()
        log_access(request, record, 'view')
    
    related_records = PayrollRecord.objects.filter(
        company=company,
        employee=record.employee,
        is_deleted=False
    ).exclude(
        id=record.id
    ).select_related(
        'employee', 'department', 'category'
    ).order_by('-created_at')[:5]
    
    access_logs = PayrollRecordAccessLog.objects.filter(
        record=record
    ).exclude(
        action='view',
        created_at__lt=five_minutes_ago
    ).select_related(
        'user'
    ).order_by('-created_at')[:10]
    
    shares = PayrollRecordShare.objects.filter(
        record=record,
        is_active=True,
        is_deleted=False
    ).select_related(
        'shared_by'
    ).order_by('-created_at')
    
    preview_url = None
    if record.can_preview:
        preview_url = f'/payroll/records/{record.id}/preview/'
    
    context = {
        'record': record,
        'related_records': related_records,
        'access_logs': access_logs,
        'shares': shares,
        'preview_url': preview_url,
        'payroll_current_page': 'records',
    }
    return render(request, 'payroll/record_detail.html', context)


@login_required
@never_cache
@company_admin_or_permission_required('payroll.change_payroll_record', raise_exception=True)
def record_edit(request, record_id):
    """
    Edit payroll record details.
    """
    company = _get_company(request)
    if not company:
        raise Http404("Company not found")
    
    account = _get_account(request)
    
    record = get_object_or_404(
        PayrollRecord,
        pk=record_id,
        company=company,
        is_deleted=False
    )
    
    if request.method == 'POST':
        form = PayrollRecordForm(request.POST, request.FILES, instance=record)
        
        if form.is_valid():
            new_file = request.FILES.get('file')
            
            if new_file:
                try:
                    processor = SmartFileProcessor(new_file, company, request.user)
                    result = processor.process()
                    
                    if not result.get('error'):
                        record.file = new_file
                        record.original_filename = result.get('original_filename', new_file.name)
                        record.file_type = result.get('file_type', 'other')
                        record.mime_type = result.get('mime_type', '')
                        record.file_size = result.get('file_size', new_file.size)
                        record.file_hash = result.get('file_hash', '')
                except Exception as e:
                    messages.error(request, f"Error processing new file: {str(e)}")
            
            record.title = form.cleaned_data.get('title', record.title)
            record.record_type = form.cleaned_data.get('record_type', record.record_type)
            record.category = form.cleaned_data.get('category')
            record.period_month = form.cleaned_data.get('period_month')
            record.period_year = form.cleaned_data.get('period_year')
            record.period_start_date = form.cleaned_data.get('period_start_date')
            record.period_end_date = form.cleaned_data.get('period_end_date')
            record.description = form.cleaned_data.get('description', '')
            record.tags = form.cleaned_data.get('tags', '')
            record.employee = form.cleaned_data.get('employee')
            record.department = form.cleaned_data.get('department')
            record.updated_by = request.user
            record.save()
            
            messages.success(request, "Payroll record updated successfully.")
            return redirect('payroll:record_detail', record_id=record.id)
    else:
        form = PayrollRecordForm(instance=record)
    
    categories = PayrollCategory.objects.filter(company=company, is_active=True)
    current_year = date.today().year
    years = list(range(1980, current_year + 10))
    
    context = {
        'form': form,
        'record': record,
        'categories': categories,
        'years': years,
        'payroll_current_page': 'records',
    }
    return render(request, 'payroll/record_edit.html', context)


@login_required
@never_cache
@company_admin_or_permission_required('payroll.delete_payroll_record', raise_exception=True)
@require_POST
def record_delete(request, record_id):
    """
    Soft delete a payroll record.
    """
    company = _get_company(request)
    if not company:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Company not found'}, status=404)
        raise Http404("Company not found")
    
    record = get_object_or_404(
        PayrollRecord,
        pk=record_id,
        company=company,
        is_deleted=False
    )
    
    record.is_deleted = True
    record.save(update_fields=['is_deleted', 'updated_at'])
    
    log_access(request, record, 'delete')
    
    # Check if this is an AJAX request
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'message': 'Record deleted successfully'})
    
    messages.success(request, "Payroll record deleted successfully.")
    return redirect('payroll:record_list')


@login_required
@never_cache
@company_admin_or_permission_required('payroll.view_payroll_record', raise_exception=True)
def record_download(request, record_id):
    """
    Download payroll record file.
    """
    company = _get_company(request)
    if not company:
        raise Http404("Company not found")
    
    record = get_object_or_404(
        PayrollRecord,
        pk=record_id,
        company=company,
        is_deleted=False
    )
    
    if not record.file:
        raise Http404("File not found")
    
    record.increment_download_count()
    log_access(request, record, 'download')
    
    file_path = record.file.path
    file_name = record.original_filename or os.path.basename(file_path)
    
    mime_type = record.mime_type
    if not mime_type:
        mime_type, _ = mimetypes.guess_type(file_path)
        mime_type = mime_type or 'application/octet-stream'
    
    response = FileResponse(
        open(file_path, 'rb'),
        content_type=mime_type
    )
    response['Content-Disposition'] = f'attachment; filename="{file_name}"'
    response['Content-Length'] = record.file_size
    
    return response


@login_required
@never_cache
@company_admin_or_permission_required('payroll.view_payroll_record', raise_exception=True)
def record_preview(request, record_id):
    """
    Preview payroll record file in browser.
    Supports multiple file types with appropriate preview methods.
    """
    company = _get_company(request)
    if not company:
        raise Http404("Company not found")
    
    record = get_object_or_404(
        PayrollRecord,
        pk=record_id,
        company=company,
        is_deleted=False
    )
    
    if not record.file:
        raise Http404("File not found")
    
    log_access(request, record, 'preview')
    
    # Build the absolute file URL
    file_url = request.build_absolute_uri(record.file.url)
    is_local = '127.0.0.1' in file_url or 'localhost' in file_url.lower()
    encoded_url = urllib.parse.quote(file_url, safe='')
    
    context = {
        'record': record,
        'file_url': file_url,
        'download_url': f'/payroll/records/{record.id}/download/',
        'preview_url': None,
        'preview_type': 'none',
        'embed_url': None,
        'is_local': is_local,
        'file_data': None,
    }
    
    # For local development, read file and provide data URL for client-side preview
    if is_local and record.file_type in ['excel', 'csv', 'pdf', 'image', 'word']:
        try:
            # Read file and convert to base64 for client-side rendering
            with open(record.file.path, 'rb') as f:
                import base64
                file_content = f.read()
                context['file_data'] = base64.b64encode(file_content).decode('utf-8')
        except Exception as e:
            pass
    
    # Determine preview method based on file type
    if record.file_type == 'excel':
        # Excel: Use client-side rendering with SheetJS
        if is_local and context.get('file_data'):
            context['preview_type'] = 'client_side'
        else:
            context['preview_type'] = 'none'
            
    elif record.file_type == 'pdf':
        # For PDF, use client-side rendering with data URL
        if is_local and context.get('file_data'):
            context['preview_type'] = 'client_side'
        else:
            context['preview_type'] = 'iframe_data'
            context['file_url'] = f'/payroll/records/{record.id}/file-data/'
            
    elif record.file_type == 'image':
        # For images, use data URL
        if context.get('file_data'):
            context['preview_type'] = 'image_data'
        else:
            context['preview_type'] = 'native'
            context['file_url'] = record.file.url
        
    elif record.file_type == 'word':
        if is_local:
            context['preview_type'] = 'client_side'
        else:
            office_url = f'https://view.officeapps.live.com/op/view.aspx?src={encoded_url}'
            context['preview_type'] = 'google_docs'
            context['preview_url'] = office_url
        
    elif record.file_type == 'csv':
        context['preview_type'] = 'client_side'
        
    else:
        # Other file types - show not available
        context['preview_type'] = 'none'
    
    return render(request, 'payroll/file_preview.html', context)


@login_required
@never_cache
@company_admin_or_permission_required('payroll.change_payroll_record', raise_exception=True)
@require_POST
def record_toggle_star(request, record_id):
    """
    Toggle star status of a payroll record.
    """
    company = _get_company(request)
    if not company:
        return JsonResponse({'error': 'Company not found'}, status=404)
    
    record = get_object_or_404(
        PayrollRecord,
        pk=record_id,
        company=company,
        is_deleted=False
    )
    
    record.is_starred = not record.is_starred
    record.save(update_fields=['is_starred', 'updated_at'])
    
    return JsonResponse({
        'is_starred': record.is_starred
    })


@login_required
@never_cache
@company_admin_or_permission_required('payroll.change_payroll_record', raise_exception=True)
@require_POST
def record_toggle_archive(request, record_id):
    """
    Toggle archive status of a payroll record.
    """
    company = _get_company(request)
    if not company:
        return JsonResponse({'error': 'Company not found'}, status=404)
    
    record = get_object_or_404(
        PayrollRecord,
        pk=record_id,
        company=company,
        is_deleted=False
    )
    
    record.is_archived = not record.is_archived
    if record.is_archived:
        record.status = 'archived'
    else:
        record.status = 'draft'
    record.save(update_fields=['is_archived', 'status', 'updated_at'])
    
    return JsonResponse({
        'is_archived': record.is_archived,
        'status': record.status
    })


@login_required
@never_cache
@company_admin_or_permission_required('payroll.change_payroll_record', raise_exception=True)
@require_POST
def record_verify(request, record_id):
    """
    Verify a payroll record.
    """
    company = _get_company(request)
    if not company:
        return JsonResponse({'error': 'Company not found'}, status=404)
    
    record = get_object_or_404(
        PayrollRecord,
        pk=record_id,
        company=company,
        is_deleted=False
    )
    
    record.verify(request.user)
    log_access(request, record, 'verify')
    
    create_notification(
        company=company,
        user=record.created_by,
        notification_type='record_verified',
        title='Payroll Record Verified',
        message=f'Your payroll record "{record.title}" has been verified.',
        record=record,
        link=f'/payroll/records/{record.id}/'
    )
    
    return JsonResponse({
        'status': record.status,
        'verified_by': str(record.verified_by),
        'verified_at': record.verified_at.isoformat() if record.verified_at else None
    })


@login_required
@never_cache
@company_admin_or_permission_required('payroll.change_payroll_record', raise_exception=True)
@require_POST
def record_approve(request, record_id):
    """
    Approve a payroll record.
    """
    company = _get_company(request)
    if not company:
        return JsonResponse({'error': 'Company not found'}, status=404)
    
    record = get_object_or_404(
        PayrollRecord,
        pk=record_id,
        company=company,
        is_deleted=False
    )
    
    if record.status != 'verified':
        return JsonResponse({
            'error': 'Record must be verified before approval'
        }, status=400)
    
    record.approve(request.user)
    log_access(request, record, 'approve')
    
    create_notification(
        company=company,
        user=record.created_by,
        notification_type='record_approved',
        title='Payroll Record Approved',
        message=f'Your payroll record "{record.title}" has been approved.',
        record=record,
        link=f'/payroll/records/{record.id}/'
    )
    
    return JsonResponse({
        'status': record.status,
        'approved_by': str(record.approved_by),
        'approved_at': record.approved_at.isoformat() if record.approved_at else None
    })


@login_required
@never_cache
@company_admin_or_permission_required('payroll.add_payroll_record', raise_exception=True)
def record_share(request, record_id):
    """
    Share a payroll record with another user.
    """
    company = _get_company(request)
    if not company:
        raise Http404("Company not found")
    
    record = get_object_or_404(
        PayrollRecord,
        pk=record_id,
        company=company,
        is_deleted=False
    )
    
    if request.method == 'POST':
        share_type = request.POST.get('share_type', 'link')
        shared_with_email = request.POST.get('email', '').strip()
        permission_view = request.POST.get('permission_view', 'on') == 'on'
        permission_download = request.POST.get('permission_download', 'on') == 'on'
        permission_print = request.POST.get('permission_print', '') == 'on'
        expires_in_days = request.POST.get('expires_in_days', '')
        max_access = request.POST.get('max_access_count', '')
        
        share = PayrollRecordShare.objects.create(
            account=record.account,
            company=company,
            record=record,
            shared_by=request.user,
            shared_with_email=shared_with_email,
            share_token=hashlib.sha256(os.urandom(32)).hexdigest(),
            permission_view=permission_view,
            permission_download=permission_download,
            permission_print=permission_print,
        )
        
        if expires_in_days:
            share.expires_at = timezone.now() + timedelta(days=int(expires_in_days))
        
        if max_access:
            share.max_access_count = int(max_access)
        
        share.save()
        
        log_access(request, record, 'share')
        
        messages.success(request, "Share link created successfully.")
        return redirect('payroll:record_detail', record_id=record.id)
    
    context = {
        'record': record,
        'payroll_current_page': 'records',
    }
    return render(request, 'payroll/record_share.html', context)


@login_required
@never_cache
def shared_record_access(request, token):
    """
    Access a shared payroll record via share token.
    """
    share = get_object_or_404(
        PayrollRecordShare,
        share_token=token,
        is_active=True,
        is_deleted=False
    )
    
    if share.is_expired:
        raise Http404("Share link has expired")
    
    if share.max_access_count > 0 and share.access_count >= share.max_access_count:
        raise Http404("Share link has reached maximum access count")
    
    record = share.record
    
    share.access_count += 1
    share.save(update_fields=['access_count'])
    
    log_access(request, record, 'view')
    
    context = {
        'record': record,
        'share': share,
        'can_download': share.permission_download,
        'can_print': share.permission_print,
    }
    return render(request, 'payroll/shared_record.html', context)


@login_required
@never_cache
def shared_record_download(request, token):
    """
    Download a shared payroll record via share token.
    """
    share = get_object_or_404(
        PayrollRecordShare,
        share_token=token,
        is_active=True,
        is_deleted=False
    )
    
    if share.is_expired:
        raise Http404("Share link has expired")
    
    if not share.permission_download:
        raise Http404("Download not allowed")
    
    if share.max_access_count > 0 and share.access_count >= share.max_access_count:
        raise Http404("Share link has reached maximum access count")
    
    record = share.record
    
    if not record.file:
        raise Http404("File not found")
    
    share.access_count += 1
    share.save(update_fields=['access_count'])
    
    file_path = record.file.path
    file_name = record.original_filename or os.path.basename(file_path)
    
    mime_type = record.mime_type
    if not mime_type:
        mime_type, _ = mimetypes.guess_type(file_path)
        mime_type = mime_type or 'application/octet-stream'
    
    response = FileResponse(
        open(file_path, 'rb'),
        content_type=mime_type
    )
    response['Content-Disposition'] = f'attachment; filename="{file_name}"'
    response['Content-Length'] = record.file_size
    
    return response


@login_required
@never_cache
@company_admin_or_permission_required('payroll.view_payroll_record', raise_exception=True)
def category_list(request):
    """
    List all payroll categories.
    """
    company = _get_company(request)
    if not company:
        raise Http404("Company not found")
    
    # Categories with annotated record count (prevents N+1 queries!)
    from django.db.models import Count, Q
    categories = PayrollCategory.objects.filter(
        company=company, is_active=True
    ).annotate(
        record_count=Count('payroll_records', filter=~Q(payroll_records__is_deleted=True))
    ).order_by('name')
    
    context = {
        'categories': categories,
        'payroll_current_page': 'categories',
    }
    return render(request, 'payroll/category_list.html', context)


@login_required
@never_cache
@company_admin_or_permission_required('payroll.add_payroll_category', raise_exception=True)
def category_create(request):
    """
    Create a new payroll category.
    """
    company = _get_company(request)
    if not company:
        raise Http404("Company not found")
    
    account = _get_account(request)
    
    if request.method == 'POST':
        form = PayrollCategoryForm(request.POST)
        
        if form.is_valid():
            category = form.save(commit=False)
            category.account = account
            category.company = company
            category.created_by = request.user
            category.save()
            
            messages.success(request, f"Category '{category.name}' created successfully.")
            return redirect('payroll:category_list')
    else:
        form = PayrollCategoryForm()
    
    context = {
        'form': form,
        'payroll_current_page': 'categories',
    }
    return render(request, 'payroll/category_create.html', context)


@login_required
@never_cache
@company_admin_or_permission_required('payroll.change_payroll_category', raise_exception=True)
def category_edit(request, category_id):
    """
    Edit a payroll category.
    """
    company = _get_company(request)
    if not company:
        raise Http404("Company not found")
    
    category = get_object_or_404(
        PayrollCategory,
        pk=category_id,
        company=company
    )
    
    if request.method == 'POST':
        form = PayrollCategoryForm(request.POST, instance=category)
        
        if form.is_valid():
            form.save()
            messages.success(request, f"Category '{category.name}' updated successfully.")
            return redirect('payroll:category_list')
    else:
        form = PayrollCategoryForm(instance=category)
    
    context = {
        'form': form,
        'category': category,
        'payroll_current_page': 'categories',
    }
    return render(request, 'payroll/category_edit.html', context)


@login_required
@never_cache
@company_admin_or_permission_required('payroll.delete_payroll_category', raise_exception=True)
@require_POST
def category_delete(request, category_id):
    """
    Delete a payroll category.
    """
    company = _get_company(request)
    if not company:
        raise Http404("Company not found")
    
    category = get_object_or_404(
        PayrollCategory,
        pk=category_id,
        company=company
    )
    
    category.is_active = False
    category.save(update_fields=['is_active', 'updated_at'])
    
    messages.success(request, f"Category '{category.name}' deleted successfully.")
    return redirect('payroll:category_list')


@login_required
@never_cache
@company_admin_or_permission_required('payroll.view_payroll_record', raise_exception=True)
def access_logs(request):
    """
    View payroll record access logs.
    """
    company = _get_company(request)
    if not company:
        raise Http404("Company not found")
    
    # Get filter params
    action = request.GET.get('action', '')
    record_id = request.GET.get('record', '')
    user_id = request.GET.get('user', '')
    
    # Build base queryset - use only_() to limit fields fetched
    logs_qs = PayrollRecordAccessLog.objects.filter(
        company=company
    ).select_related(
        'record'
    ).order_by('-created_at')
    
    # Apply filters
    if action:
        logs_qs = logs_qs.filter(action=action)
    
    if record_id:
        logs_qs = logs_qs.filter(record_id=record_id)
    
    if user_id:
        logs_qs = logs_qs.filter(user_id=user_id)
    
    # Paginate
    paginator = Paginator(logs_qs, 50)
    page = request.GET.get('page', 1)
    
    try:
        logs = paginator.page(page)
    except (PageNotAnInteger, EmptyPage):
        logs = paginator.page(1)
    
    context = {
        'logs': logs,
        'payroll_current_page': 'access_logs',
    }
    return render(request, 'payroll/access_logs.html', context)


@login_required
@never_cache
@company_admin_or_permission_required('payroll.view_payroll_record', raise_exception=True)
def analytics(request):
    """
    Payroll records analytics and statistics.
    """
    company = _get_company(request)
    if not company:
        raise Http404("Company not found")
    
    stats = calculate_record_stats(company)
    
    records_qs = PayrollRecord.objects.filter(
        company=company, is_deleted=False
    )
    
    # Use database aggregation for record type counts
    records_by_type = {}
    type_counts = records_qs.values('record_type').annotate(count=Count('id'))
    for item in type_counts:
        rt = item['record_type']
        label = dict(PayrollRecord.RECORD_TYPE_CHOICES).get(rt, rt)
        records_by_type[label] = item['count']
    
    # Use database aggregation for monthly counts
    records_by_month = {}
    month_counts = records_qs.filter(period_month__isnull=False).values('period_month').annotate(count=Count('id'))
    for item in month_counts:
        month_name = date(2000, item['period_month'], 1).strftime('%B')
        records_by_month[month_name] = item['count']
    
    # Fill in missing months with 0
    for i in range(1, 13):
        month_name = date(2000, i, 1).strftime('%B')
        if month_name not in records_by_month:
            records_by_month[month_name] = 0
    
    top_employees = records_qs.values(
        'employee__first_name', 'employee__last_name', 'employee__employee_id'
    ).annotate(
        count=Count('id')
    ).order_by('-count')[:10]
    
    context = {
        'stats': stats,
        'records_by_type': records_by_type,
        'records_by_month': records_by_month,
        'top_employees': top_employees,
        'payroll_current_page': 'analytics',
    }
    return render(request, 'payroll/analytics.html', context)


@login_required
@never_cache
@company_admin_or_permission_required('payroll.view_payroll_record', raise_exception=True)
def template_list(request):
    """
    List payroll templates.
    """
    company = _get_company(request)
    if not company:
        raise Http404("Company not found")
    
    templates = PayrollTemplate.objects.filter(
        company=company, is_active=True
    ).order_by('-created_at')
    
    context = {
        'templates': templates,
        'payroll_current_page': 'templates',
    }
    return render(request, 'payroll/template_list.html', context)


@login_required
@never_cache
@company_admin_or_permission_required('payroll.view_payroll_record', raise_exception=True)
def entry_list(request):
    """
    List payroll entries.
    """
    company = _get_company(request)
    if not company:
        raise Http404("Company not found")
    
    entries = PayrollEntry.objects.filter(
        company=company, is_deleted=False
    ).select_related(
        'template', 'created_by'
    ).order_by('-created_at')
    
    status = request.GET.get('status', '')
    if status:
        entries = entries.filter(status=status)
    
    paginator = Paginator(entries, 25)
    page = request.GET.get('page', 1)
    
    try:
        entries = paginator.page(page)
    except (PageNotAnInteger, EmptyPage):
        entries = paginator.page(1)
    
    context = {
        'entries': entries,
        'payroll_current_page': 'entries',
    }
    return render(request, 'payroll/entry_list.html', context)


@login_required
@never_cache
@company_admin_or_permission_required('payroll.view_payroll_record', raise_exception=True)
def entry_detail(request, entry_id):
    """
    View payroll entry details.
    """
    company = _get_company(request)
    if not company:
        raise Http404("Company not found")
    
    entry = get_object_or_404(
        PayrollEntry,
        pk=entry_id,
        company=company,
        is_deleted=False
    )
    
    context = {
        'entry': entry,
        'payroll_current_page': 'entries',
    }
    return render(request, 'payroll/entry_detail.html', context)


def _format_file_size(size_bytes):
    """Format file size in human readable format."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


@require_POST
@csrf_exempt
def api_upload(request):
    """
    API endpoint for file upload.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    company = _get_company(request)
    account = _get_account(request)
    
    if not company:
        return JsonResponse({'error': 'Company not found'}, status=404)
    
    files = request.FILES.getlist('files')
    
    if not files:
        return JsonResponse({'error': 'No files provided'}, status=400)
    
    results = []
    
    for uploaded_file in files:
        try:
            processor = SmartFileProcessor(uploaded_file, company, request.user)
            result = processor.process()
            
            if result.get('error'):
                results.append({
                    'name': uploaded_file.name,
                    'error': result['error']
                })
                continue
            
            record = PayrollRecord.objects.create(
                account=account,
                company=company,
                created_by=request.user,
                title=result.get('title', uploaded_file.name),
                record_type='other',
                file=uploaded_file,
                original_filename=result.get('original_filename', uploaded_file.name),
                file_type=result.get('file_type', 'other'),
                mime_type=result.get('mime_type', ''),
                file_size=result.get('file_size', uploaded_file.size),
                file_hash=result.get('file_hash', ''),
            )
            
            results.append({
                'id': record.id,
                'name': uploaded_file.name,
                'file_type': record.file_type,
                'file_size': record.file_size,
                'url': record.file.url if record.file else None,
                'success': True
            })
            
        except Exception as e:
            results.append({
                'name': uploaded_file.name,
                'error': str(e)
            })
    
    return JsonResponse({
        'results': results,
        'uploaded_count': sum(1 for r in results if r.get('success')),
        'error_count': sum(1 for r in results if r.get('error'))
    })


@require_POST
@csrf_exempt
def api_delete(request):
    """
    API endpoint for record deletion.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    company = _get_company(request)
    
    if not company:
        return JsonResponse({'error': 'Company not found'}, status=404)
    
    record_id = request.POST.get('id')
    
    if not record_id:
        return JsonResponse({'error': 'Record ID required'}, status=400)
    
    try:
        record = PayrollRecord.objects.get(
            pk=record_id,
            company=company,
            is_deleted=False
        )
        record.is_deleted = True
        record.save(update_fields=['is_deleted', 'updated_at'])
        return JsonResponse({'success': True})
    except PayrollRecord.DoesNotExist:
        return JsonResponse({'error': 'Record not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_POST
@csrf_exempt
def api_bulk_action(request):
    """
    API endpoint for bulk actions on records.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    company = _get_company(request)
    
    if not company:
        return JsonResponse({'error': 'Company not found'}, status=404)
    
    action = request.POST.get('action')
    record_ids = request.POST.getlist('ids')
    
    if not action or not record_ids:
        return JsonResponse({'error': 'Action and IDs required'}, status=400)
    
    success_count = 0
    error_count = 0
    
    for record_id in record_ids:
        try:
            record = PayrollRecord.objects.get(
                pk=record_id,
                company=company,
                is_deleted=False
            )
            
            if action == 'archive':
                record.is_archived = True
                record.status = 'archived'
                record.save(update_fields=['is_archived', 'status', 'updated_at'])
                success_count += 1
            elif action == 'unarchive':
                record.is_archived = False
                record.status = 'draft'
                record.save(update_fields=['is_archived', 'status', 'updated_at'])
                success_count += 1
            elif action == 'star':
                record.is_starred = True
                record.save(update_fields=['is_starred', 'updated_at'])
                success_count += 1
            elif action == 'unstar':
                record.is_starred = False
                record.save(update_fields=['is_starred', 'updated_at'])
                success_count += 1
            elif action == 'delete':
                record.is_deleted = True
                record.save(update_fields=['is_deleted', 'updated_at'])
                success_count += 1
            else:
                error_count += 1
                
        except Exception:
            error_count += 1
    
    return JsonResponse({
        'success_count': success_count,
        'error_count': error_count
    })


def api_stats(request):
    """API endpoint for getting dashboard statistics (real-time) using database aggregation."""
    from datetime import date
    from django.http import JsonResponse
    
    company = _get_company(request)
    if not company:
        return JsonResponse({'error': 'Company not found'}, status=403)
    
    records_qs = PayrollRecord.objects.filter(company=company, is_deleted=False)
    
    total_records = records_qs.count()
    
    by_status = {}
    status_counts = records_qs.values('status').annotate(count=Count('id'))
    for item in status_counts:
        status = item['status']
        label = dict(PayrollRecord.STATUS_CHOICES).get(status, status)
        by_status[status] = {'label': label, 'count': item['count']}
    
    by_type = {}
    type_counts = records_qs.values('file_type').annotate(count=Count('id'))
    for item in type_counts:
        ft = item['file_type']
        label = dict(PayrollRecord.FILE_TYPE_CHOICES).get(ft, ft)
        by_type[ft] = {'label': label, 'count': item['count']}
    
    pending_count = records_qs.filter(status='draft').count()
    verified_count = records_qs.filter(status='verified').count()
    approved_count = records_qs.filter(status='approved').count()
    
    total_size_agg = records_qs.aggregate(total=Sum('file_size'))
    total_size = total_size_agg['total'] or 0
    
    total_views_agg = records_qs.aggregate(total=Sum('view_count'))
    total_views = total_views_agg['total'] or 0
    
    total_downloads_agg = records_qs.aggregate(total=Sum('download_count'))
    total_downloads = total_downloads_agg['total'] or 0
    
    def format_size(size):
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        return f"{size / (1024 * 1024 * 1024):.1f} GB"
    
    return JsonResponse({
        'total_records': total_records,
        'pending_count': pending_count,
        'verified_count': verified_count,
        'approved_count': approved_count,
        'by_status': by_status,
        'by_type': by_type,
        'total_size': total_size,
        'total_size_display': format_size(total_size),
        'starred_count': records_qs.filter(is_starred=True).count(),
        'archived_count': records_qs.filter(is_archived=True).count(),
        'total_views': total_views,
        'total_downloads': total_downloads,
    })


@require_POST
def record_update_status(request, record_id):
    """Update record status via AJAX (real-time)."""
    from django.http import JsonResponse
    
    company = _get_company(request)
    if not company:
        return JsonResponse({'success': False, 'error': 'Company not found'}, status=403)
    
    try:
        record = PayrollRecord.objects.get(
            pk=record_id,
            company=company,
            is_deleted=False
        )
    except PayrollRecord.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Record not found'}, status=404)
    
    import json
    try:
        data = json.loads(request.body)
        new_status = data.get('status')
    except:
        return JsonResponse({'success': False, 'error': 'Invalid request data'}, status=400)
    
    valid_statuses = ['draft', 'verified', 'approved', 'archived']
    if new_status not in valid_statuses:
        return JsonResponse({'success': False, 'error': f'Invalid status. Must be one of: {", ".join(valid_statuses)}'}, status=400)
    
    old_status = record.status
    
    if new_status == 'verified':
        record.verify(request.user)
    elif new_status == 'approved':
        if record.status != 'verified':
            return JsonResponse({
                'success': False, 
                'error': 'Record must be verified before approval'
            }, status=400)
        record.approve(request.user)
    else:
        record.status = new_status
        if new_status == 'archived':
            record.is_archived = True
        else:
            record.is_archived = False
        record.updated_by = request.user
        record.save(update_fields=['status', 'is_archived', 'updated_by', 'updated_at'])
    
    log_access(request, record, f'status_change_{new_status}')
    
    return JsonResponse({
        'success': True,
        'message': f'Status changed from {old_status} to {new_status}',
        'new_status': record.status,
        'old_status': old_status
    })


def api_stream(request):
    """Server-Sent Events (SSE) stream for real-time updates (disabled by default)."""
    from django.http import StreamingHttpResponse, JsonResponse
    import time
    import json
    from datetime import datetime
    
    company = _get_company(request)
    if not company:
        return JsonResponse({'error': 'Company not found'}, status=403)
    
    def event_stream():
        last_check = time.time()
        
        while True:
            time.sleep(2)
            
            current_check = time.time()
            
            records_qs = PayrollRecord.objects.filter(company=company, is_deleted=False)
            total_records = records_qs.count()
            
            by_status = {}
            status_counts = records_qs.values('status').annotate(count=Count('id'))
            for item in status_counts:
                status = item['status']
                label = dict(PayrollRecord.STATUS_CHOICES).get(status, status)
                by_status[status] = {'label': label, 'count': item['count']}
            
            pending_count = records_qs.filter(status='draft').count()
            verified_count = records_qs.filter(status='verified').count()
            approved_count = records_qs.filter(status='approved').count()
            
            recent_records_raw = records_qs.order_by('-created_at')[:10].values(
                'id', 'title', 'original_filename', 'file_type', 'status', 
                'period_month', 'period_year', 'file_size', 'created_at'
            )
            
            recent_records = []
            for record in recent_records_raw:
                record_dict = dict(record)
                if record_dict.get('created_at'):
                    record_dict['created_at'] = record_dict['created_at'].strftime('%Y-%m-%d %H:%M:%S')
                recent_records.append(record_dict)
            
            data = {
                'type': 'update',
                'total_records': total_records,
                'pending_count': pending_count,
                'verified_count': verified_count,
                'approved_count': approved_count,
                'by_status': by_status,
                'recent_records': recent_records,
                'timestamp': current_check
            }
            
            yield f"data: {json.dumps(data)}\n\n"
            
            last_check = current_check
    
    response = StreamingHttpResponse(
        event_stream(),
        content_type='text/event-stream'
    )
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response


@login_required
@never_cache
@company_admin_or_permission_required('payroll.view_payroll_record', raise_exception=True)
def record_file_data(request, record_id):
    """Serve raw file data for client-side preview."""
    company = _get_company(request)
    if not company:
        raise Http404("Company not found")
    
    record = get_object_or_404(
        PayrollRecord,
        pk=record_id,
        company=company,
        is_deleted=False
    )
    
    if not record.file:
        raise Http404("File not found")
    
    try:
        with open(record.file.path, 'rb') as f:
            file_content = f.read()
        
        response = HttpResponse(file_content, content_type=record.mime_type or 'application/octet-stream')
        response['Content-Disposition'] = f'inline; filename="{record.original_filename}"'
        return response
    except IOError:
        raise Http404("File not found")
