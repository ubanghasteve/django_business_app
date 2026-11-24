"""
Smart Payroll API Views
====================
API views for the payroll records app.
"""

from rest_framework import serializers, viewsets, permissions, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.http import FileResponse

from apps.core.utils import get_company_profile_for_user
from apps.core.ownership import get_account_for_user, drf_filter_queryset_for_user
from apps.core.permissions import DjangoModelPermissions

from ..models import (
    PayrollRecord,
    PayrollCategory,
    PayrollTemplate,
    PayrollEntry,
    ExtractedPayrollData,
    PayrollRecordAccessLog,
    PayrollRecordShare,
    PayrollNotification,
)
from ..file_processor import SmartFileProcessor, get_file_icon
from ..services import (
    log_access,
    calculate_record_stats,
    generate_share_link,
    get_user_unread_notifications,
    mark_notification_as_read,
)


class IsAuthenticatedOrReadOnly(permissions.BasePermission):
    """Allow read-only access for unauthenticated users, write access for authenticated."""
    
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user and request.user.is_authenticated


class PayrollRecordListSerializer(serializers.ModelSerializer):
    """Serializer for payroll record list view."""
    
    file_icon = serializers.SerializerMethodField()
    file_size_display = serializers.CharField(read_only=True)
    period_display = serializers.CharField(read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    employee_name = serializers.SerializerMethodField()
    
    class Meta:
        model = PayrollRecord
        fields = [
            'id', 'title', 'record_type', 'file_type', 'file_icon',
            'original_filename', 'file_size', 'file_size_display',
            'period_month', 'period_year', 'period_display',
            'category', 'category_name', 'employee', 'employee_name',
            'status', 'is_starred', 'is_archived',
            'view_count', 'download_count', 'created_at',
        ]
    
    def get_file_icon(self, obj):
        icon_class, color = get_file_icon(obj.file_type)
        return {'class': icon_class, 'color': color}
    
    def get_employee_name(self, obj):
        if obj.employee:
            return str(obj.employee)
        return None


class PayrollRecordDetailSerializer(serializers.ModelSerializer):
    """Serializer for payroll record detail view."""
    
    file_icon = serializers.SerializerMethodField()
    file_size_display = serializers.CharField(read_only=True)
    period_display = serializers.CharField(read_only=True)
    can_preview = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()
    preview_url = serializers.SerializerMethodField()
    
    class Meta:
        model = PayrollRecord
        fields = [
            'id', 'uuid', 'title', 'record_type', 'description', 'notes',
            'file', 'original_filename', 'file_type', 'file_icon',
            'mime_type', 'file_size', 'file_size_display', 'file_hash',
            'period_month', 'period_year', 'period_display',
            'period_start_date', 'period_end_date',
            'category', 'employee', 'department',
            'status', 'is_starred', 'is_archived', 'is_public',
            'view_count', 'download_count', 'last_viewed_at', 'last_downloaded_at',
            'verified_by', 'verified_at', 'approved_by', 'approved_at',
            'can_preview', 'download_url', 'preview_url',
            'created_at', 'updated_at', 'created_by',
        ]
    
    def get_file_icon(self, obj):
        icon_class, color = get_file_icon(obj.file_type)
        return {'class': icon_class, 'color': color}
    
    def get_can_preview(self, obj):
        return obj.can_preview
    
    def get_download_url(self, obj):
        return f'/payroll/records/{obj.id}/download/'
    
    def get_preview_url(self, obj):
        if obj.can_preview:
            return f'/payroll/records/{obj.id}/preview/'
        return None


class PayrollCategorySerializer(serializers.ModelSerializer):
    """Serializer for PayrollCategory model."""
    
    record_count = serializers.SerializerMethodField()
    
    class Meta:
        model = PayrollCategory
        fields = [
            'id', 'name', 'category_type', 'description',
            'color', 'icon', 'is_active', 'record_count',
            'created_at', 'updated_at',
        ]
    
    def get_record_count(self, obj):
        return obj.record_count


class PayrollTemplateSerializer(serializers.ModelSerializer):
    """Serializer for PayrollTemplate model."""
    
    column_count = serializers.SerializerMethodField()
    source_file_title = serializers.CharField(source='source_file.title', read_only=True)
    
    class Meta:
        model = PayrollTemplate
        fields = [
            'id', 'name', 'description', 'record_type',
            'columns', 'column_count', 'default_tags',
            'source_file', 'source_file_title',
            'usage_count', 'is_active', 'is_default',
            'created_at', 'updated_at',
        ]
    
    def get_column_count(self, obj):
        return len(obj.columns) if obj.columns else 0


class PayrollEntrySerializer(serializers.ModelSerializer):
    """Serializer for PayrollEntry model."""
    
    template_name = serializers.CharField(source='template.name', read_only=True)
    period_display = serializers.SerializerMethodField()
    
    class Meta:
        model = PayrollEntry
        fields = [
            'id', 'title', 'template', 'template_name',
            'period_month', 'period_year', 'period_display',
            'period_start_date', 'period_end_date',
            'data', 'row_count', 'status',
            'total_gross', 'total_deductions', 'total_net',
            'notes', 'approved_by', 'approved_at',
            'created_at', 'updated_at',
        ]
    
    def get_period_display(self, obj):
        if obj.period_month and obj.period_year:
            from datetime import date
            d = date(obj.period_year, obj.period_month, 1)
            return d.strftime('%B %Y')
        return None


class ExtractedPayrollDataSerializer(serializers.ModelSerializer):
    """Serializer for ExtractedPayrollData model."""
    
    period_display = serializers.SerializerMethodField()
    employee_name = serializers.SerializerMethodField()
    
    class Meta:
        model = ExtractedPayrollData
        fields = [
            'id', 'record', 'employee', 'employee_name',
            'period_month', 'period_year', 'period_display',
            'extraction_method', 'raw_data', 'structured_data',
            'employee_name', 'employee_id_number',
            'basic_salary', 'gross_salary', 'net_salary',
            'total_allowances', 'total_deductions',
            'pension', 'nhf', 'tax', 'other_deductions',
            'is_verified', 'verified_by', 'verified_at',
            'is_linked', 'confidence_score',
            'created_at', 'updated_at',
        ]
    
    def get_period_display(self, obj):
        if obj.period_month and obj.period_year:
            from datetime import date
            d = date(obj.period_year, obj.period_month, 1)
            return d.strftime('%B %Y')
        return None
    
    def get_employee_name(self, obj):
        if obj.employee:
            return str(obj.employee)
        return obj.employee_name


class BaseTenantViewSet(viewsets.ModelViewSet):
    """Base ViewSet with tenant filtering."""
    
    permission_classes = [permissions.IsAuthenticated, DjangoModelPermissions]
    account_lookup = "company__account"
    
    def get_queryset(self):
        qs = super().get_queryset()
        return drf_filter_queryset_for_user(qs, self.request, account_lookup=self.account_lookup)
    
    def perform_create(self, serializer):
        account = get_account_for_user(self.request.user)
        company = get_company_profile_for_user(self.request.user, self.request)
        serializer.save(account=account, company=company, created_by=self.request.user)


class PayrollRecordViewSet(BaseTenantViewSet):
    """ViewSet for PayrollRecord model."""
    
    queryset = PayrollRecord.objects.select_related(
        'employee', 'department', 'created_by', 'category'
    )
    serializer_class = None
    
    def get_serializer_class(self):
        if self.action == 'list':
            return PayrollRecordListSerializer
        return PayrollRecordDetailSerializer
    
    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.filter(is_deleted=False)
        
        query = self.request.query_params.get('q', '')
        if query:
            qs = qs.filter(
                Q(title__icontains=query) |
                Q(original_filename__icontains=query) |
                Q(description__icontains=query) |
                Q(tags__icontains=query)
            )
        
        record_type = self.request.query_params.get('record_type')
        if record_type:
            qs = qs.filter(record_type=record_type)
        
        file_type = self.request.query_params.get('file_type')
        if file_type:
            qs = qs.filter(file_type=file_type)
        
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        
        year = self.request.query_params.get('year')
        if year:
            qs = qs.filter(period_year=int(year))
        
        month = self.request.query_params.get('month')
        if month:
            qs = qs.filter(period_month=int(month))
        
        show_archived = self.request.query_params.get('archived', 'false') == 'true'
        if not show_archived:
            qs = qs.filter(is_archived=False)
        
        starred_only = self.request.query_params.get('starred', 'false') == 'true'
        if starred_only:
            qs = qs.filter(is_starred=True)
        
        return qs.order_by('-created_at')
    
    @action(detail=True, methods=['post'])
    def toggle_star(self, request, pk=None):
        record = self.get_object()
        record.is_starred = not record.is_starred
        record.save(update_fields=['is_starred', 'updated_at'])
        return Response({'is_starred': record.is_starred})
    
    @action(detail=True, methods=['post'])
    def toggle_archive(self, request, pk=None):
        record = self.get_object()
        record.is_archived = not record.is_archived
        if record.is_archived:
            record.status = 'archived'
        else:
            record.status = 'draft'
        record.save(update_fields=['is_archived', 'status', 'updated_at'])
        return Response({
            'is_archived': record.is_archived,
            'status': record.status
        })
    
    @action(detail=True, methods=['post'])
    def verify(self, request, pk=None):
        record = self.get_object()
        record.verify(request.user)
        log_access(request, record, 'verify')
        return Response({
            'status': record.status,
            'verified_by': str(record.verified_by),
            'verified_at': record.verified_at.isoformat() if record.verified_at else None
        })
    
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        record = self.get_object()
        if record.status != 'verified':
            return Response(
                {'error': 'Record must be verified before approval'},
                status=status.HTTP_400_BAD_REQUEST
            )
        record.approve(request.user)
        log_access(request, record, 'approve')
        return Response({
            'status': record.status,
            'approved_by': str(record.approved_by),
            'approved_at': record.approved_at.isoformat() if record.approved_at else None
        })


class PayrollCategoryViewSet(BaseTenantViewSet):
    """ViewSet for PayrollCategory model."""
    
    queryset = PayrollCategory.objects.all()
    serializer_class = PayrollCategorySerializer
    
    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.filter(is_active=True)
        
        category_type = self.request.query_params.get('category_type')
        if category_type:
            qs = qs.filter(category_type=category_type)
        
        return qs.order_by('name')


class PayrollTemplateViewSet(BaseTenantViewSet):
    """ViewSet for PayrollTemplate model."""
    
    queryset = PayrollTemplate.objects.all()
    serializer_class = PayrollTemplateSerializer
    
    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.filter(is_active=True)
        
        record_type = self.request.query_params.get('record_type')
        if record_type:
            qs = qs.filter(record_type=record_type)
        
        return qs.order_by('-created_at')


class PayrollEntryViewSet(BaseTenantViewSet):
    """ViewSet for PayrollEntry model."""
    
    queryset = PayrollEntry.objects.select_related('template', 'created_by')
    serializer_class = PayrollEntrySerializer
    
    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.filter(is_deleted=False)
        
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        
        year = self.request.query_params.get('year')
        if year:
            qs = qs.filter(period_year=int(year))
        
        template_id = self.request.query_params.get('template')
        if template_id:
            qs = qs.filter(template_id=template_id)
        
        return qs.order_by('-created_at')


class ExtractedPayrollDataViewSet(BaseTenantViewSet):
    """ViewSet for ExtractedPayrollData model."""
    
    queryset = ExtractedPayrollData.objects.select_related('record', 'employee')
    serializer_class = ExtractedPayrollDataSerializer
    
    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.filter(is_deleted=False)
        
        verified = self.request.query_params.get('verified')
        if verified is not None:
            qs = qs.filter(is_verified=verified.lower() == 'true')
        
        linked = self.request.query_params.get('linked')
        if linked is not None:
            qs = qs.filter(is_linked=linked.lower() == 'true')
        
        return qs.order_by('-created_at')


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def api_record_list(request):
    """API endpoint for listing payroll records."""
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return Response({'error': 'Company not found'}, status=403)
    
    qs = PayrollRecord.objects.filter(
        company=company, is_deleted=False
    ).select_related(
        'employee', 'department', 'category', 'created_by'
    ).order_by('-created_at')
    
    record_type = request.query_params.get('record_type')
    if record_type:
        qs = qs.filter(record_type=record_type)
    
    file_type = request.query_params.get('file_type')
    if file_type:
        qs = qs.filter(file_type=file_type)
    
    status_filter = request.query_params.get('status')
    if status_filter:
        qs = qs.filter(status=status_filter)
    
    page_size = int(request.query_params.get('page_size', 25))
    page = int(request.query_params.get('page', 1))
    
    start = (page - 1) * page_size
    end = start + page_size
    
    records = qs[start:end]
    total_count = qs.count()
    
    serializer = PayrollRecordListSerializer(records, many=True)
    
    return Response({
        'results': serializer.data,
        'count': total_count,
        'page': page,
        'page_size': page_size,
        'total_pages': (total_count + page_size - 1) // page_size,
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def api_record_detail(request, record_id):
    """API endpoint for getting payroll record details."""
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return Response({'error': 'Company not found'}, status=403)
    
    try:
        record = PayrollRecord.objects.get(
            pk=record_id,
            company=company,
            is_deleted=False
        )
    except PayrollRecord.DoesNotExist:
        return Response({'error': 'Record not found'}, status=404)
    
    record.increment_view_count()
    log_access(request, record, 'view')
    
    serializer = PayrollRecordDetailSerializer(record)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def api_record_upload(request):
    """API endpoint for uploading payroll records."""
    company = get_company_profile_for_user(request.user, request)
    account = get_account_for_user(request.user)
    
    if not company:
        return Response({'error': 'Company not found'}, status=403)
    
    files = request.FILES.getlist('files')
    
    if not files:
        return Response({'error': 'No files provided'}, status=400)
    
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
                record_type=request.data.get('record_type', 'other'),
                file=uploaded_file,
                original_filename=result.get('original_filename', uploaded_file.name),
                file_type=result.get('file_type', 'other'),
                mime_type=result.get('mime_type', ''),
                file_size=result.get('file_size', uploaded_file.size),
                file_hash=result.get('file_hash', ''),
                period_month=result.get('period_month'),
                period_year=result.get('period_year'),
                status='draft',
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
    
    return Response({
        'results': results,
        'uploaded_count': sum(1 for r in results if r.get('success')),
        'error_count': sum(1 for r in results if r.get('error'))
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def api_record_delete(request):
    """API endpoint for deleting payroll records."""
    company = get_company_profile_for_user(request.user, request)
    
    if not company:
        return Response({'error': 'Company not found'}, status=403)
    
    record_id = request.data.get('id')
    
    if not record_id:
        return Response({'error': 'Record ID required'}, status=400)
    
    try:
        record = PayrollRecord.objects.get(
            pk=record_id,
            company=company,
            is_deleted=False
        )
        record.is_deleted = True
        record.save(update_fields=['is_deleted', 'updated_at'])
        return Response({'success': True})
    except PayrollRecord.DoesNotExist:
        return Response({'error': 'Record not found'}, status=404)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def api_record_download(request, record_id):
    """API endpoint for downloading payroll records."""
    company = get_company_profile_for_user(request.user, request)
    
    if not company:
        return Response({'error': 'Company not found'}, status=403)
    
    try:
        record = PayrollRecord.objects.get(
            pk=record_id,
            company=company,
            is_deleted=False
        )
    except PayrollRecord.DoesNotExist:
        return Response({'error': 'Record not found'}, status=404)
    
    if not record.file:
        return Response({'error': 'File not found'}, status=404)
    
    record.increment_download_count()
    log_access(request, record, 'download')
    
    return Response({
        'download_url': record.file.url,
        'filename': record.original_filename,
        'mime_type': record.mime_type,
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def api_record_stats(request):
    """API endpoint for getting payroll record statistics."""
    company = get_company_profile_for_user(request.user, request)
    
    if not company:
        return Response({'error': 'Company not found'}, status=403)
    
    stats = calculate_record_stats(company)
    return Response(stats)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def api_bulk_action(request):
    """API endpoint for bulk actions on payroll records."""
    company = get_company_profile_for_user(request.user, request)
    
    if not company:
        return Response({'error': 'Company not found'}, status=403)
    
    action = request.data.get('action')
    record_ids = request.data.get('ids', [])
    
    if not action or not record_ids:
        return Response({'error': 'Action and IDs required'}, status=400)
    
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
    
    return Response({
        'success_count': success_count,
        'error_count': error_count
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def api_search(request):
    """API endpoint for searching payroll records."""
    company = get_company_profile_for_user(request.user, request)
    
    if not company:
        return Response({'error': 'Company not found'}, status=403)
    
    query = request.query_params.get('q', '')
    record_type = request.query_params.get('record_type')
    file_type = request.query_params.get('file_type')
    status_filter = request.query_params.get('status')
    year = request.query_params.get('year')
    month = request.query_params.get('month')
    
    qs = PayrollRecord.objects.filter(
        company=company, is_deleted=False, is_archived=False
    ).select_related('employee', 'department', 'category')
    
    if query:
        qs = qs.filter(
            Q(title__icontains=query) |
            Q(original_filename__icontains=query) |
            Q(description__icontains=query) |
            Q(tags__icontains=query)
        )
    
    if record_type:
        qs = qs.filter(record_type=record_type)
    
    if file_type:
        qs = qs.filter(file_type=file_type)
    
    if status_filter:
        qs = qs.filter(status=status_filter)
    
    if year:
        qs = qs.filter(period_year=int(year))
    
    if month:
        qs = qs.filter(period_month=int(month))
    
    records = qs[:50]
    serializer = PayrollRecordListSerializer(records, many=True)
    
    return Response({
        'results': serializer.data,
        'count': len(records)
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def api_share_create(request):
    """API endpoint for creating share links."""
    company = get_company_profile_for_user(request.user, request)
    
    if not company:
        return Response({'error': 'Company not found'}, status=403)
    
    record_id = request.data.get('record_id')
    if not record_id:
        return Response({'error': 'Record ID required'}, status=400)
    
    try:
        record = PayrollRecord.objects.get(
            pk=record_id,
            company=company,
            is_deleted=False
        )
    except PayrollRecord.DoesNotExist:
        return Response({'error': 'Record not found'}, status=404)
    
    share = generate_share_link(
        record=record,
        shared_by=request.user,
        shared_with_email=request.data.get('email', ''),
        permission_view=request.data.get('permission_view', True),
        permission_download=request.data.get('permission_download', True),
        permission_print=request.data.get('permission_print', False),
        expires_in_days=request.data.get('expires_in_days'),
        max_access_count=request.data.get('max_access_count', 0),
    )
    
    share_url = f'/payroll/share/{share.share_token}/'
    
    return Response({
        'share_id': share.id,
        'share_url': share_url,
        'token': share.share_token,
        'expires_at': share.expires_at.isoformat() if share.expires_at else None,
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def api_share_revoke(request, share_id):
    """API endpoint for revoking share links."""
    company = get_company_profile_for_user(request.user, request)
    
    if not company:
        return Response({'error': 'Company not found'}, status=403)
    
    try:
        share = PayrollRecordShare.objects.get(
            pk=share_id,
            record__company=company,
            is_active=True
        )
        share.is_active = False
        share.save(update_fields=['is_active', 'updated_at'])
        return Response({'success': True})
    except PayrollRecordShare.DoesNotExist:
        return Response({'error': 'Share not found'}, status=404)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def api_access_logs(request):
    """API endpoint for accessing payroll record access logs."""
    company = get_company_profile_for_user(request.user, request)
    
    if not company:
        return Response({'error': 'Company not found'}, status=403)
    
    record_id = request.query_params.get('record_id')
    
    qs = PayrollRecordAccessLog.objects.filter(
        company=company,
        record__is_deleted=False
    ).select_related('record', 'user').order_by('-created_at')
    
    if record_id:
        qs = qs.filter(record_id=record_id)
    
    page_size = int(request.query_params.get('page_size', 50))
    page = int(request.query_params.get('page', 1))
    
    start = (page - 1) * page_size
    end = start + page_size
    
    logs = qs[start:end]
    
    results = [
        {
            'id': log.id,
            'record_id': log.record_id,
            'record_title': str(log.record),
            'action': log.action,
            'user': str(log.user) if log.user else None,
            'ip_address': log.ip_address,
            'created_at': log.created_at.isoformat(),
        }
        for log in logs
    ]
    
    return Response({
        'results': results,
        'page': page,
        'page_size': page_size,
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def api_notifications(request):
    """API endpoint for getting user notifications."""
    notifications = get_user_unread_notifications(request.user)
    
    results = [
        {
            'id': n.id,
            'notification_type': n.notification_type,
            'title': n.title,
            'message': n.message,
            'record_id': n.record_id if n.record else None,
            'is_read': n.is_read,
            'priority': n.priority,
            'link': n.link,
            'created_at': n.created_at.isoformat(),
        }
        for n in notifications
    ]
    
    return Response({'results': results, 'count': len(results)})


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def api_mark_notification_read(request, notification_id):
    """API endpoint for marking notification as read."""
    success = mark_notification_as_read(notification_id, request.user)
    return Response({'success': success})


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def api_dashboard_stats(request):
    """API endpoint for getting dashboard statistics (real-time)."""
    from datetime import date
    
    company = get_company_profile_for_user(request.user, request)
    
    if not company:
        return Response({'error': 'Company not found'}, status=403)
    
    records_qs = PayrollRecord.objects.filter(company=company, is_deleted=False)
    
    total_records = records_qs.count()
    
    by_status = {}
    for status, label in PayrollRecord.STATUS_CHOICES:
        count = records_qs.filter(status=status).count()
        if count > 0:
            by_status[status] = {'label': label, 'count': count}
    
    by_type = {}
    for rt, label in PayrollRecord.RECORD_TYPE_CHOICES:
        count = records_qs.filter(record_type=rt).count()
        if count > 0:
            by_type[rt] = {'label': label, 'count': count}
    
    pending_count = records_qs.filter(status='draft').count()
    verified_count = records_qs.filter(status='verified').count()
    approved_count = records_qs.filter(status='approved').count()
    
    total_size = sum(r.file_size or 0 for r in records_qs)
    
    def format_size(size):
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        return f"{size / (1024 * 1024 * 1024):.1f} GB"
    
    return Response({
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
        'total_views': sum(r.view_count or 0 for r in records_qs),
        'total_downloads': sum(r.download_count or 0 for r in records_qs),
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def api_record_file_data(request, record_id):
    """API endpoint for getting raw file data for client-side preview."""
    company = get_company_profile_for_user(request.user, request)
    
    if not company:
        return Response({'error': 'Company not found'}, status=403)
    
    try:
        record = PayrollRecord.objects.get(
            pk=record_id,
            company=company,
            is_deleted=False
        )
    except PayrollRecord.DoesNotExist:
        return Response({'error': 'Record not found'}, status=404)
    
    if not record.file:
        return Response({'error': 'File not found'}, status=404)
    
    try:
        with open(record.file.path, 'rb') as f:
            file_content = f.read()
        return Response(
            file_content,
            content_type=record.mime_type or 'application/octet-stream',
            headers={
                'Content-Disposition': f'inline; filename="{record.original_filename}"',
            }
        )
    except IOError:
        return Response({'error': 'Unable to read file'}, status=500)
