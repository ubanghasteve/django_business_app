"""
Smart Payroll Records Django Admin
================================
Admin configuration for payroll records management.
"""

from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from django.urls import reverse
from django.contrib import messages

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


@admin.register(PayrollRecord)
class PayrollRecordAdmin(admin.ModelAdmin):
    """
    Admin for PayrollRecord model.
    """
    
    list_display = [
        'title', 'record_type', 'file_type', 'status_display',
        'employee', 'period_display', 'file_size_display',
        'is_starred', 'created_at'
    ]
    
    list_filter = [
        'record_type', 'file_type', 'status', 'is_starred',
        'is_archived', 'is_public', 'company', 'created_at'
    ]
    
    search_fields = [
        'title', 'original_filename', 'description', 'tags',
        'employee__first_name', 'employee__last_name'
    ]
    
    readonly_fields = [
        'uuid', 'file_size', 'mime_type', 'file_hash',
        'view_count', 'download_count', 'last_viewed_at',
        'last_downloaded_at', 'created_at', 'updated_at',
        'verified_by', 'verified_at', 'approved_by', 'approved_at'
    ]
    
    fieldsets = [
        ('Basic Information', {
            'fields': [
                'uuid', 'title', 'record_type', 'category',
                'description', 'tags', 'file'
            ]
        }),
        ('File Information', {
            'fields': [
                'original_filename', 'file_type', 'mime_type',
                'file_size', 'file_hash'
            ],
            'classes': ('collapse',)
        }),
        ('Period Information', {
            'fields': [
                'period_month', 'period_year',
                'period_start_date', 'period_end_date'
            ]
        }),
        ('Employee & Department', {
            'fields': ['employee', 'department']
        }),
        ('Status & Visibility', {
            'fields': [
                'status', 'is_starred', 'is_archived', 'is_public'
            ]
        }),
        ('Verification', {
            'fields': [
                'verified_by', 'verified_at', 'approved_by', 'approved_at'
            ],
            'classes': ('collapse',)
        }),
        ('Statistics', {
            'fields': [
                'view_count', 'download_count',
                'last_viewed_at', 'last_downloaded_at'
            ],
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ['account', 'company', 'created_by', 'updated_by'],
            'classes': ('collapse',)
        }),
    ]
    
    date_hierarchy = 'created_at'
    
    ordering = ['-created_at']
    
    raw_id_fields = ['employee', 'department', 'created_by', 'updated_by']
    
    actions = ['verify_records', 'approve_records', 'archive_records', 'unarchive_records']
    
    def status_display(self, obj):
        """Display status with color coding."""
        colors = {
            'draft': '#6c757d',
            'verified': '#ffc107',
            'approved': '#28a745',
            'archived': '#17a2b8',
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{}</span>',
            color, obj.get_status_display()
        )
    status_display.short_description = 'Status'
    
    def period_display(self, obj):
        """Display period as formatted string."""
        if obj.period_month and obj.period_year:
            from datetime import date
            try:
                d = date(obj.period_year, obj.period_month, 1)
                return d.strftime('%B %Y')
            except ValueError:
                pass
        return '-'
    period_display.short_description = 'Period'
    
    def file_size_display(self, obj):
        """Display human-readable file size."""
        return obj.file_size_display
    file_size_display.short_description = 'Size'
    
    def verify_records(self, request, queryset):
        """Verify selected records."""
        count = 0
        for record in queryset.filter(status='draft'):
            record.verify(request.user)
            count += 1
        self.message_user(request, f'{count} record(s) verified.', messages.SUCCESS)
    verify_records.short_description = 'Verify selected records'
    
    def approve_records(self, request, queryset):
        """Approve selected records."""
        count = 0
        for record in queryset.filter(status='verified'):
            record.approve(request.user)
            count += 1
        self.message_user(request, f'{count} record(s) approved.', messages.SUCCESS)
    approve_records.short_description = 'Approve selected records'
    
    def archive_records(self, request, queryset):
        """Archive selected records."""
        count = queryset.update(is_archived=True, status='archived')
        self.message_user(request, f'{count} record(s) archived.', messages.SUCCESS)
    archive_records.short_description = 'Archive selected records'
    
    def unarchive_records(self, request, queryset):
        """Unarchive selected records."""
        count = queryset.update(is_archived=False, status='draft')
        self.message_user(request, f'{count} record(s) unarchived.', messages.SUCCESS)
    unarchive_records.short_description = 'Unarchive selected records'
    
    def get_queryset(self, request):
        """Filter by company for non-superusers."""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(company=request.user.company_profile)


@admin.register(PayrollCategory)
class PayrollCategoryAdmin(admin.ModelAdmin):
    """
    Admin for PayrollCategory model.
    """
    
    list_display = ['name', 'category_type', 'color_display', 'record_count', 'is_active', 'created_at']
    
    list_filter = ['category_type', 'is_active', 'company']
    
    search_fields = ['name', 'description']
    
    readonly_fields = ['uuid', 'created_at', 'updated_at']
    
    fieldsets = [
        ('Basic Information', {
            'fields': ['uuid', 'name', 'category_type', 'description']
        }),
        ('Appearance', {
            'fields': ['color', 'icon']
        }),
        ('Settings', {
            'fields': ['is_active']
        }),
        ('Metadata', {
            'fields': ['account', 'company', 'created_by', 'created_at', 'updated_at'],
            'classes': ('collapse',)
        }),
    ]
    
    def color_display(self, obj):
        """Display color swatch."""
        return format_html(
            '<span style="background-color: {}; display: inline-block; width: 20px; height: 20px; border-radius: 3px;"></span> {}',
            obj.color, obj.color
        )
    color_display.short_description = 'Color'
    
    def record_count(self, obj):
        """Display count of records in category."""
        return obj.record_count
    record_count.short_description = 'Records'
    
    def get_queryset(self, request):
        """Filter by company for non-superusers."""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(company=request.user.company_profile)


@admin.register(PayrollRecordAccessLog)
class PayrollRecordAccessLogAdmin(admin.ModelAdmin):
    """
    Admin for PayrollRecordAccessLog model.
    """
    
    list_display = ['record', 'action', 'user', 'ip_address', 'created_at']
    
    list_filter = ['action', 'created_at', 'company']
    
    search_fields = ['record__title', 'user__email', 'ip_address']
    
    readonly_fields = [
        'uuid', 'record', 'action', 'user', 'ip_address',
        'user_agent', 'session_id', 'metadata', 'created_at', 'updated_at'
    ]
    
    date_hierarchy = 'created_at'
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False


@admin.register(PayrollRecordShare)
class PayrollRecordShareAdmin(admin.ModelAdmin):
    """
    Admin for PayrollRecordShare model.
    """
    
    list_display = ['record', 'shared_with_display', 'share_token_short', 'is_active', 'access_count', 'expires_at', 'created_at']
    
    list_filter = ['is_active', 'permission_view', 'permission_download', 'permission_print', 'created_at']
    
    search_fields = ['record__title', 'shared_with__email', 'share_token']
    
    readonly_fields = ['uuid', 'share_token', 'access_count', 'created_at', 'updated_at']
    
    fieldsets = [
        ('Share Information', {
            'fields': ['uuid', 'record', 'shared_by', 'shared_with', 'shared_with_email']
        }),
        ('Permissions', {
            'fields': ['permission_view', 'permission_download', 'permission_print']
        }),
        ('Access Control', {
            'fields': ['expires_at', 'max_access_count', 'access_count', 'is_active']
        }),
        ('Token', {
            'fields': ['share_token'],
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ['account', 'company', 'created_at', 'updated_at'],
            'classes': ('collapse',)
        }),
    ]
    
    def shared_with_display(self, obj):
        """Display shared with user or email."""
        if obj.shared_with:
            return obj.shared_with.email
        return obj.shared_with_email or '-'
    shared_with_display.short_description = 'Shared With'
    
    def share_token_short(self, obj):
        """Display truncated share token."""
        return obj.share_token[:20] + '...' if len(obj.share_token) > 20 else obj.share_token
    share_token_short.short_description = 'Token'


@admin.register(ExtractedPayrollData)
class ExtractedPayrollDataAdmin(admin.ModelAdmin):
    """
    Admin for ExtractedPayrollData model.
    """
    
    list_display = ['employee_name', 'period_display', 'basic_salary', 'net_salary', 'is_verified', 'is_linked', 'created_at']
    
    list_filter = ['is_verified', 'is_linked', 'extraction_method', 'company', 'created_at']
    
    search_fields = ['employee_name', 'employee_id_number']
    
    readonly_fields = ['uuid', 'created_at', 'updated_at']
    
    fieldsets = [
        ('Basic Information', {
            'fields': ['uuid', 'record', 'employee', 'extraction_method']
        }),
        ('Employee', {
            'fields': ['employee_name', 'employee_id_number']
        }),
        ('Period', {
            'fields': ['period_month', 'period_year']
        }),
        ('Salary Information', {
            'fields': ['basic_salary', 'gross_salary', 'net_salary', 'total_allowances', 'total_deductions']
        }),
        ('Deductions', {
            'fields': ['pension', 'nhf', 'tax', 'other_deductions']
        }),
        ('Verification', {
            'fields': ['is_verified', 'verified_by', 'verified_at', 'is_linked', 'confidence_score']
        }),
        ('Data', {
            'fields': ['raw_data', 'structured_data'],
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ['account', 'company', 'created_by', 'created_at', 'updated_at'],
            'classes': ('collapse',)
        }),
    ]
    
    def period_display(self, obj):
        """Display period as formatted string."""
        if obj.period_month and obj.period_year:
            from datetime import date
            try:
                d = date(obj.period_year, obj.period_month, 1)
                return d.strftime('%B %Y')
            except ValueError:
                pass
        return '-'
    period_display.short_description = 'Period'


@admin.register(PayrollTemplate)
class PayrollTemplateAdmin(admin.ModelAdmin):
    """
    Admin for PayrollTemplate model.
    """
    
    list_display = ['name', 'record_type', 'usage_count', 'is_default', 'is_active', 'created_at']
    
    list_filter = ['record_type', 'is_default', 'is_active', 'company']
    
    search_fields = ['name', 'description']
    
    readonly_fields = ['uuid', 'usage_count', 'created_at', 'updated_at']
    
    fieldsets = [
        ('Basic Information', {
            'fields': ['uuid', 'name', 'description', 'record_type']
        }),
        ('Template Configuration', {
            'fields': ['columns', 'default_tags']
        }),
        ('Settings', {
            'fields': ['is_active', 'is_default']
        }),
        ('Statistics', {
            'fields': ['usage_count', 'source_file']
        }),
        ('Metadata', {
            'fields': ['account', 'company', 'created_by', 'created_at', 'updated_at'],
            'classes': ('collapse',)
        }),
    ]


@admin.register(PayrollEntry)
class PayrollEntryAdmin(admin.ModelAdmin):
    """
    Admin for PayrollEntry model.
    """
    
    list_display = ['title', 'template', 'period_display', 'row_count', 'status', 'total_gross', 'total_net', 'created_at']
    
    list_filter = ['status', 'company', 'created_at']
    
    search_fields = ['title']
    
    readonly_fields = ['uuid', 'row_count', 'total_gross', 'total_net', 'total_deductions', 'created_at', 'updated_at']
    
    fieldsets = [
        ('Basic Information', {
            'fields': ['uuid', 'title', 'template', 'source_record']
        }),
        ('Period', {
            'fields': ['period_month', 'period_year', 'period_start_date', 'period_end_date']
        }),
        ('Data', {
            'fields': ['data', 'row_count']
        }),
        ('Status', {
            'fields': ['status', 'notes']
        }),
        ('Approval', {
            'fields': ['approved_by', 'approved_at']
        }),
        ('Totals', {
            'fields': ['total_gross', 'total_deductions', 'total_net']
        }),
        ('Metadata', {
            'fields': ['account', 'company', 'created_by', 'updated_by', 'created_at', 'updated_at'],
            'classes': ('collapse',)
        }),
    ]
    
    def period_display(self, obj):
        """Display period as formatted string."""
        if obj.period_month and obj.period_year:
            from datetime import date
            try:
                d = date(obj.period_year, obj.period_month, 1)
                return d.strftime('%B %Y')
            except ValueError:
                pass
        return '-'
    period_display.short_description = 'Period'


@admin.register(PayrollNotification)
class PayrollNotificationAdmin(admin.ModelAdmin):
    """
    Admin for PayrollNotification model.
    """
    
    list_display = ['user', 'notification_type', 'title', 'is_read', 'priority', 'created_at']
    
    list_filter = ['notification_type', 'is_read', 'priority', 'created_at']
    
    search_fields = ['title', 'message', 'user__email']
    
    readonly_fields = ['uuid', 'created_at', 'updated_at']
    
    fieldsets = [
        ('Basic Information', {
            'fields': ['uuid', 'user', 'notification_type', 'record']
        }),
        ('Content', {
            'fields': ['title', 'message', 'priority']
        }),
        ('Status', {
            'fields': ['is_read', 'read_at']
        }),
        ('Navigation', {
            'fields': ['link']
        }),
        ('Metadata', {
            'fields': ['account', 'company', 'created_at', 'updated_at'],
            'classes': ('collapse',)
        }),
    ]


@admin.register(PayrollSetting)
class PayrollSettingAdmin(admin.ModelAdmin):
    """
    Admin for PayrollSetting model.
    """
    
    list_display = ['company', 'default_currency', 'require_approval', 'auto_verify_uploads', 'retention_period_months']
    
    list_filter = ['default_currency', 'require_approval', 'auto_verify_uploads']
    
    readonly_fields = ['uuid', 'created_at', 'updated_at']
    
    fieldsets = [
        ('Basic Settings', {
            'fields': ['uuid', 'company', 'default_currency']
        }),
        ('Deduction Rates', {
            'fields': ['default_pension_rate', 'default_nhf_rate', 'default_tax_method']
        }),
        ('Workflow', {
            'fields': ['require_approval', 'auto_verify_uploads']
        }),
        ('File Upload', {
            'fields': ['allowed_file_types', 'max_file_size']
        }),
        ('Notifications', {
            'fields': ['notify_on_upload', 'notify_on_approval']
        }),
        ('Data Management', {
            'fields': ['retention_period_months']
        }),
        ('Metadata', {
            'fields': ['account', 'created_at', 'updated_at'],
            'classes': ('collapse',)
        }),
    ]
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False
