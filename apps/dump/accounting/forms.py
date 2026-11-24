from django import forms
from django.contrib.auth import get_user_model
from .models import Transaction, Account, FinancialReport
from decimal import Decimal
import re

User = get_user_model()


class TransactionForm(forms.ModelForm):
    """Form for creating and editing transactions"""
    
    DISCOUNT_TYPE_CHOICES = [
        ('percentage', 'Percentage (%)'),
        ('fixed', 'Fixed Amount'),
    ]
    TAX_TYPE_CHOICES = [
        ('percentage', 'Percentage (%)'),
        ('fixed', 'Fixed Amount'),
    ]
    
    tax_type = forms.ChoiceField(
        choices=TAX_TYPE_CHOICES,
        required=False,
        initial='fixed',
        widget=forms.Select(attrs={
            'class': 'form-select type-selector',
            'id': 'tax_type'
        })
    )
    discount_type = forms.ChoiceField(
        choices=DISCOUNT_TYPE_CHOICES,
        required=False,
        initial='fixed',
        widget=forms.Select(attrs={
            'class': 'form-select type-selector',
            'id': 'discount_type'
        })
    )
    
    class Meta:
        model = Transaction
        fields = [
            'type', 'title', 'description', 'amount', 'currency', 
            'tax_type', 'tax', 'discount_type', 'discount', 'transaction_date', 'notes'
        ]
        widgets = {
            'transaction_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 3}),
            'notes': forms.Textarea(attrs={'rows': 3}),
            'amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0', 'class': 'form-control'}),
            'tax': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '0.00 or 5%'}),
            'discount': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '0.00 or 10%'}),
        }
    
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Set default currency from user's company
        if self.user and hasattr(self.user, 'company_profile'):
            self.fields['currency'].initial = self.user.company_profile.currency_code
    
    def clean_amount(self):
        """Clean and validate amount field"""
        amount = self.cleaned_data.get('amount')
        if amount is not None:
            # Handle currency symbols and formatting
            if isinstance(amount, str):
                # Remove currency symbols and commas
                amount = re.sub(r'[₦$€£¥,\s]', '', amount)
                try:
                    amount = Decimal(amount)
                except (ValueError, TypeError):
                    raise forms.ValidationError("Please enter a valid amount.")
            
            if amount <= 0:
                raise forms.ValidationError("Amount must be greater than zero.")
        
        return amount
    
    def clean_tax(self):
        """Clean tax field with type detection"""
        tax = self.cleaned_data.get('tax')
        
        if tax is None or tax == '':
            return Decimal('0')
        
        if isinstance(tax, str):
            # Auto-detect percentage type from input
            if '%' in tax:
                self.cleaned_data['tax_type'] = 'percentage'
                # Extract the percentage number
                cleaned = re.sub(r'[₦$€£¥,%\s]', '', tax)
                try:
                    return Decimal(cleaned) if cleaned else Decimal('0')
                except (ValueError, TypeError):
                    raise forms.ValidationError("Please enter a valid tax value.")
            
            # Fixed amount
            cleaned = re.sub(r'[₦$€£¥,\s]', '', tax)
            try:
                return Decimal(cleaned) if cleaned else Decimal('0')
            except (ValueError, TypeError):
                raise forms.ValidationError("Please enter a valid tax amount.")
        
        return tax or Decimal('0')
    
    def clean_discount(self):
        """Clean discount field with type detection"""
        discount = self.cleaned_data.get('discount')
        
        if discount is None or discount == '':
            return Decimal('0')
        
        if isinstance(discount, str):
            # Auto-detect percentage type from input
            if '%' in discount:
                self.cleaned_data['discount_type'] = 'percentage'
                # Extract the percentage number
                cleaned = re.sub(r'[₦$€£¥,%\s]', '', discount)
                try:
                    return Decimal(cleaned) if cleaned else Decimal('0')
                except (ValueError, TypeError):
                    raise forms.ValidationError("Please enter a valid discount value.")
            
            # Fixed amount
            cleaned = re.sub(r'[₦$€£¥,\s]', '', discount)
            try:
                return Decimal(cleaned) if cleaned else Decimal('0')
            except (ValueError, TypeError):
                raise forms.ValidationError("Please enter a valid discount amount.")
        
        return discount or Decimal('0')


class TransactionFilterForm(forms.Form):
    """Form for filtering transactions"""
    
    # Date range
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    
    # Transaction type
    transaction_type = forms.ChoiceField(
        choices=[('', 'All Types')] + Transaction.TRANSACTION_TYPE,
        required=False
    )
    
    # Source app
    source_app = forms.ChoiceField(
        choices=[('', 'All Sources')] + Transaction.SOURCE_APP_CHOICES,
        required=False
    )
    
    # Amount range
    min_amount = forms.DecimalField(
        required=False,
        widget=forms.NumberInput(attrs={'step': '0.01', 'min': '0', 'placeholder': 'Min Amount'})
    )
    max_amount = forms.DecimalField(
        required=False,
        widget=forms.NumberInput(attrs={'step': '0.01', 'min': '0', 'placeholder': 'Max Amount'})
    )
    
    # Search
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Search transactions...'})
    )
    
    # Status
    is_reconciled = forms.ChoiceField(
        choices=[('', 'All'), ('true', 'Reconciled'), ('false', 'Not Reconciled')],
        required=False
    )
    # Admin-only: filter by creator. Queryset set in view when is_company_admin.
    created_by = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        empty_label='All team members',
        label='Created by',
        widget=forms.Select(attrs={'class': 'form-control', 'placeholder': 'Created by'})
    )


class AccountForm(forms.ModelForm):
    """Form for creating and editing accounts"""
    
    class Meta:
        model = Account
        fields = ['name', 'account_number', 'account_type', 'description', 'opening_balance']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'opening_balance': forms.NumberInput(attrs={'step': '0.01'}),
        }
    
    def clean_account_number(self):
        """Ensure account number is unique"""
        account_number = self.cleaned_data.get('account_number')
        if Account.objects.filter(account_number=account_number).exclude(pk=self.instance.pk if self.instance else None).exists():
            raise forms.ValidationError("This account number is already in use.")
        return account_number


class FinancialReportForm(forms.ModelForm):
    """Form for generating financial reports"""
    
    class Meta:
        model = FinancialReport
        fields = ['report_type', 'title', 'start_date', 'end_date']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }
    
    def clean(self):
        """Validate date range"""
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        
        if start_date and end_date and start_date > end_date:
            raise forms.ValidationError("Start date cannot be after end date.")
        
        return cleaned_data


class BulkTransactionForm(forms.Form):
    """Form for bulk transaction operations"""
    
    transaction_ids = forms.CharField(
        widget=forms.HiddenInput(),
        required=False
    )
    
    action = forms.ChoiceField(
        choices=[
            ('reconcile', 'Mark as Reconciled'),
            ('unreconcile', 'Mark as Not Reconciled'),
            ('void', 'Void Transactions'),
            ('export', 'Export Selected'),
        ]
    )


class ReconciliationForm(forms.Form):
    """Form for bank reconciliation"""
    
    bank_statement_balance = forms.DecimalField(
        label="Bank Statement Balance",
        widget=forms.NumberInput(attrs={'step': '0.01'})
    )
    
    reconciliation_date = forms.DateField(
        label="Reconciliation Date",
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    
    notes = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3}),
        required=False
    )


class ImportTransactionForm(forms.Form):
    """Form for importing transactions from CSV/Excel"""
    
    file = forms.FileField(
        label="Transaction File",
        help_text="Upload CSV or Excel file with transaction data"
    )
    
    has_header = forms.BooleanField(
        initial=True,
        required=False,
        label="File has header row"
    )
    
    date_format = forms.ChoiceField(
        choices=[
            ('%Y-%m-%d', 'YYYY-MM-DD'),
            ('%d/%m/%Y', 'DD/MM/YYYY'),
            ('%m/%d/%Y', 'MM/DD/YYYY'),
        ],
        initial='%Y-%m-%d'
    )
    
    def clean_file(self):
        """Validate uploaded file"""
        file = self.cleaned_data.get('file')
        if file:
            # Check file extension
            allowed_extensions = ['.csv', '.xlsx', '.xls']
            file_extension = file.name.lower()
            
            if not any(file_extension.endswith(ext) for ext in allowed_extensions):
                raise forms.ValidationError(
                    "Please upload a valid CSV or Excel file."
                )
            
            # Check file size (max 5MB)
            if file.size > 5 * 1024 * 1024:
                raise forms.ValidationError(
                    "File size must be less than 5MB."
                )
        
        return file
