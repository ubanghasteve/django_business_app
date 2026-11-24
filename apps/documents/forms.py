# -*- coding: utf-8 -*-
from datetime import date
from django import forms
from django.core.validators import FileExtensionValidator, MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from .models import Document

ALLOWED_EXTENSIONS = (
    'pdf',
    'png', 'jpg', 'jpeg', 'tiff', 'tif', 'bmp', 'gif', 'webp',
    'doc', 'docx',
    'xls', 'xlsx', 'xlsm',
)
ACCEPT_ATTR = (
    '.pdf,.png,.jpg,.jpeg,.tiff,.tif,.bmp,.gif,.webp,'
    '.doc,.docx,.xls,.xlsx,.xlsm'
)
MAX_UPLOAD_MB = 25
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024


class DocumentUploadForm(forms.ModelForm):
    """Form for uploading a document with enhanced metadata fields."""

    title = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter document title (optional)',
        }),
        help_text='Leave blank to auto-generate from filename'
    )
    
    document_type = forms.ChoiceField(
        choices=[('', 'Select type (optional)')] + list(Document.DOCUMENT_TYPE_CHOICES),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Enter description (optional)',
        }),
    )
    
    tags = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter tags separated by commas (optional)',
        }),
        help_text='Example: invoice, 2024, january'
    )
    
    period_month = forms.ChoiceField(
        choices=[('', 'Select month (optional)')] + [
            (i, m) for i, m in enumerate([
                'January', 'February', 'March', 'April', 'May', 'June',
                'July', 'August', 'September', 'October', 'November', 'December'
            ], 1)
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    
    period_year = forms.ChoiceField(
        choices=[('', 'Select year (optional)')] + [
            (y, str(y)) for y in range(date.today().year - 5, date.today().year + 1)
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = Document
        fields = ('file',)
        widgets = {
            'file': forms.FileInput(attrs={
                'accept': ACCEPT_ATTR,
                'aria-label': 'Choose PDF, Word, Excel or image file',
                'class': 'form-control',
            }),
        }

    def clean_file(self):
        data = self.cleaned_data.get('file')
        if not data:
            raise forms.ValidationError('Please select a file.')
        name = getattr(data, 'name', '') or ''
        ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
        if ext not in ALLOWED_EXTENSIONS:
            raise forms.ValidationError(
                'Unsupported format. Allowed: PDF, Word (DOC, DOCX), Excel (XLS, XLSX, XLSM) and images (PNG, JPG, JPEG, TIFF, BMP, GIF, WebP).'
            )
        if data.size > MAX_UPLOAD_BYTES:
            raise forms.ValidationError(f'File size must not exceed {MAX_UPLOAD_MB} MB.')
        return data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if not instance.document_type:
            instance.document_type = Document.DOCUMENT_TYPE_OTHER
        if not instance.title:
            import os
            instance.title = os.path.splitext(instance.original_filename or getattr(instance.file, 'name', 'Document'))[0]
            instance.title = instance.title.replace('_', ' ').replace('-', ' ').title()
        if commit:
            instance.save()
        return instance


class DocumentFilterForm(forms.Form):
    """Form for filtering documents in list view."""
    
    q = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search documents...',
        })
    )
    
    document_type = forms.ChoiceField(
        choices=[('', 'All types')] + list(Document.DOCUMENT_TYPE_CHOICES),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    
    processing_status = forms.ChoiceField(
        choices=[('', 'All statuses')] + list(Document.STATUS_CHOICES),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    
    show_archived = forms.BooleanField(
        required=False,
        label='Show archived'
    )
    
    starred_only = forms.BooleanField(
        required=False,
        label='Starred only'
    )
    
    sort_by = forms.ChoiceField(
        choices=[
            ('-created_at', 'Newest first'),
            ('created_at', 'Oldest first'),
            ('-updated_at', 'Recently updated'),
            ('title', 'Title (A-Z)'),
            ('-title', 'Title (Z-A)'),
        ],
        required=False,
        initial='-created_at',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
