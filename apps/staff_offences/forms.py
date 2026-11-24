from django import forms
from django.contrib.auth import get_user_model
from calendar import month_name
from datetime import date

from .models import StaffOffenceRegister, StaffOffenceEntry

User = get_user_model()


class StaffOffenceRegisterForm(forms.ModelForm):
    month = forms.TypedChoiceField(
        coerce=int,
        choices=[(i, month_name[i]) for i in range(1, 13)],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    year = forms.IntegerField(
        min_value=2000,
        max_value=2100,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': 2000, 'max': 2100}),
    )

    class Meta:
        model = StaffOffenceRegister
        fields = ['staff_name', 'department_name', 'month', 'year']
        widgets = {
            'staff_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Type staff member full name',
                'autocomplete': 'off',
            }),
            'department_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Production',
                'autocomplete': 'off',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            today = date.today()
            self.fields['month'].initial = today.month
            self.fields['year'].initial = today.year
        self.fields['staff_name'].required = True
        self.fields['department_name'].required = False
        self.fields['month'].required = True
        self.fields['year'].required = True

    def clean_staff_name(self):
        name = (self.cleaned_data.get('staff_name') or '').strip()
        if not name:
            raise forms.ValidationError('Staff member name is required.')
        return name


class StaffOffenceEntryForm(forms.ModelForm):
    class Meta:
        model = StaffOffenceEntry
        fields = ['date', 'description', 'amount']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'description': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Late arrival',
                'maxlength': 500,
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': '0.00',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['date'].required = True
        self.fields['description'].required = True
        self.fields['amount'].required = True
        if not self.instance.pk:
            self.fields['date'].initial = date.today()


class StaffOffenceRegisterFilterForm(forms.Form):
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control so-filter-input',
            'placeholder': 'Type a name, letter, record no…',
            'autocomplete': 'off',
            'spellcheck': 'false',
            'inputmode': 'search',
            'aria-label': 'Live search staff offence registers',
        }),
    )
    department = forms.ChoiceField(
        required=False,
        choices=[('', 'All departments')],
        widget=forms.Select(attrs={'class': 'form-select so-filter-input'}),
    )
    month = forms.ChoiceField(
        required=False,
        choices=[('', 'All months')] + [(str(i), month_name[i]) for i in range(1, 13)],
        widget=forms.Select(attrs={'class': 'form-select so-filter-input'}),
    )
    year = forms.ChoiceField(
        required=False,
        choices=[('', 'All years')],
        widget=forms.Select(attrs={'class': 'form-select so-filter-input'}),
    )
    payment_status = forms.ChoiceField(
        required=False,
        choices=[('', 'All payment statuses')],
        widget=forms.Select(attrs={'class': 'form-select so-filter-input'}),
    )
    created_by = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        empty_label='All team members',
        label='Created by',
        widget=forms.Select(attrs={'class': 'form-select so-filter-input'}),
    )

    def __init__(self, *args, department_choices=None, year_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        depts = department_choices or []
        years = year_choices or []
        self.fields['department'].choices = [('', 'All departments')] + [
            (d, d) for d in depts if d
        ]
        self.fields['year'].choices = [('', 'All years')] + [
            (str(y), str(y)) for y in years
        ]
        self.fields['payment_status'].choices = [('', 'All payment statuses')] + list(
            StaffOffenceRegister.PAYMENT_STATUS_CHOICES
        )
