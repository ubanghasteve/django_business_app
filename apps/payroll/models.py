"""
Smart Payroll Records Models
============================
Comprehensive payroll record management with multi-tenant support,
RBAC permissions, and smart file handling for PDF, Word, Excel, and images.
"""

import uuid
import os
import mimetypes
import urllib.parse
from datetime import date
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.validators import FileExtensionValidator
from django.core.files.storage import default_storage


class TenantOwnedManager(models.Manager):
    """Manager that automatically filters by tenant (account/company)."""
    
    def for_tenant(self, account_id=None, company_id=None):
        """Filter queryset by tenant."""
        qs = self.get_queryset()
        if account_id:
            qs = qs.filter(account_id=account_id)
        if company_id:
            qs = qs.filter(company_id=company_id)
        return qs
    
    def for_user(self, user):
        """Filter queryset based on user's tenant."""
        from apps.core.ownership import get_account_for_user
        from apps.core.utils import get_company_profile_for_user
        
        account = get_account_for_user(user)
        company = get_company_profile_for_user(user, None)
        
        qs = self.get_queryset()
        if account:
            qs = qs.filter(account_id=account.id)
        if company:
            qs = qs.filter(company_id=company.id)
        return qs


class SyncMixin(models.Model):
    """Mixin for sync-enabled models with UUID and soft delete."""
    
    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        help_text="Unique identifier for offline sync"
    )
    is_deleted = models.BooleanField(
        default=False,
        help_text="Soft delete flag for sync systems"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        abstract = True


class PayrollRecord(SyncMixin):
    """
    Main payroll record model that stores uploaded payroll documents.
    Supports PDF, Word, Excel, and image files.
    """
    
    FILE_TYPE_CHOICES = [
        ('pdf', 'PDF Document'),
        ('word', 'Word Document'),
        ('excel', 'Excel Spreadsheet'),
        ('image', 'Image'),
        ('csv', 'CSV File'),
        ('text', 'Text File'),
        ('other', 'Other'),
    ]
    
    RECORD_TYPE_CHOICES = [
        ('payslip', 'Payslip'),
        ('payroll_summary', 'Payroll Summary'),
        ('bank_transfer', 'Bank Transfer List'),
        ('tax_document', 'Tax Document'),
        ('pension_report', 'Pension Report'),
        ('nhf_contribution', 'NHF Contribution'),
        ('loan_schedule', 'Loan Repayment Schedule'),
        ('bonus_record', 'Bonus Record'),
        ('allowance_record', 'Allowance Record'),
        ('deduction_record', 'Deduction Record'),
        ('leave_payment', 'Leave Payment'),
        ('termination_payment', 'Termination Payment'),
        (' thirteenth_month', '13th Month Pay'),
        ('other', 'Other'),
    ]
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('verified', 'Verified'),
        ('approved', 'Approved'),
        ('archived', 'Archived'),
    ]
    
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='smart_payroll_records',
        null=True,
        blank=True,
        help_text='Tenant account for multi-tenancy'
    )
    
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='smart_payroll_records',
        null=True,
        blank=True,
        help_text='Company for data isolation'
    )
    
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='smart_payroll_records_created'
    )
    
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='smart_payroll_records_updated'
    )
    
    title = models.CharField(
        max_length=255,
        help_text='Title/description of the payroll record'
    )
    
    record_type = models.CharField(
        max_length=30,
        choices=RECORD_TYPE_CHOICES,
        default='payslip',
        help_text='Type of payroll record'
    )
    
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft',
        help_text='Verification status'
    )
    
    file = models.FileField(
        upload_to='payroll/records/%Y/%m/',
        max_length=500,
        help_text='The uploaded payroll document file'
    )
    
    original_filename = models.CharField(
        max_length=255,
        help_text='Original filename when uploaded'
    )
    
    file_type = models.CharField(
        max_length=10,
        choices=FILE_TYPE_CHOICES,
        default='other',
        help_text='Detected file type'
    )
    
    mime_type = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text='MIME type of the file'
    )
    
    file_size = models.BigIntegerField(
        default=0,
        help_text='File size in bytes'
    )
    
    file_hash = models.CharField(
        max_length=64,
        blank=True,
        default='',
        help_text='SHA256 hash for integrity verification'
    )
    
    employee = models.ForeignKey(
        'hr_staff.Employee',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payroll_records',
        help_text='Associated employee (if applicable)'
    )
    
    department = models.ForeignKey(
        'hr_staff.Department',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payroll_records',
        help_text='Department for this record'
    )
    
    category = models.ForeignKey(
        'PayrollCategory',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payroll_records',
        help_text='Category for organizing records'
    )
    
    period_month = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text='Pay period month (1-12)'
    )
    
    period_year = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text='Pay period year'
    )
    
    period_start_date = models.DateField(
        null=True,
        blank=True,
        help_text='Start date of the pay period'
    )
    
    period_end_date = models.DateField(
        null=True,
        blank=True,
        help_text='End date of the pay period'
    )
    
    description = models.TextField(
        blank=True,
        default='',
        help_text='Additional description or notes'
    )
    
    notes = models.TextField(
        blank=True,
        default='',
        help_text='Internal notes (not visible to employees)'
    )
    
    tags = models.CharField(
        max_length=500,
        blank=True,
        default='',
        help_text='Comma-separated tags for easy searching'
    )
    
    is_starred = models.BooleanField(
        default=False,
        help_text='Mark as starred for quick access'
    )
    
    is_archived = models.BooleanField(
        default=False,
        help_text='Archive old records'
    )
    
    is_public = models.BooleanField(
        default=False,
        help_text='Make visible to employees'
    )
    
    view_count = models.PositiveIntegerField(
        default=0,
        help_text='Number of times this record has been viewed'
    )
    
    download_count = models.PositiveIntegerField(
        default=0,
        help_text='Number of times this record has been downloaded'
    )
    
    last_viewed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Last time this record was viewed'
    )
    
    last_downloaded_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Last time this record was downloaded'
    )
    
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payroll_records_verified'
    )
    
    verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the record was verified'
    )
    
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payroll_records_approved'
    )
    
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the record was approved'
    )
    
    objects = TenantOwnedManager()
    
    class Meta:
        verbose_name = 'Smart Payroll Record'
        verbose_name_plural = 'Smart Payroll Records'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['account', 'company']),
            models.Index(fields=['period_year', 'period_month']),
            models.Index(fields=['record_type']),
            models.Index(fields=['file_type']),
            models.Index(fields=['employee', 'period_year', 'period_month']),
            models.Index(fields=['status']),
            models.Index(fields=['-created_at']),
            models.Index(fields=['-updated_at']),
            models.Index(fields=['is_archived', 'is_starred']),
            models.Index(fields=['company', 'is_deleted', '-created_at']),
            models.Index(fields=['company', 'status', '-created_at']),
        ]
    
    def __str__(self):
        return self.title
    
    def save(self, *args, **kwargs):
        if self.file and not self.file_size:
            self.file_size = self.file.size
        if self.file and not self.mime_type:
            self.mime_type = self._detect_mime_type()
        if self.file and not self.original_filename:
            self.original_filename = self.file.name
        super().save(*args, **kwargs)
    
    def _detect_mime_type(self):
        """Detect MIME type from file extension."""
        if self.file:
            ext = os.path.splitext(self.file.name)[1].lower()
            mime_type = mimetypes.types_map.get(ext, 'application/octet-stream')
            return mime_type
        return 'application/octet-stream'
    
    @property
    def file_size_display(self):
        """Human-readable file size."""
        if self.file_size < 1024:
            return f"{self.file_size} B"
        elif self.file_size < 1024 * 1024:
            return f"{self.file_size / 1024:.1f} KB"
        elif self.file_size < 1024 * 1024 * 1024:
            return f"{self.file_size / (1024 * 1024):.1f} MB"
        return f"{self.file_size / (1024 * 1024 * 1024):.1f} GB"
    
    @property
    def period_display(self):
        """Human-readable pay period."""
        if self.period_month and self.period_year:
            try:
                d = date(self.period_year, self.period_month, 1)
                return d.strftime("%B %Y")
            except ValueError:
                pass
        return None
    
    @property
    def file_extension(self):
        """Get file extension."""
        if self.file:
            return os.path.splitext(self.file.name)[1].lower()
        return ''
    
    @property
    def can_preview(self):
        """Check if file can be previewed in browser."""
        preview_types = ['pdf', 'image', 'word', 'excel']
        return self.file_type in preview_types
    
    @property
    def preview_type(self):
        """Return the preview type: 'native', 'google_docs', or 'office'."""
        if self.file_type in ['pdf', 'image']:
            return 'native'
        elif self.file_type in ['word', 'excel']:
            return 'google_docs'
        return 'none'
    
    def get_file_url(self):
        """Get the file URL (relative path)."""
        if not self.file:
            return None
        return self.file.url
    
    def get_preview_url(self, request=None):
        """Get the appropriate preview URL for this file.
        
        For native types (PDF, images), returns the file URL directly.
        For Google Docs types (Word, Excel), builds full Google Docs viewer URL.
        """
        if not self.file:
            return None
        
        file_url = self.file.url
        
        if self.file_type in ['pdf', 'image']:
            return file_url
        
        if self.file_type in ['word', 'excel']:
            if request:
                absolute_url = request.build_absolute_uri(file_url)
            else:
                absolute_url = file_url
            encoded_url = urllib.parse.quote(absolute_url)
            return f'https://docs.google.com/gview?url={encoded_url}&embedded=true'
        
        return None
    
    def increment_view_count(self):
        """Increment view count and update last viewed timestamp."""
        self.view_count += 1
        self.last_viewed_at = timezone.now()
        self.save(update_fields=['view_count', 'last_viewed_at'])
    
    def increment_download_count(self):
        """Increment download count and update last downloaded timestamp."""
        self.download_count += 1
        self.last_downloaded_at = timezone.now()
        self.save(update_fields=['download_count', 'last_downloaded_at'])
    
    def verify(self, user):
        """Mark record as verified."""
        self.status = 'verified'
        self.verified_by = user
        self.verified_at = timezone.now()
        self.save(update_fields=['status', 'verified_by', 'verified_at'])
    
    def approve(self, user):
        """Mark record as approved."""
        self.status = 'approved'
        self.approved_by = user
        self.approved_at = timezone.now()
        self.save(update_fields=['status', 'approved_by', 'approved_at'])
    
    def archive(self):
        """Archive the record."""
        self.is_archived = True
        self.status = 'archived'
        self.save(update_fields=['is_archived', 'status'])
    
    def unarchive(self):
        """Unarchive the record."""
        self.is_archived = False
        self.status = 'draft'
        self.save(update_fields=['is_archived', 'status'])


class PayrollCategory(SyncMixin):
    """
    Categories for organizing payroll records.
    """
    
    CATEGORY_TYPES = [
        ('payslip', 'Payslips'),
        ('report', 'Reports'),
        ('bank_transfer', 'Bank Transfers'),
        ('tax_document', 'Tax Documents'),
        ('pension', 'Pension Documents'),
        ('nhf', 'NHF Documents'),
        ('loan', 'Loan Documents'),
        ('bonus', 'Bonus Documents'),
        ('allowance', 'Allowance Documents'),
        ('deduction', 'Deduction Documents'),
        ('leave', 'Leave Payment Documents'),
        ('termination', 'Termination Documents'),
        ('other', 'Other'),
    ]
    
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='smart_payroll_categories',
        null=True,
        blank=True,
    )
    
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='smart_payroll_categories',
        null=True,
        blank=True,
    )
    
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payroll_categories_created',
    )
    
    name = models.CharField(max_length=100)
    
    category_type = models.CharField(
        max_length=20,
        choices=CATEGORY_TYPES,
        default='other'
    )
    
    description = models.TextField(blank=True, default='')
    
    is_active = models.BooleanField(default=True)
    
    color = models.CharField(max_length=7, default='#1976d2')
    
    icon = models.CharField(max_length=50, default='file-document')
    
    objects = TenantOwnedManager()
    
    class Meta:
        verbose_name = 'Payroll Category'
        verbose_name_plural = 'Payroll Categories'
        ordering = ['name']
        unique_together = ['company', 'name']
    
    def __str__(self):
        return self.name
    
    @property
    def record_count(self):
        """Get count of records in this category."""
        return self.payroll_records.filter(is_deleted=False).count()


class PayrollRecordAccessLog(models.Model):
    """
    Audit log for payroll record access (view/download).
    """
    
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)
    
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='smart_payroll_access_logs',
        null=True,
        blank=True,
    )
    
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='smart_payroll_access_logs',
        null=True,
        blank=True,
    )
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payroll_access_logs',
    )
    
    record = models.ForeignKey(
        PayrollRecord,
        on_delete=models.CASCADE,
        related_name='access_logs',
    )
    
    action = models.CharField(
        max_length=20,
        choices=[
            ('view', 'View'),
            ('download', 'Download'),
            ('preview', 'Preview'),
            ('print', 'Print'),
            ('share', 'Share'),
            ('verify', 'Verify'),
            ('approve', 'Approve'),
            ('archive', 'Archive'),
            ('delete', 'Delete'),
        ]
    )
    
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    
    user_agent = models.CharField(max_length=500, blank=True, default='')
    
    session_id = models.CharField(max_length=100, blank=True, default='')
    
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        verbose_name = 'Payroll Access Log'
        verbose_name_plural = 'Payroll Access Logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['account', 'company']),
            models.Index(fields=['record', 'action']),
            models.Index(fields=['user', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.user} - {self.action} - {self.record}"


class PayrollRecordShare(models.Model):
    """
    Model for tracking payroll record shares.
    """
    
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)
    
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='smart_payroll_shares',
        null=True,
        blank=True,
    )
    
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='smart_payroll_shares',
        null=True,
        blank=True,
    )
    
    record = models.ForeignKey(
        PayrollRecord,
        on_delete=models.CASCADE,
        related_name='shares',
    )
    
    shared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payroll_shares_sent',
    )
    
    shared_with = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payroll_shares_received',
    )
    
    shared_with_email = models.EmailField(blank=True, default='')
    
    share_token = models.CharField(max_length=64, unique=True)
    
    expires_at = models.DateTimeField(null=True, blank=True)
    
    access_count = models.PositiveIntegerField(default=0)
    
    max_access_count = models.PositiveIntegerField(default=0)
    
    is_active = models.BooleanField(default=True)
    
    permission_view = models.BooleanField(default=True)
    
    permission_download = models.BooleanField(default=True)
    
    permission_print = models.BooleanField(default=False)
    
    class Meta:
        verbose_name = 'Payroll Share'
        verbose_name_plural = 'Payroll Shares'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Share: {self.record} -> {self.shared_with or self.shared_with_email}"
    
    @property
    def is_expired(self):
        """Check if share link has expired."""
        if self.expires_at:
            return timezone.now() > self.expires_at
        return False


class ExtractedPayrollData(SyncMixin):
    """
    Stores extracted data from payroll documents.
    """
    
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='smart_extracted_payroll_data',
        null=True,
        blank=True,
    )
    
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='smart_extracted_payroll_data',
        null=True,
        blank=True,
    )
    
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='extracted_payroll_data_created',
    )
    
    record = models.ForeignKey(
        PayrollRecord,
        on_delete=models.CASCADE,
        related_name='extracted_data',
        null=True,
        blank=True,
    )
    
    employee = models.ForeignKey(
        'hr_staff.Employee',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='extracted_payroll_data',
    )
    
    extraction_method = models.CharField(
        max_length=50,
        blank=True,
        default='',
        help_text='Method used for extraction (ocr, ai, manual)'
    )
    
    raw_data = models.JSONField(
        default=dict,
        help_text='Raw extracted data as JSON'
    )
    
    structured_data = models.JSONField(
        default=dict,
        help_text='Structured/extracted fields as JSON'
    )
    
    employee_name = models.CharField(max_length=255, blank=True, default='')
    
    employee_id_number = models.CharField(max_length=100, blank=True, default='')
    
    period_month = models.PositiveSmallIntegerField(null=True, blank=True)
    
    period_year = models.PositiveSmallIntegerField(null=True, blank=True)
    
    basic_salary = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True
    )
    
    gross_salary = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True
    )
    
    net_salary = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True
    )
    
    total_allowances = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True
    )
    
    total_deductions = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True
    )
    
    pension = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True
    )
    
    nhf = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True
    )
    
    tax = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True
    )
    
    other_deductions = models.JSONField(
        default=dict,
        blank=True,
        help_text='Other deductions as JSON'
    )
    
    is_verified = models.BooleanField(default=False)
    
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='extracted_data_verified'
    )
    
    verified_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    
    is_linked = models.BooleanField(
        default=False,
        help_text='Successfully linked to employee record'
    )
    
    confidence_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='AI confidence score (0-100)'
    )
    
    notes = models.TextField(blank=True, default='')
    
    class Meta:
        verbose_name = 'Extracted Payroll Data'
        verbose_name_plural = 'Extracted Payroll Data'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['account', 'company']),
            models.Index(fields=['period_year', 'period_month']),
            models.Index(fields=['employee']),
        ]
    
    def __str__(self):
        return f"{self.employee_name} - {self.period_month}/{self.period_year}"


class PayrollTemplate(SyncMixin):
    """
    Reusable payroll templates for consistent record types.
    """
    
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='smart_payroll_templates',
        null=True,
        blank=True,
    )
    
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='smart_payroll_templates',
        null=True,
        blank=True,
    )
    
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payroll_templates_created',
    )
    
    name = models.CharField(max_length=255)
    
    description = models.TextField(blank=True, default='')
    
    record_type = models.CharField(
        max_length=30,
        choices=PayrollRecord.RECORD_TYPE_CHOICES,
        default='payslip',
    )
    
    columns = models.JSONField(
        default=list,
        help_text='Template columns configuration'
    )
    
    default_tags = models.CharField(
        max_length=500,
        blank=True,
        default='',
        help_text='Default tags for records created from this template'
    )
    
    source_file = models.ForeignKey(
        PayrollRecord,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='templates_created',
    )
    
    usage_count = models.PositiveIntegerField(default=0)
    
    is_active = models.BooleanField(default=True)
    
    is_default = models.BooleanField(
        default=False,
        help_text='Set as default template for this record type'
    )
    
    objects = TenantOwnedManager()
    
    class Meta:
        verbose_name = 'Payroll Template'
        verbose_name_plural = 'Payroll Templates'
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name


class PayrollEntry(SyncMixin):
    """
    Payroll entries created from templates or manual data.
    """
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('completed', 'Completed'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('archived', 'Archived'),
    ]
    
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='smart_payroll_entries',
        null=True,
        blank=True,
    )
    
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='smart_payroll_entries',
        null=True,
        blank=True,
    )
    
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payroll_entries_created',
    )
    
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payroll_entries_updated',
    )
    
    template = models.ForeignKey(
        PayrollTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='entries',
    )
    
    title = models.CharField(max_length=255)
    
    period_month = models.PositiveSmallIntegerField(null=True, blank=True)
    
    period_year = models.PositiveSmallIntegerField(null=True, blank=True)
    
    period_start_date = models.DateField(null=True, blank=True)
    
    period_end_date = models.DateField(null=True, blank=True)
    
    data = models.JSONField(
        default=dict,
        help_text='Entry data as JSON'
    )
    
    row_count = models.PositiveIntegerField(default=0)
    
    source_record = models.ForeignKey(
        PayrollRecord,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='entries',
    )
    
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft'
    )
    
    notes = models.TextField(blank=True, default='')
    
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payroll_entries_approved'
    )
    
    approved_at = models.DateTimeField(null=True, blank=True)
    
    total_gross = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True
    )
    
    total_net = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True
    )
    
    total_deductions = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True
    )
    
    objects = TenantOwnedManager()
    
    class Meta:
        verbose_name = 'Payroll Entry'
        verbose_name_plural = 'Payroll Entries'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['account', 'company']),
            models.Index(fields=['period_year', 'period_month']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return self.title
    
    def calculate_totals(self):
        """Calculate totals from data."""
        rows = self.data.get('rows', [])
        
        total_gross = Decimal('0.00')
        total_net = Decimal('0.00')
        total_deductions = Decimal('0.00')
        
        for row in rows:
            gross = Decimal(str(row.get('gross_salary', 0) or 0))
            net = Decimal(str(row.get('net_salary', 0) or 0))
            deductions = Decimal(str(row.get('total_deductions', 0) or 0))
            
            total_gross += gross
            total_net += net
            total_deductions += deductions
        
        self.total_gross = total_gross
        self.total_net = total_net
        self.total_deductions = total_deductions
        self.save(update_fields=['total_gross', 'total_net', 'total_deductions'])


class PayrollNotification(models.Model):
    """
    Notifications for payroll record events.
    """
    
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)
    
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='smart_payroll_notifications',
        null=True,
        blank=True,
    )
    
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='smart_payroll_notifications',
        null=True,
        blank=True,
    )
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='smart_payroll_notifications',
    )
    
    record = models.ForeignKey(
        PayrollRecord,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notifications',
    )
    
    notification_type = models.CharField(
        max_length=50,
        choices=[
            ('record_uploaded', 'Record Uploaded'),
            ('record_verified', 'Record Verified'),
            ('record_approved', 'Record Approved'),
            ('record_shared', 'Record Shared'),
            ('reminder', 'Reminder'),
            ('deadline', 'Deadline'),
        ]
    )
    
    title = models.CharField(max_length=255)
    
    message = models.TextField()
    
    is_read = models.BooleanField(default=False)
    
    read_at = models.DateTimeField(null=True, blank=True)
    
    link = models.CharField(max_length=500, blank=True, default='')
    
    priority = models.CharField(
        max_length=10,
        choices=[
            ('low', 'Low'),
            ('normal', 'Normal'),
            ('high', 'High'),
            ('urgent', 'Urgent'),
        ],
        default='normal'
    )
    
    class Meta:
        verbose_name = 'Payroll Notification'
        verbose_name_plural = 'Payroll Notifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.user} - {self.title}"
    
    def mark_as_read(self):
        """Mark notification as read."""
        self.is_read = True
        self.read_at = timezone.now()
        self.save(update_fields=['is_read', 'read_at'])


class PayrollSetting(models.Model):
    """
    Company-specific payroll settings.
    """
    
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='smart_payroll_settings',
        null=True,
        blank=True,
    )
    
    company = models.OneToOneField(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='payroll_settings',
    )
    
    default_currency = models.CharField(max_length=3, default='NGN')
    
    default_pension_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('8.00'),
        help_text='Default pension contribution rate (%)'
    )
    
    default_nhf_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('2.50'),
        help_text='Default NHF contribution rate (%)'
    )
    
    default_tax_method = models.CharField(
        max_length=50,
        default='pay_as_you_earn',
        choices=[
            ('pay_as_you_earn', 'Pay As You Earn (PAYE)'),
            ('flat_rate', 'Flat Rate'),
            ('none', 'None'),
        ]
    )
    
    require_approval = models.BooleanField(
        default=True,
        help_text='Require approval for payroll records'
    )
    
    auto_verify_uploads = models.BooleanField(
        default=False,
        help_text='Auto-verify uploaded records'
    )
    
    allowed_file_types = models.JSONField(
        default=list,
        help_text='Allowed file extensions'
    )
    
    max_file_size = models.BigIntegerField(
        default=50 * 1024 * 1024,
        help_text='Max file size in bytes (default 50MB)'
    )
    
    retention_period_months = models.PositiveIntegerField(
        default=84,
        help_text='How long to keep records (months), default 7 years'
    )
    
    notify_on_upload = models.BooleanField(default=True)
    
    notify_on_approval = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = 'Payroll Setting'
        verbose_name_plural = 'Payroll Settings'
    
    def __str__(self):
        return f"Payroll Settings - {self.company}"


class PayrollStructure(models.Model):
    """Legacy model for payroll structure."""
    
    account = models.ForeignKey('core.Account', on_delete=models.CASCADE, related_name='payroll_structures', null=True, blank=True)
    company = models.ForeignKey('core.CompanyProfile', on_delete=models.CASCADE, related_name='payroll_structures', null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = 'Payroll Structure'
        verbose_name_plural = 'Payroll Structures'
        ordering = ['name']
    
    def __str__(self):
        return self.name


class EmployeePayrollProfile(models.Model):
    """Legacy model for employee payroll profile."""
    
    account = models.ForeignKey('core.Account', on_delete=models.CASCADE, related_name='employee_payroll_profiles', null=True, blank=True)
    company = models.ForeignKey('core.CompanyProfile', on_delete=models.CASCADE, related_name='employee_payroll_profiles', null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    employee = models.ForeignKey('hr_staff.Employee', on_delete=models.CASCADE, related_name='payroll_profiles')
    payroll_structure = models.ForeignKey(PayrollStructure, on_delete=models.SET_NULL, null=True, blank=True)
    
    basic_salary = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    allowance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    pension_enabled = models.BooleanField(default=True)
    nhf_enabled = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = 'Employee Payroll Profile'
        verbose_name_plural = 'Employee Payroll Profiles'
    
    def __str__(self):
        return f"{self.employee} - {self.basic_salary}"


class PayrollPeriod(models.Model):
    """Legacy model for payroll period."""
    
    account = models.ForeignKey('core.Account', on_delete=models.CASCADE, related_name='payroll_periods', null=True, blank=True)
    company = models.ForeignKey('core.CompanyProfile', on_delete=models.CASCADE, related_name='payroll_periods', null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    name = models.CharField(max_length=255)
    month = models.PositiveSmallIntegerField()
    year = models.PositiveSmallIntegerField()
    start_date = models.DateField()
    end_date = models.DateField()
    is_closed = models.BooleanField(default=False)
    
    class Meta:
        verbose_name = 'Payroll Period'
        verbose_name_plural = 'Payroll Periods'
        ordering = ['-year', '-month']
    
    def __str__(self):
        return f"{self.name} ({self.month}/{self.year})"


class PayrollRun(models.Model):
    """Legacy model for payroll run."""
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled'),
    ]
    
    account = models.ForeignKey('core.Account', on_delete=models.CASCADE, related_name='payroll_runs', null=True, blank=True)
    company = models.ForeignKey('core.CompanyProfile', on_delete=models.CASCADE, related_name='payroll_runs', null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    period = models.ForeignKey(PayrollPeriod, on_delete=models.CASCADE, related_name='runs')
    structure = models.ForeignKey(PayrollStructure, on_delete=models.SET_NULL, null=True, blank=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    total_gross = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_net = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    
    class Meta:
        verbose_name = 'Payroll Run'
        verbose_name_plural = 'Payroll Runs'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Payroll Run - {self.period}"


class PayrollItem(models.Model):
    """Legacy model for payroll item."""
    
    account = models.ForeignKey('core.Account', on_delete=models.CASCADE, related_name='payroll_items', null=True, blank=True)
    company = models.ForeignKey('core.CompanyProfile', on_delete=models.CASCADE, related_name='payroll_items', null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    payroll_run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name='items')
    employee = models.ForeignKey('hr_staff.Employee', on_delete=models.CASCADE, related_name='payroll_items')
    
    basic_salary = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    allowances = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    gross_salary = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    pension = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    nhf = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    loan_deduction = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    salary_advance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    other_deductions = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    net_salary = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    
    class Meta:
        verbose_name = 'Payroll Item'
        verbose_name_plural = 'Payroll Items'
        ordering = ['employee__last_name', 'employee__first_name']
    
    def __str__(self):
        return f"{self.employee} - {self.net_salary}"


class Payslip(models.Model):
    """Legacy model for payslip."""
    
    account = models.ForeignKey('core.Account', on_delete=models.CASCADE, related_name='payslips', null=True, blank=True)
    company = models.ForeignKey('core.CompanyProfile', on_delete=models.CASCADE, related_name='payslips', null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    employee = models.ForeignKey('hr_staff.Employee', on_delete=models.CASCADE, related_name='payslips')
    period = models.ForeignKey(PayrollPeriod, on_delete=models.CASCADE, related_name='payslips')
    payroll_item = models.ForeignKey(PayrollItem, on_delete=models.SET_NULL, null=True, blank=True, related_name='payslips')
    
    generated_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'Payslip'
        verbose_name_plural = 'Payslips'
        ordering = ['-generated_at']
    
    def __str__(self):
        return f"Payslip - {self.employee} - {self.period}"


class BonusRule(models.Model):
    """Legacy model for bonus rule."""
    
    account = models.ForeignKey('core.Account', on_delete=models.CASCADE, related_name='bonus_rules', null=True, blank=True)
    company = models.ForeignKey('core.CompanyProfile', on_delete=models.CASCADE, related_name='bonus_rules', null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    bonus_type = models.CharField(max_length=50, choices=[
        ('fixed', 'Fixed Amount'),
        ('percentage', 'Percentage'),
    ], default='fixed')
    value = models.DecimalField(max_digits=14, decimal_places=2)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = 'Bonus Rule'
        verbose_name_plural = 'Bonus Rules'
        ordering = ['name']
    
    def __str__(self):
        return self.name


class EmployeeBonus(models.Model):
    """Legacy model for employee bonus."""
    
    account = models.ForeignKey('core.Account', on_delete=models.CASCADE, related_name='employee_bonuses', null=True, blank=True)
    company = models.ForeignKey('core.CompanyProfile', on_delete=models.CASCADE, related_name='employee_bonuses', null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    employee = models.ForeignKey('hr_staff.Employee', on_delete=models.CASCADE, related_name='bonuses')
    rule = models.ForeignKey(BonusRule, on_delete=models.CASCADE, related_name='employee_bonuses')
    payroll_run = models.ForeignKey(PayrollRun, on_delete=models.SET_NULL, null=True, blank=True, related_name='bonuses')
    
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    
    class Meta:
        verbose_name = 'Employee Bonus'
        verbose_name_plural = 'Employee Bonuses'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.employee} - {self.rule.name}"


class EmployeeLoan(models.Model):
    """Legacy model for employee loan."""
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('closed', 'Closed'),
        ('defaulted', 'Defaulted'),
    ]
    
    account = models.ForeignKey('core.Account', on_delete=models.CASCADE, related_name='employee_loans', null=True, blank=True)
    company = models.ForeignKey('core.CompanyProfile', on_delete=models.CASCADE, related_name='employee_loans', null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    employee = models.ForeignKey('hr_staff.Employee', on_delete=models.CASCADE, related_name='loans')
    
    principal_amount = models.DecimalField(max_digits=14, decimal_places=2)
    outstanding_balance = models.DecimalField(max_digits=14, decimal_places=2)
    monthly_repayment_amount = models.DecimalField(max_digits=14, decimal_places=2)
    interest_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    
    class Meta:
        verbose_name = 'Employee Loan'
        verbose_name_plural = 'Employee Loans'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.employee} - {self.principal_amount}"


class LoanRepayment(models.Model):
    """Legacy model for loan repayment."""
    
    account = models.ForeignKey('core.Account', on_delete=models.CASCADE, related_name='loan_repayments', null=True, blank=True)
    company = models.ForeignKey('core.CompanyProfile', on_delete=models.CASCADE, related_name='loan_repayments', null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    loan = models.ForeignKey(EmployeeLoan, on_delete=models.CASCADE, related_name='repayments')
    payroll_item = models.ForeignKey(PayrollItem, on_delete=models.SET_NULL, null=True, blank=True, related_name='loan_repayments')
    
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    repayment_date = models.DateField()
    
    class Meta:
        verbose_name = 'Loan Repayment'
        verbose_name_plural = 'Loan Repayments'
        ordering = ['-repayment_date']
    
    def __str__(self):
        return f"{self.loan} - {self.amount}"


class SalaryAdvance(models.Model):
    """Legacy model for salary advance."""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('recovered', 'Recovered'),
    ]
    
    account = models.ForeignKey('core.Account', on_delete=models.CASCADE, related_name='salary_advances', null=True, blank=True)
    company = models.ForeignKey('core.CompanyProfile', on_delete=models.CASCADE, related_name='salary_advances', null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    employee = models.ForeignKey('hr_staff.Employee', on_delete=models.CASCADE, related_name='salary_advances')
    
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    request_date = models.DateField(auto_now_add=True)
    recovery_months = models.PositiveSmallIntegerField(default=1)
    
    class Meta:
        verbose_name = 'Salary Advance'
        verbose_name_plural = 'Salary Advances'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.employee} - {self.amount}"
