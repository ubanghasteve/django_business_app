# -*- coding: utf-8 -*-
"""
HR & Staff forms: Department, Employee, LeaveRequest.
Employee form supports creating a profile by linking to an existing User (no duplicate account).
"""
from django import forms
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

from .models import Department, Employee, LeaveRequest

User = get_user_model()


def get_account_users_without_employee(account):
    """Users in this account who do not yet have a linked Employee profile (for HR "link existing user"). Single query via subquery."""
    if not account:
        return User.objects.none()
    linked_ids = Employee.objects.filter(account=account).exclude(
        linked_user__isnull=True
    ).values_list('linked_user_id', flat=True)
    return User.objects.filter(account=account).exclude(pk__in=linked_ids).order_by('email')


class DepartmentForm(forms.ModelForm):
    """Form for creating and editing Department."""

    class Meta:
        model = Department
        fields = ['name', 'manager_name', 'budget']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Engineering',
                'autocomplete': 'organization',
            }),
            'manager_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Manager full name',
                'autocomplete': 'name',
            }),
            'budget': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '0.00',
                'min': '0',
                'step': '0.01',
            }),
        }


class EmployeeForm(forms.ModelForm):
    """
    Form for creating and editing Employee. Uses full_name for display; splits to first_name/last_name on save.
    When creating, can optionally link to an existing User (HR profile only; no duplicate account).
    """

    full_name = forms.CharField(
        required=False,
        label='Full Name',
        widget=forms.TextInput(attrs={
            'class': 'form-control hr-form-control',
            'placeholder': 'e.g. John Doe',
            'autocomplete': 'name',
        }),
    )
    link_to_existing_user = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        label='Link to existing user',
        help_text='Optional: select a user in this account to create an employee profile for them. Their login stays the same.',
        widget=forms.Select(attrs={'class': 'form-select hr-form-control'}),
    )
    temporary_password = forms.CharField(
        required=False,
        label='Temporary password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control hr-form-control',
            'placeholder': 'Leave blank to auto-generate',
            'autocomplete': 'new-password',
        }),
        help_text='Optional. Only used when "Enable portal access" is checked. Leave blank to auto-generate a secure password.',
    )

    class Meta:
        model = Employee
        # HR can edit profile/HR data only. linked_user and is_portal_user are NEVER in fields:
        # only Company Admin / system can manage auth; HR must not break app access.
        fields = [
            'profile_photo',
            'email', 'phone', 'date_of_birth',
            'street_address', 'city', 'state_province', 'zip_code',
            'position', 'department', 'monthly_salary', 'status', 'reporting_manager',
            'emergency_contact_name', 'emergency_contact_phone', 'bio',
            'date_joined',
        ]
        widgets = {
            'profile_photo': forms.FileInput(attrs={
                'class': 'd-none',
                'accept': 'image/png,image/jpeg,image/jpg',
                'id': 'id_profile_photo',
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control hr-form-control',
                'placeholder': 'john.doe@company.com',
                'autocomplete': 'email',
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control hr-form-control',
                'placeholder': '+1 (555) 123-4567',
                'autocomplete': 'tel',
            }),
            'date_of_birth': forms.DateInput(attrs={
                'class': 'form-control hr-form-control',
                'type': 'date',
                'placeholder': 'mm/dd/yyyy',
            }),
            'street_address': forms.TextInput(attrs={
                'class': 'form-control hr-form-control',
                'placeholder': '123 Main Street',
                'autocomplete': 'street-address',
            }),
            'city': forms.TextInput(attrs={
                'class': 'form-control hr-form-control',
                'placeholder': 'New York',
                'autocomplete': 'address-level2',
            }),
            'state_province': forms.TextInput(attrs={
                'class': 'form-control hr-form-control',
                'placeholder': 'NY',
                'autocomplete': 'address-level1',
            }),
            'zip_code': forms.TextInput(attrs={
                'class': 'form-control hr-form-control',
                'placeholder': '10001',
                'autocomplete': 'postal-code',
            }),
            'position': forms.TextInput(attrs={
                'class': 'form-control hr-form-control',
                'placeholder': 'e.g. Software Engineer',
            }),
            'department': forms.Select(attrs={
                'class': 'form-select hr-form-control',
                'placeholder': 'e.g. Engineering',
            }),
            'monthly_salary': forms.NumberInput(attrs={
                'class': 'form-control hr-form-control hr-salary-input',
                'placeholder': '10000',
                'min': '0',
                'step': '0.01',
            }),
            'status': forms.Select(attrs={'class': 'form-select hr-form-control'}),
            'reporting_manager': forms.TextInput(attrs={
                'class': 'form-control hr-form-control',
                'placeholder': 'e.g. Sarah Johnson',
            }),
            'emergency_contact_name': forms.TextInput(attrs={
                'class': 'form-control hr-form-control',
                'placeholder': 'e.g. Jane Doe',
            }),
            'emergency_contact_phone': forms.TextInput(attrs={
                'class': 'form-control hr-form-control',
                'placeholder': '+1 (555) 987-6543',
            }),
            'bio': forms.Textarea(attrs={
                'class': 'form-control hr-form-control',
                'placeholder': 'Short bio or notes',
                'rows': 3,
            }),
            'date_joined': forms.DateInput(attrs={
                'class': 'form-control hr-form-control',
                'type': 'date',
            }),
        }
        labels = {
            'profile_photo': 'Profile Photo',
            'email': 'Email Address',
            'phone': 'Phone Number',
            'date_of_birth': 'Date of Birth',
            'street_address': 'Street Address',
            'city': 'City',
            'state_province': 'State / Province',
            'zip_code': 'Zip / Postal Code',
            'position': 'Position / Job Title',
            'department': 'Department',
            'monthly_salary': 'Monthly Salary',
            'status': 'Employment Status',
            'reporting_manager': 'Reporting Manager (Optional)',
            'emergency_contact_name': 'Contact Name',
            'emergency_contact_phone': 'Contact Phone',
            'bio': 'Bio / Notes',
        }

    def __init__(self, *args, **kwargs):
        account = kwargs.pop('account', None)
        users_without_employee_queryset = kwargs.pop('users_without_employee_queryset', None)
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.initial['full_name'] = self.instance.full_name
        self.fields['department'].empty_label = 'e.g. Engineering'
        if users_without_employee_queryset is not None:
            self.fields['link_to_existing_user'].queryset = users_without_employee_queryset
        elif account is not None:
            self.fields['link_to_existing_user'].queryset = get_account_users_without_employee(account)
        # Temporary password only for create; hide on edit
        if self.instance and self.instance.pk:
            self.fields.pop('temporary_password', None)
        # Make all fields optional so the form never blocks submit.
        for name, field in self.fields.items():
            field.required = False

    def clean(self):
        cleaned = super().clean()
        # When linking to an existing user, prefill missing name/email but do not enforce them.
        if not self.instance.pk and cleaned.get('link_to_existing_user'):
            u = cleaned.get('link_to_existing_user')
            if u:
                if not (cleaned.get('full_name') or '').strip():
                    cleaned['full_name'] = f'{u.first_name or ""} {u.last_name or ""}'.strip() or (u.email or '')
                if not (cleaned.get('email') or '').strip():
                    cleaned['email'] = u.email or ''
        # Validate temporary password length if provided (only used when creating portal)
        pwd = (cleaned.get('temporary_password') or '').strip()
        if pwd and len(pwd) < 8:
            self.add_error('temporary_password', 'Password must be at least 8 characters.')
        return cleaned

    def save(self, commit=True):
        full = self.cleaned_data.pop('full_name', '').strip()
        parts = full.split(None, 1) if full else []
        self.instance.first_name = parts[0] if parts else ''
        self.instance.last_name = parts[1] if len(parts) > 1 else ''
        return super().save(commit=commit)


class LeaveRequestForm(forms.ModelForm):
    """Form for creating and editing LeaveRequest."""

    class Meta:
        model = LeaveRequest
        fields = [
            'employee', 'leave_type', 'reason', 'start_date', 'end_date',
            'supporting_document', 'supervisor_manager', 'work_handover_to', 'handover_notes',
            'contact_number', 'address_during_leave', 'emergency_contact_name', 'emergency_contact_phone',
            'status',
        ]
        widgets = {
            'employee': forms.Select(attrs={
                'class': 'form-select hr-leave-input',
                'id': 'id_employee',
            }),
            'leave_type': forms.Select(attrs={
                'class': 'form-select hr-leave-input',
                'placeholder': 'Select leave type',
            }),
            'reason': forms.Textarea(attrs={
                'class': 'form-control hr-leave-input',
                'rows': 4,
                'placeholder': 'Please provide a detailed reason for your leave request...',
            }),
            'start_date': forms.DateInput(attrs={
                'class': 'form-control hr-leave-input',
                'type': 'date',
                'placeholder': 'mm/dd/yyyy',
            }),
            'end_date': forms.DateInput(attrs={
                'class': 'form-control hr-leave-input',
                'type': 'date',
                'placeholder': 'mm/dd/yyyy',
            }),
            'supporting_document': forms.FileInput(attrs={
                'class': 'd-none',
                'accept': '.pdf,.doc,.docx,image/*',
                'id': 'id_supporting_document',
            }),
            'supervisor_manager': forms.TextInput(attrs={
                'class': 'form-control hr-leave-input',
                'placeholder': 'e.g. Sarah Johnson',
            }),
            'work_handover_to': forms.TextInput(attrs={
                'class': 'form-control hr-leave-input',
                'placeholder': 'e.g. Michael Chen',
            }),
            'handover_notes': forms.Textarea(attrs={
                'class': 'form-control hr-leave-input',
                'rows': 3,
                'placeholder': 'Brief notes about pending tasks or responsibilities during absence...',
            }),
            'contact_number': forms.TextInput(attrs={
                'class': 'form-control hr-leave-input',
                'placeholder': '+1 (555) 123-4567',
            }),
            'address_during_leave': forms.TextInput(attrs={
                'class': 'form-control hr-leave-input',
                'placeholder': 'e.g. 123 Beach Road, Miami',
            }),
            'emergency_contact_name': forms.TextInput(attrs={
                'class': 'form-control hr-leave-input',
                'placeholder': 'e.g. Jane Doe',
            }),
            'emergency_contact_phone': forms.TextInput(attrs={
                'class': 'form-control hr-leave-input',
                'placeholder': '+1 (555) 987-6543',
            }),
            'status': forms.Select(attrs={'class': 'form-select hr-leave-input'}),
        }
        labels = {
            'employee': 'Employee Name',
            'leave_type': 'Type of Leave',
            'reason': 'Reason for Leave',
            'supervisor_manager': 'Supervisor / Manager',
            'work_handover_to': 'Work Handover To',
            'handover_notes': 'Handover Notes',
            'contact_number': 'Contact Number',
            'address_during_leave': 'Address During Leave',
            'emergency_contact_name': 'Emergency Contact Name',
            'emergency_contact_phone': 'Emergency Contact Phone',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make all fields optional; leave status hidden on create for UX, but never required.
        for _name, field in self.fields.items():
            field.required = False
        if not (self.instance and self.instance.pk):
            self.fields['status'].widget = forms.HiddenInput()

    def clean(self):
        cleaned = super().clean()
        start_date = cleaned.get('start_date')
        end_date = cleaned.get('end_date')
        if start_date and end_date and end_date < start_date:
            raise ValidationError('End date must be on or after start date.')
        return cleaned


from .models import JobSeeker, EmployeeDocument


class EmployeeDocumentForm(forms.ModelForm):
    """Form for creating and editing EmployeeDocument."""

    class Meta:
        model = EmployeeDocument
        fields = ['employee', 'document_type', 'title', 'file', 'expiry_date', 'notes']
        widgets = {
            'employee': forms.Select(attrs={
                'class': 'form-select hr-form-control',
                'placeholder': 'Select employee (optional)',
            }),
            'document_type': forms.Select(attrs={
                'class': 'form-select hr-form-control',
            }),
            'title': forms.TextInput(attrs={
                'class': 'form-control hr-form-control',
                'placeholder': 'Enter document title',
            }),
            'file': forms.FileInput(attrs={
                'class': 'form-control hr-form-control',
                'accept': '.pdf,.doc,.docx,.jpg,.jpeg,.png,.gif,.bmp,.tiff',
            }),
            'expiry_date': forms.DateInput(attrs={
                'class': 'form-control hr-form-control',
                'type': 'date',
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control hr-form-control',
                'placeholder': 'Add any notes about this document',
                'rows': 3,
            }),
        }
        labels = {
            'employee': 'Employee',
            'document_type': 'Document Type',
            'title': 'Document Title',
            'file': 'File',
            'expiry_date': 'Expiry Date',
            'notes': 'Notes',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make all fields optional for flexibility
        # Employee can be assigned later
        for field_name, field in self.fields.items():
            field.required = False


class JobSeekerForm(forms.ModelForm):
    """Form for creating and editing JobSeeker with CV upload."""
    
    class Meta:
        model = JobSeeker
        fields = [
            'full_name', 'email', 'phone',
            'address', 'date_of_birth', 'gender',
            'position_applied', 'years_of_experience', 'skills',
            'education', 'work_experience', 'status', 'notes',
            'cv_file'
        ]
        widgets = {
            'full_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Full Name (as on CV)',
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'email@example.com',
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '+1 (555) 123-4567',
            }),
            'address': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Full Address',
                'rows': 2,
            }),
            'date_of_birth': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
            }),
            'gender': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Male/Female/Other',
            }),
            'position_applied': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Position applying for',
            }),
            'years_of_experience': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. 5 years',
            }),
            'skills': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Skills (comma-separated)',
                'rows': 3,
            }),
            'education': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Education background',
                'rows': 3,
            }),
            'work_experience': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Work experience',
                'rows': 4,
            }),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Additional notes',
                'rows': 3,
            }),
            'cv_file': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.doc,.docx,.jpg,.jpeg,.png',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if field_name != 'cv_file':
                field.required = False

    def find_duplicates(self, account):
        """Find potential duplicate job seekers based on name, email, phone, or address."""
        from .models import JobSeeker
        from django.db.models import Q
        
        if not self.cleaned_data:
            return []
        
        full_name = self.cleaned_data.get('full_name', '').strip()
        email = self.cleaned_data.get('email', '').strip().lower()
        phone = self.cleaned_data.get('phone', '').strip()
        address = self.cleaned_data.get('address', '').strip()
        
        duplicates = []
        seen_ids = set()
        
        # Check by email (case-insensitive)
        if email:
            matches = JobSeeker.objects.filter(
                account=account,
                email__iexact=email
            ).exclude(pk=self.instance.pk if self.instance.pk else None)
            for job_seeker in matches:
                if job_seeker.id not in seen_ids:
                    seen_ids.add(job_seeker.id)
                    duplicates.append({
                        'id': job_seeker.id,
                        'type': 'email',
                        'match': email,
                        'seeker': job_seeker
                    })
        
        # Check by phone (partial match)
        if phone:
            phone_variations = [phone, phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')]
            for p in phone_variations:
                if p:
                    matches = JobSeeker.objects.filter(
                        account=account,
                        phone__icontains=p
                    ).exclude(pk=self.instance.pk if self.instance.pk else None)
                    for job_seeker in matches:
                        if job_seeker.id not in seen_ids:
                            seen_ids.add(job_seeker.id)
                            duplicates.append({
                                'id': job_seeker.id,
                                'type': 'phone',
                                'match': phone,
                                'seeker': job_seeker
                            })
        
        # Check by full_name
        if full_name:
            name_query = Q(full_name__iexact=full_name)
            
            if name_query:
                matches = JobSeeker.objects.filter(
                    account=account
                ).exclude(pk=self.instance.pk if self.instance.pk else None).filter(name_query)
                for job_seeker in matches:
                    if job_seeker.id not in seen_ids:
                        seen_ids.add(job_seeker.id)
                        duplicates.append({
                            'id': job_seeker.id,
                            'type': 'name',
                            'match': full_name,
                            'seeker': job_seeker
                        })
        
        # Check by address (if provided and substantial)
        if address and len(address) > 10:
            matches = JobSeeker.objects.filter(
                account=account,
                address__icontains=address[:30]
            ).exclude(pk=self.instance.pk if self.instance.pk else None)
            for job_seeker in matches:
                if job_seeker.id not in seen_ids:
                    seen_ids.add(job_seeker.id)
                    duplicates.append({
                        'id': job_seeker.id,
                        'type': 'address',
                        'match': address[:30],
                        'seeker': job_seeker
                    })
        
        return duplicates
