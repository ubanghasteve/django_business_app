from django import forms
from django.core.exceptions import ValidationError
from .models import CompanyProfile, BankAccount


class CompanyProfileForm(forms.ModelForm):
    class Meta:
        model = CompanyProfile
        fields = [
            'company_name', 'email', 'phone', 'website',
            'address_line_1', 'address_line_2', 'city', 'state', 'postal_code', 'country',
            'business_type', 'tax_id', 'registration_number',
            'logo', 'signature', 'default_tax', 'currency_code', 'currency_symbol',
            'primary_color', 'secondary_color', 'accent_color', 'text_color',
            'show_bank_details', 'show_signature'
        ]
        widgets = {
            'company_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter company name'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'company@example.com'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '+1234567890'
            }),
            'website': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://example.com'
            }),
            'address_line_1': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Street address'
            }),
            'address_line_2': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Apartment, suite, etc.'
            }),
            'city': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'City'
            }),
            'state': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'State/Province'
            }),
            'postal_code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Postal code'
            }),
            'country': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Country'
            }),
            'business_type': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Corporation, LLC, Partnership'
            }),
            'tax_id': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Tax ID number'
            }),
            'registration_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Business registration number'
            }),
            'logo': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'signature': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'default_tax': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'max': '100'
            }),
            'currency_code': forms.TextInput(attrs={
                'class': 'form-control',
                'maxlength': '3',
                'placeholder': 'USD'
            }),
            'currency_symbol': forms.TextInput(attrs={
                'class': 'form-control',
                'maxlength': '5',
                'placeholder': '$'
            }),
            'primary_color': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color',
                'title': 'Main brand color for headers, buttons, and accents'
            }),
            'secondary_color': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color',
                'title': 'Background color for sections and cards'
            }),
            'accent_color': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color',
                'title': 'Border and divider color'
            }),
            'text_color': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color',
                'title': 'Main text color for documents'
            }),
            'show_bank_details': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'show_signature': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make fields with defaults not required
        self.fields['default_tax'].required = False
        self.fields['primary_color'].required = False
        self.fields['secondary_color'].required = False
        self.fields['accent_color'].required = False
        self.fields['text_color'].required = False
        self.fields['currency_code'].required = False
        self.fields['currency_symbol'].required = False
        self.fields['company_name'].required = False
        self.fields['email'].required = False
        self.fields['phone'].required = False
        self.fields['website'].required = False

    def clean_logo(self):
        logo = self.cleaned_data.get('logo')
        if logo:
            # Validate file size (max 5MB)
            if logo.size > 5 * 1024 * 1024:
                raise ValidationError("Logo file size cannot exceed 5MB.")
            
            # Validate file type
            valid_extensions = ['.jpg', '.jpeg', '.png', '.gif']
            if not any(logo.name.lower().endswith(ext) for ext in valid_extensions):
                raise ValidationError("Logo must be a JPG, PNG, or GIF file.")
        
        return logo

    def clean_signature(self):
        signature = self.cleaned_data.get('signature')
        if signature:
            # Validate file size (max 5MB)
            if signature.size > 5 * 1024 * 1024:
                raise ValidationError("Signature file size cannot exceed 5MB.")
            
            # Validate file type
            valid_extensions = ['.jpg', '.jpeg', '.png', '.gif']
            if not any(signature.name.lower().endswith(ext) for ext in valid_extensions):
                raise ValidationError("Signature must be a JPG, PNG, or GIF file.")
        
        return signature



class BankAccountForm(forms.ModelForm):
    class Meta:
        model = BankAccount
        fields = ['bank_name', 'account_name', 'account_number', 'is_default']
        widgets = {
            'bank_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter bank name'
            }),
            'account_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter account holder name'
            }),
            'account_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter account number'
            }),
            'is_default': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }

    def clean_account_number(self):
        account_number = self.cleaned_data.get('account_number')
        if account_number:
            # Remove spaces and hyphens for validation
            clean_number = account_number.replace(' ', '').replace('-', '')
            if not clean_number.isdigit():
                raise ValidationError("Account number can only contain digits, spaces, and hyphens.")
            
            if len(clean_number) < 8:
                raise ValidationError("Account number must be at least 8 digits long.")
        
        return account_number

    def clean_bank_name(self):
        bank_name = self.cleaned_data.get('bank_name')
        if bank_name and len(bank_name.strip()) < 2:
            raise ValidationError("Bank name must be at least 2 characters long.")
        return bank_name.strip() if bank_name else None

    def clean_account_name(self):
        account_name = self.cleaned_data.get('account_name')
        if account_name and len(account_name.strip()) < 2:
            raise ValidationError("Account name must be at least 2 characters long.")
        return account_name.strip() if account_name else None


class CustomChargeForm(forms.Form):
    """Form for adding custom charges dynamically"""
    charge_name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Charge name (e.g., Handling Fee)'
        })
    )
    charge_amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.01',
            'placeholder': '0.00'
        })
    )

    def clean_charge_name(self):
        charge_name = self.cleaned_data.get('charge_name')
        if charge_name:
            # Convert to lowercase with underscores for consistency
            return charge_name.lower().replace(' ', '_')
        return charge_name


class CurrencyForm(forms.Form):
    """Form for currency selection"""
    CURRENCY_CHOICES = [
        ('USD', 'US Dollar ($)'),
        ('EUR', 'Euro (€)'),
        ('GBP', 'British Pound (£)'),
        ('JPY', 'Japanese Yen (¥)'),
        ('CAD', 'Canadian Dollar (C$)'),
        ('AUD', 'Australian Dollar (A$)'),
        ('CHF', 'Swiss Franc (CHF)'),
        ('CNY', 'Chinese Yuan (¥)'),
        ('INR', 'Indian Rupee (₹)'),
        ('NGN', 'Nigerian Naira (₦)'),
    ]
    
    currency_code = forms.ChoiceField(
        choices=CURRENCY_CHOICES,
        widget=forms.Select(attrs={
            'class': 'form-control'
        })
    )
