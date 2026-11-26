from decimal import Decimal, InvalidOperation

from django import forms
from django.db.models import Q

from apps.core.ownership import for_user_queryset
from apps.invoices.models import Invoice

from .models import PAYMENT_CHOICES, Receipt


class ReceiptForm(forms.ModelForm):
    class Meta:
        model = Receipt
        fields = [
            'invoice', 'client_name', 'client_phone', 'client_address',
            'amount_received', 'amount_in_words', 'payment_method',
            'transaction_id', 'received_by', 'notes', 'custom_color',
            'show_bank_details', 'show_signature',
        ]
        widgets = {
            'invoice': forms.Select(attrs={
                'class': 'form-select receipt-input',
                'data-invoice-select': '1',
                'autocomplete': 'off',
            }),
            'client_name': forms.TextInput(attrs={
                'class': 'form-control receipt-input',
                'placeholder': 'Client name',
                'autocomplete': 'organization',
            }),
            'client_phone': forms.TextInput(attrs={
                'class': 'form-control receipt-input',
                'placeholder': 'Phone',
                'autocomplete': 'tel',
            }),
            'client_address': forms.TextInput(attrs={
                'class': 'form-control receipt-input',
                'placeholder': 'Address',
                'autocomplete': 'street-address',
            }),
            'amount_received': forms.TextInput(attrs={
                'class': 'form-control receipt-input receipt-amount-input',
                'placeholder': '0.00',
                'inputmode': 'decimal',
                'autocomplete': 'off',
                'pattern': r'[0-9,]*\.?[0-9]*',
                'title': 'Enter a valid amount (e.g., 1,500.00)',
            }),
            'amount_in_words': forms.TextInput(attrs={
                'class': 'form-control receipt-input receipt-words-input',
                'placeholder': 'Amount in words appears here',
                'readonly': 'readonly',
                'maxlength': '2000',
                'tabindex': '-1',
            }),
            'payment_method': forms.Select(attrs={'class': 'form-select receipt-input'}),
            'transaction_id': forms.TextInput(attrs={
                'class': 'form-control receipt-input',
                'placeholder': 'Optional reference',
            }),
            'received_by': forms.TextInput(attrs={
                'class': 'form-control receipt-input',
                'placeholder': 'Who received the payment',
                'required': 'required',
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control receipt-input',
                'rows': 3,
                'placeholder': 'Optional note for the customer (shown on printed receipt)',
            }),
            'custom_color': forms.TextInput(attrs={
                'type': 'color',
                'class': 'form-control form-control-color receipt-color-input',
            }),
            'show_bank_details': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
                'role': 'switch',
            }),
            'show_signature': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
                'role': 'switch',
            }),
        }

    def __init__(self, *args, **kwargs):
        invoice = kwargs.pop('invoice', None)
        user = kwargs.pop('user', None)
        default_color = kwargs.pop('default_color', None) or '#1976d2'
        super().__init__(*args, **kwargs)

        qs = Invoice.objects.none()
        if user is not None:
            qs = for_user_queryset(Invoice, user, None, account_lookup='account')
            # Fast dropdown: only invoices that still need payment, plus current selection
            keep_ids = []
            if invoice and getattr(invoice, 'pk', None):
                keep_ids.append(invoice.pk)
            if self.instance and getattr(self.instance, 'invoice_id', None):
                keep_ids.append(self.instance.invoice_id)
            qs = qs.filter(
                Q(status__in=['unpaid', 'partial']) | Q(pk__in=keep_ids)
            ).only(
                'id', 'invoice_number', 'client_name', 'status',
                'grand_total', 'amount_paid', 'balance_due',
            ).order_by('-created_at')

        self.fields['invoice'].queryset = qs
        self.fields['invoice'].empty_label = 'Select an invoice…'
        self.fields['invoice'].label_from_instance = self._invoice_label

        if invoice:
            self.fields['invoice'].initial = invoice.pk
            self.fields['client_name'].initial = invoice.client_name
            self.fields['client_phone'].initial = invoice.client_phone
            self.fields['client_address'].initial = invoice.client_address

        if not self.initial.get('custom_color') and not (self.instance and self.instance.pk and self.instance.custom_color):
            self.initial['custom_color'] = default_color
        # Keep unbound create forms on company theme color
        if not self.is_bound and (not self.instance or not self.instance.pk):
            self.fields['custom_color'].initial = self.initial.get('custom_color') or default_color
        if not self.instance or not self.instance.pk:
            self.initial.setdefault('show_bank_details', True)
            self.initial.setdefault('show_signature', True)

        # Empty payment method prompt
        if hasattr(self.fields['payment_method'], 'choices'):
            choices = list(self.fields['payment_method'].choices)
            if choices and choices[0][0] != '':
                self.fields['payment_method'].choices = [('', 'Select method…')] + choices

    @staticmethod
    def _invoice_label(obj):
        client = (obj.client_name or '').strip()
        bal = obj.balance_due if obj.balance_due is not None else obj.grand_total
        try:
            bal_txt = f"{bal:,.2f}"
        except Exception:
            bal_txt = str(bal)
        status = (obj.status or '').title()
        if client:
            return f"{obj.invoice_number} — {client} · {status} · bal {bal_txt}"
        return f"{obj.invoice_number} · {status} · bal {bal_txt}"

    def clean_amount_received(self):
        amount_str = self.cleaned_data['amount_received']
        try:
            amount = Decimal(str(amount_str).replace(',', '').strip())
        except (ValueError, TypeError, InvalidOperation):
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
