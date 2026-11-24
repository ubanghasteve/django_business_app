# -*- coding: utf-8 -*-
"""
Documents app - Document model with company isolation.
All queries must filter by company (request.user.company / request.company).
"""
import os
import mimetypes
import uuid
from django.db import models
from django.conf import settings
from django.urls import reverse
from django.utils import timezone


def document_upload_path(instance, filename):
    """Upload path: documents/<company_id>/<year>/<month>/<filename>."""
    y = timezone.now().year
    m = timezone.now().month
    company_id = getattr(instance, 'company_id', None) or 0
    return f'documents/{company_id}/{y}/{m}/{filename}'


class Document(models.Model):
    """
    Uploaded financial document. Company-scoped; used in OCR → AI → finance → tax pipeline.
    """
    STATUS_PENDING = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
    ]

    DOCUMENT_TYPE_INVOICE = 'invoice'
    DOCUMENT_TYPE_RECEIPT = 'receipt'
    DOCUMENT_TYPE_TAX_FORM = 'tax_form'
    DOCUMENT_TYPE_BANK_STATEMENT = 'bank_statement'
    DOCUMENT_TYPE_ACCOUNTING_STATEMENT = 'accounting_statement'
    DOCUMENT_TYPE_OTHER = 'other'
    DOCUMENT_TYPE_CHOICES = [
        (DOCUMENT_TYPE_INVOICE, 'Invoice'),
        (DOCUMENT_TYPE_RECEIPT, 'Receipt'),
        (DOCUMENT_TYPE_TAX_FORM, 'Tax Form'),
        (DOCUMENT_TYPE_BANK_STATEMENT, 'Bank Statement'),
        (DOCUMENT_TYPE_ACCOUNTING_STATEMENT, 'Accounting Statement'),
        (DOCUMENT_TYPE_OTHER, 'Other'),
    ]

    FILE_TYPE_CHOICES = [
        ('pdf', 'PDF Document'),
        ('word', 'Word Document'),
        ('excel', 'Excel Spreadsheet'),
        ('image', 'Image'),
        ('csv', 'CSV File'),
        ('text', 'Text File'),
        ('other', 'Other'),
    ]

    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        help_text="Unique identifier for the document"
    )
    is_deleted = models.BooleanField(
        default=False,
        help_text="Soft delete flag"
    )

    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='tax_analyzer_documents',
        null=False,
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='uploaded_documents',
    )

    file = models.FileField(upload_to=document_upload_path)
    original_filename = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='Original filename when uploaded'
    )
    file_type = models.CharField(
        max_length=50,
        blank=True,
        help_text='Detected file type category (pdf, excel, word, image, etc.)'
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
    
    document_type = models.CharField(
        max_length=20,
        choices=DOCUMENT_TYPE_CHOICES,
        default=DOCUMENT_TYPE_OTHER,
    )
    processing_status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    processing_error = models.TextField(blank=True)

    title = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='Title/description of the document'
    )
    description = models.TextField(
        blank=True,
        default='',
        help_text='Additional description or notes'
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
        help_text='Archive old documents'
    )
    is_public = models.BooleanField(
        default=False,
        help_text='Make visible to other users'
    )

    view_count = models.PositiveIntegerField(
        default=0,
        help_text='Number of times this document has been viewed'
    )
    download_count = models.PositiveIntegerField(
        default=0,
        help_text='Number of times this document has been downloaded'
    )
    last_viewed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Last time this document was viewed'
    )
    last_downloaded_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Last time this document was downloaded'
    )

    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='documents_verified'
    )
    verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the document was verified'
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='documents_approved'
    )
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the document was approved'
    )

    extracted_text_preview = models.TextField(blank=True)
    ai_result_json = models.TextField(blank=True)
    extracted_tables_json = models.TextField(blank=True)
    cleaned_tables_json = models.TextField(blank=True)
    complete_extraction_json = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Document'
        verbose_name_plural = 'Documents'
        permissions = [
            ('view_tax_report', 'Can view tax reports'),
        ]
        indexes = [
            models.Index(fields=['company', 'is_deleted', '-created_at']),
            models.Index(fields=['company', 'processing_status']),
            models.Index(fields=['company', 'document_type']),
            models.Index(fields=['is_starred', 'is_archived']),
        ]

    def __str__(self):
        doc_type = self.get_document_type_display() if self.document_type else 'Document'
        return f"{doc_type} ({self.original_filename or self.file.name})"

    def get_absolute_url(self):
        return reverse('documents:detail', kwargs={'pk': self.pk})

    def save(self, *args, **kwargs):
        if self.file and not self.file_size:
            self.file_size = self.file.size
        if self.file and not self.mime_type:
            self.mime_type = self._detect_mime_type()
        if self.file and not self.original_filename:
            self.original_filename = self.file.name
        super().save(*args, **kwargs)

    def _detect_mime_type(self):
        if self.file:
            ext = os.path.splitext(self.file.name)[1].lower()
            mime_type = mimetypes.types_map.get(ext, 'application/octet-stream')
            return mime_type
        return 'application/octet-stream'

    @property
    def file_size_display(self):
        if self.file_size < 1024:
            return f"{self.file_size} B"
        elif self.file_size < 1024 * 1024:
            return f"{self.file_size / 1024:.1f} KB"
        elif self.file_size < 1024 * 1024 * 1024:
            return f"{self.file_size / (1024 * 1024):.1f} MB"
        return f"{self.file_size / (1024 * 1024 * 1024):.1f} GB"

    @property
    def file_extension(self):
        if self.file:
            return os.path.splitext(self.file.name)[1].lower()
        return ''

    @property
    def can_preview(self):
        preview_types = ['pdf', 'image', 'word', 'excel']
        return self.file_type in preview_types

    @property
    def preview_type(self):
        if self.file_type in ['pdf', 'image']:
            return 'native'
        elif self.file_type in ['word', 'excel']:
            return 'google_docs'
        return 'none'

    def increment_view_count(self):
        self.view_count += 1
        self.last_viewed_at = timezone.now()
        self.save(update_fields=['view_count', 'last_viewed_at'])

    def increment_download_count(self):
        self.download_count += 1
        self.last_downloaded_at = timezone.now()
        self.save(update_fields=['download_count', 'last_downloaded_at'])

    def verify(self, user):
        self.verified_by = user
        self.verified_at = timezone.now()
        self.save(update_fields=['verified_by', 'verified_at'])

    def approve(self, user):
        self.approved_by = user
        self.approved_at = timezone.now()
        self.save(update_fields=['approved_by', 'approved_at'])

    def archive(self):
        self.is_archived = True
        self.save(update_fields=['is_archived'])

    def unarchive(self):
        self.is_archived = False
        self.save(update_fields=['is_archived'])


class DocumentPage(models.Model):
    """
    Per-page content for a document. Stores the page number, extracted text,
    and optional per-page tables so very large documents can be browsed and
    processed page by page without loading everything into memory at once.
    """
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name='pages',
    )
    page_number = models.PositiveIntegerField(db_index=True)
    text = models.TextField(blank=True)
    tables_json = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['page_number']
        unique_together = ('document', 'page_number')
        verbose_name = 'Document page'
        verbose_name_plural = 'Document pages'

    def __str__(self):
        return f"Page {self.page_number} of document {self.document_id}"
