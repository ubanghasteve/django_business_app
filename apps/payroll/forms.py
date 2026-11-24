"""
Smart Payroll Records Forms
=========================
Forms for payroll record management with smart validation.
"""

from datetime import date
from django import forms
from django.core.validators import FileExtensionValidator, MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError

from .models import (
    PayrollRecord,
    PayrollCategory,
    PayrollTemplate,
    PayrollEntry,
)


class PayrollRecordForm(forms.ModelForm):
    """
    Form for creating and editing payroll records.
    """
    
    class Meta:
        model = PayrollRecord
        fields = [
            'title',
            'record_type',
            'file',
            'category',
            'period_month',
            'period_year',
            'period_start_date',
            'period_end_date',
            'employee',
            'department',
            'description',
            'tags',
            'is_public',
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter payroll record title',
            }),
            'record_type': forms.Select(attrs={'class': 'form-select'}),
            'file': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.doc,.docx,.xls,.xlsx,.csv,.jpg,.jpeg,.png,.gif,.bmp,.tiff,.txt',
            }),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'period_month': forms.Select(attrs={'class': 'form-select'}),
            'period_year': forms.TextInput(attrs={
                'class': 'form-control',
                'list': 'year-list',
                'placeholder': 'Type or select year',
                'autocomplete': 'off',
            }),
            'period_start_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
            }),
            'period_end_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
            }),
            'employee': forms.Select(attrs={'class': 'form-select'}),
            'department': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Enter description (optional)',
            }),
            'tags': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter tags separated by commas',
            }),
            'is_public': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Make all fields not required
        for field_name in self.fields:
            self.fields[field_name].required = False
        
        current_year = date.today().year
        
        month_choices = [('', 'Select month')] + [
            (i, m) for i, m in enumerate([
                'January', 'February', 'March', 'April', 'May', 'June',
                'July', 'August', 'September', 'October', 'November', 'December'
            ], 1)
        ]
        self.fields['period_month'].widget.choices = month_choices
        
        year_choices = [('', 'Select year')] + [
            (y, str(y)) for y in range(1980, current_year + 10)
        ]
        self.fields['period_year'].widget.choices = year_choices
        
        self.fields['category'].queryset = PayrollCategory.objects.filter(is_active=True)
        
        try:
            from apps.hr_staff.models import Employee
            self.fields['employee'].queryset = Employee.objects.filter(is_deleted=False)
        except ImportError:
            self.fields['employee'].queryset = Employee.objects.none()
        
        try:
            from apps.hr_staff.models import Department
            self.fields['department'].queryset = Department.objects.filter(is_deleted=False)
        except ImportError:
            self.fields['department'].queryset = Department.objects.none()
    
    def clean_file(self):
        """Validate uploaded file."""
        file = self.cleaned_data.get('file')
        
        if not file:
            return file
        
        allowed_extensions = [
            'pdf', 'doc', 'docx', 'xls', 'xlsx', 'csv',
            'jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'tif',
            'txt', 'rtf', 'odt', 'ods', 'ppt', 'pptx'
        ]
        
        max_size = 100 * 1024 * 1024
        
        ext = file.name.split('.')[-1].lower() if '.' in file.name else ''
        
        if ext not in allowed_extensions:
            raise ValidationError(
                f"File type '.{ext}' is not supported. "
                f"Supported types: {', '.join(allowed_extensions)}"
            )
        
        if file.size > max_size:
            max_size_mb = max_size / (1024 * 1024)
            raise ValidationError(
                f"File size exceeds maximum allowed ({max_size_mb:.0f}MB)"
            )
        
        return file
    
    def clean(self):
        """Additional validation."""
        cleaned_data = super().clean()
        
        period_start = cleaned_data.get('period_start_date')
        period_end = cleaned_data.get('period_end_date')
        
        if period_start and period_end and period_end < period_start:
            raise ValidationError({
                'period_end_date': 'End date must be after start date'
            })
        
        return cleaned_data


class PayrollRecordBulkForm(forms.Form):
    """
    Form for bulk uploading payroll records.
    Note: Multiple files should be handled in the view using request.FILES.getlist('files')
    """
    
    record_type = forms.ChoiceField(
        choices=[('', 'Select type')] + list(PayrollRecord.RECORD_TYPE_CHOICES),
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=False,
    )
    
    category = forms.ModelChoiceField(
        queryset=PayrollCategory.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=False,
    )
    
    period_month = forms.ChoiceField(
        choices=[('', 'Select month')] + [
            (i, m) for i, m in enumerate([
                'January', 'February', 'March', 'April', 'May', 'June',
                'July', 'August', 'September', 'October', 'November', 'December'
            ], 1)
        ],
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=False,
    )
    
    period_year = forms.ChoiceField(
        choices=[('', 'Select year')] + [
            (y, str(y)) for y in range(date.today().year - 5, date.today().year + 1)
        ],
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=False,
    )
    
    auto_detect_period = forms.BooleanField(
        required=False,
        initial=True,
        help_text='Automatically detect period from file content'
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        try:
            self.fields['category'].queryset = PayrollCategory.objects.filter(is_active=True)
        except Exception:
            pass
    
    def clean_files(self):
        """Validate multiple uploaded files."""
        files = self.cleaned_data.get('files')
        
        if not files:
            return files
        
        if not isinstance(files, list):
            files = [files]
        
        allowed_extensions = [
            'pdf', 'doc', 'docx', 'xls', 'xlsx', 'csv',
            'jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'tif',
            'txt', 'rtf', 'odt', 'ods', 'ppt', 'pptx'
        ]
        
        max_size = 100 * 1024 * 1024
        max_files = 50
        
        if len(files) > max_files:
            raise ValidationError(f'Maximum {max_files} files can be uploaded at once')
        
        for f in files:
            if not f:
                continue
                
            ext = f.name.split('.')[-1].lower() if '.' in f.name else ''
            
            if ext not in allowed_extensions:
                raise ValidationError(
                    f"File type '.{ext}' is not supported for file: {f.name}"
                )
            
            if f.size > max_size:
                max_size_mb = max_size / (1024 * 1024)
                raise ValidationError(
                    f"File {f.name} exceeds maximum allowed size ({max_size_mb:.0f}MB)"
                )
        
        return files


class PayrollCategoryForm(forms.ModelForm):
    """
    Form for creating and editing payroll categories.
    """
    
    class Meta:
        model = PayrollCategory
        fields = [
            'name',
            'category_type',
            'description',
            'color',
            'icon',
            'is_active',
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter category name',
            }),
            'category_type': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Enter description (optional)',
            }),
            'color': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color',
            }),
            'icon': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., file-document, money',
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class PayrollRecordFilterForm(forms.Form):
    """
    Form for filtering payroll records.
    """
    
    q = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search records...',
        })
    )
    
    record_type = forms.ChoiceField(
        choices=[('', 'All types')] + list(PayrollRecord.RECORD_TYPE_CHOICES),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    
    file_type = forms.ChoiceField(
        choices=[('', 'All file types')] + list(PayrollRecord.FILE_TYPE_CHOICES),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    
    status = forms.ChoiceField(
        choices=[('', 'All statuses')] + list(PayrollRecord.STATUS_CHOICES),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    
    category = forms.ModelChoiceField(
        queryset=PayrollCategory.objects.none(),
        required=False,
        empty_label='All categories',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    
    year = forms.ChoiceField(
        choices=[('', 'All years')] + [
            (y, str(y)) for y in range(date.today().year - 5, date.today().year + 1)
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    
    month = forms.ChoiceField(
        choices=[('', 'All months')] + [
            (i, m) for i, m in enumerate([
                'January', 'February', 'March', 'April', 'May', 'June',
                'July', 'August', 'September', 'October', 'November', 'December'
            ], 1)
        ],
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
            ('-period_year', 'Year (newest)'),
            ('-period_month', 'Month (newest)'),
            ('title', 'Title (A-Z)'),
            ('-title', 'Title (Z-A)'),
            ('file_size', 'File size (smallest)'),
            ('-file_size', 'File size (largest)'),
        ],
        required=False,
        initial='-created_at',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        try:
            self.fields['category'].queryset = PayrollCategory.objects.filter(is_active=True)
        except Exception:
            pass


class PayrollTemplateForm(forms.ModelForm):
    """
    Form for creating and editing payroll templates.
    """
    
    class Meta:
        model = PayrollTemplate
        fields = [
            'name',
            'description',
            'record_type',
            'columns',
            'default_tags',
            'is_active',
            'is_default',
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter template name',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Enter description (optional)',
            }),
            'record_type': forms.Select(attrs={'class': 'form-select'}),
            'columns': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 10,
                'placeholder': 'Enter columns configuration as JSON',
            }),
            'default_tags': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter default tags separated by commas',
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_default': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class PayrollEntryForm(forms.ModelForm):
    """
    Form for creating and editing payroll entries.
    """
    
    class Meta:
        model = PayrollEntry
        fields = [
            'title',
            'template',
            'period_month',
            'period_year',
            'period_start_date',
            'period_end_date',
            'status',
            'notes',
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter entry title',
            }),
            'template': forms.Select(attrs={'class': 'form-select'}),
            'period_month': forms.Select(attrs={'class': 'form-select'}),
            'period_year': forms.Select(attrs={'class': 'form-select'}),
            'period_start_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
            }),
            'period_end_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
            }),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Enter notes (optional)',
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        current_year = date.today().year
        
        month_choices = [('', 'Select month')] + [
            (i, m) for i, m in enumerate([
                'January', 'February', 'March', 'April', 'May', 'June',
                'July', 'August', 'September', 'October', 'November', 'December'
            ], 1)
        ]
        self.fields['period_month'].widget.choices = month_choices
        
        year_choices = [('', 'Select year')] + [
            (y, str(y)) for y in range(1980, current_year + 10)
        ]
        self.fields['period_year'].widget.choices = year_choices
        
        self.fields['template'].queryset = PayrollTemplate.objects.filter(is_active=True)


class PayrollRecordShareForm(forms.Form):
    """
    Form for sharing payroll records.
    """
    
    share_type = forms.ChoiceField(
        choices=[
            ('link', 'Share via link'),
            ('email', 'Share via email'),
        ],
        widget=forms.Select(attrs={'class': 'form-select'}),
        initial='link',
    )
    
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter recipient email',
        }),
    )
    
    permission_view = forms.BooleanField(
        required=False,
        initial=True,
        label='Allow viewing',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )
    
    permission_download = forms.BooleanField(
        required=False,
        initial=True,
        label='Allow downloading',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )
    
    permission_print = forms.BooleanField(
        required=False,
        initial=False,
        label='Allow printing',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )
    
    expires_in_days = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=365,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Days until expiration',
        }),
        help_text='Leave empty for no expiration',
    )
    
    max_access_count = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=1000,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Max access count',
        }),
        help_text='Leave empty for unlimited',
    )
    
    message = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Add a message (optional)',
        }),
    )
    
    def clean(self):
        """Validate share form."""
        cleaned_data = super().clean()
        
        share_type = cleaned_data.get('share_type')
        email = cleaned_data.get('email')
        
        if share_type == 'email' and not email:
            raise ValidationError({
                'email': 'Email is required when sharing via email'
            })
        
        return cleaned_data
