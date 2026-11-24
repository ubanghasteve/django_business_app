from django import forms
from .models import Receipt, PAYMENT_CHOICES
from apps.invoices.models import Invoice
from apps.core.ownership import for_user_queryset

class ReceiptForm(forms.ModelForm):
    class Meta:
        model = Receipt
        fields = [
            'invoice', 'client_name', 'client_phone', 'client_address', 'amount_received', 'amount_in_words', 'payment_method',
            'transaction_id', 'received_by', 'notes', 'custom_color', 'show_bank_details', 'show_signature'
        ]
        widgets = {
            'invoice': forms.Select(attrs={'class': 'form-control border', 'data-invoice-select': '1'}),
            'client_name': forms.TextInput(attrs={'class': 'form-control border', 'placeholder': 'Client Name'}),
            'client_phone': forms.TextInput(attrs={'class': 'form-control border', 'placeholder': 'Client Phone'}),
            'client_address': forms.TextInput(attrs={'class': 'form-control border', 'placeholder': 'Client Address'}),
            'amount_received': forms.TextInput(attrs={'class': 'form-control border', 'placeholder': 'Amount Received', 'pattern': r'[0-9,]*\.?[0-9]*', 'title': 'Enter a valid amount (e.g., 1,500.00)'}),
            'amount_in_words': forms.TextInput(attrs={'class': 'form-control border', 'placeholder': 'Amount in Words', 'readonly': 'readonly'}),
            'payment_method': forms.Select(choices=PAYMENT_CHOICES, attrs={'class': 'form-control border', 'placeholder': 'Payment Method'}),
            'transaction_id': forms.TextInput(attrs={'class': 'form-control border', 'placeholder': 'Transaction ID (optional)'}),
            'received_by': forms.TextInput(attrs={'class': 'form-control border', 'placeholder': 'Received By', 'required': 'required'}),
            'notes': forms.Textarea(attrs={'class': 'form-control border', 'rows': 3, 'placeholder': 'Add a note for your customer (optional)'}),
            'custom_color': forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color border', 'placeholder': 'Pick a color'}),
            'show_bank_details': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'show_signature': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
        }

    def __init__(self, *args, **kwargs):
        invoice = kwargs.pop('invoice', None)
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if invoice:
            self.fields['invoice'].initial = invoice.pk
            self.fields['client_name'].initial = invoice.client_name
            self.fields['client_phone'].initial = invoice.client_phone
            self.fields['client_address'].initial = invoice.client_address
        if user is not None:
            self.fields['invoice'].queryset = for_user_queryset(Invoice, user, None, account_lookup='account')
        else:
            self.fields['invoice'].queryset = Invoice.objects.none()
        self.fields['invoice'].empty_label = 'Select Invoice'
        # Add data attributes for JS
        for inv in self.fields['invoice'].queryset:
            self.fields['invoice'].widget.choices.queryset = self.fields['invoice'].queryset
        # Ensure custom_color always has a valid default
        if not self.initial.get('custom_color'):
            self.initial['custom_color'] = '#000000'
        # Default toggles to True for new receipts
        if not self.instance or not self.instance.pk:
            self.initial.setdefault('show_bank_details', True)
            self.initial.setdefault('show_signature', True)

    def clean_amount_received(self):
        amount_str = self.cleaned_data['amount_received']
        # Remove commas and convert to float
        try:
            amount = float(str(amount_str).replace(',', ''))
        except (ValueError, TypeError):
            raise forms.ValidationError('Please enter a valid amount.')
        
        if amount <= 0:
            raise forms.ValidationError('Amount received must be greater than zero.')
        return amount

    def clean(self):
        cleaned = super().clean()
        invoice = cleaned.get('invoice')
        if invoice:
            if not cleaned.get('client_name'):
                cleaned['client_name'] = invoice.client_name
            if not cleaned.get('client_phone'):
                cleaned['client_phone'] = invoice.client_phone
            if not cleaned.get('client_address'):
                cleaned['client_address'] = invoice.client_address
        return cleaned
