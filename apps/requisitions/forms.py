from django import forms
from django.contrib.auth import get_user_model
from .models import Requisition

User = get_user_model()


class RequisitionSignatureClearableFileInput(forms.ClearableFileInput):
    """ClearableFileInput: renders only the file input; template adds the 'Remove signature' Bootstrap switch."""
    clear_checkbox_label = 'Remove signature'
    # Use FileInput's template so we don't render the default "Currently" + checkbox (template adds Bootstrap switch)
    template_name = 'django/forms/widgets/file.html'

    def render(self, name, value, attrs=None, renderer=None):
        """Render only the file input; clear checkbox is added in template as form-switch."""
        return super(forms.FileInput, self).render(name, value, attrs, renderer)


class RequisitionForm(forms.ModelForm):
    class Meta:
        model = Requisition
        fields = [
            'organization_name', 'address', 'contact_number', 'date',
            'job_type', 'print_product', 'quantity', 'colors', 'size', 'micron',
            'other_info', 'signature', 'status',
        ]
        widgets = {
            'organization_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Organization name',
            }),
            'address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Address',
            }),
            'contact_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Contact number',
            }),
            'date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control',
            }),
            'job_type': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Job type',
            }),
            'print_product': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Print product',
            }),
            'quantity': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Quantity',
            }),
            'colors': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Colors',
            }),
            'size': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Size',
            }),
            'micron': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Micron',
            }),
            'other_info': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Other information',
            }),
            'signature': RequisitionSignatureClearableFileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*',
            }),
            'status': forms.Select(attrs={
                'class': 'form-select',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['status'].required = True
        self.fields['organization_name'].required = True


class RequisitionFilterForm(forms.Form):
    STATUS_CHOICES = [('', 'All Status')] + list(Requisition.STATUS_CHOICES)

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search by reference or organization...',
        }),
    )
    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control',
        }),
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control',
        }),
    )
    created_by = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        empty_label='All team members',
        label='Created by',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
