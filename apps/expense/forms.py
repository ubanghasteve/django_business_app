# -*- coding: utf-8 -*-
from decimal import Decimal
from django import forms
from django.utils import timezone
from apps.waybills.utils.quantity_parser import extract_numeric_value
from .models import Expense


def _parse_mixed_decimal(raw) -> Decimal:
    """Parse mixed text+number (e.g. '500bags', '₦5,492') into Decimal."""
    if raw is None:
        return Decimal('0')
    text = str(raw).strip()
    if not text:
        return Decimal('0')
    try:
        num = extract_numeric_value(text)
        return Decimal(str(num))
    except Exception:
        return Decimal('0')


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = [
            'expense_date', 'expense_category', 'department', 'vendor', 'po_number', 'description',
            'product_id', 'product_name', 'product_category', 'product_description', 'unit_of_measurement',
            'quantity_purchased', 'quantity_out', 'unit_price', 'quantity_threshold',
            'subtotal', 'tax', 'discount',
            'payment_method', 'payment_date', 'receipt_upload',
            'status',
        ]
        widgets = {
            'expense_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'expense_category': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Expense Category'}),
            'department': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Department'}),
            'vendor': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Vendor'}),
            'po_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'PO Number'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Description'}),
            'product_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Product ID'}),
            'product_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Product Name'}),
            'product_category': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Product Category'}),
            'product_description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Product Description'}),
            'unit_of_measurement': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. pieces, kg'}),
            'quantity_purchased': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 500bags'}),
            'quantity_out': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 50bags'}),
            'unit_price': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. ₦45,000 per bag'}),
            'quantity_threshold': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 10bags'}),
            'subtotal': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'tax': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'discount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'payment_method': forms.Select(attrs={'class': 'form-control form-select'}, choices=Expense.PAYMENT_METHOD_CHOICES),
            'payment_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'receipt_upload': forms.FileInput(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control form-select'}, choices=Expense.STATUS_CHOICES),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        # Use CharField for mixed text+number inputs (parsed in clean_*)
        for name in ('quantity_purchased', 'quantity_out', 'unit_price', 'quantity_threshold'):
            if name in self.fields:
                w = self.fields[name].widget
                self.fields[name] = forms.CharField(required=False, widget=w, label=self.fields[name].label, help_text=self.fields[name].help_text)
        instance = getattr(self, 'instance', None)
        if instance and instance.pk:
            for field_name, input_attr in (
                ('quantity_purchased', 'quantity_purchased_input'),
                ('quantity_out', 'quantity_out_input'),
                ('unit_price', 'unit_price_input'),
                ('quantity_threshold', 'quantity_threshold_input'),
            ):
                raw = getattr(instance, input_attr, '') or ''
                self.initial[field_name] = raw if raw else str(getattr(instance, field_name, '') or '')

    def clean_quantity_purchased(self):
        raw = self.cleaned_data.get('quantity_purchased', '')
        self._quantity_purchased_input_raw = '' if raw is None else str(raw).strip()
        return _parse_mixed_decimal(raw)

    def clean_quantity_out(self):
        raw = self.cleaned_data.get('quantity_out', '')
        self._quantity_out_input_raw = '' if raw is None else str(raw).strip()
        return _parse_mixed_decimal(raw)

    def clean_unit_price(self):
        raw = self.cleaned_data.get('unit_price', '')
        self._unit_price_input_raw = '' if raw is None else str(raw).strip()
        return max(Decimal('0'), _parse_mixed_decimal(raw))

    def clean_quantity_threshold(self):
        raw = self.cleaned_data.get('quantity_threshold', '')
        self._quantity_threshold_input_raw = '' if raw is None else str(raw).strip()
        return max(Decimal('0'), _parse_mixed_decimal(raw))

    def save(self, commit=True):
        instance = super().save(commit=False)
        for attr, raw_attr in (
            ('quantity_purchased_input', '_quantity_purchased_input_raw'),
            ('quantity_out_input', '_quantity_out_input_raw'),
            ('unit_price_input', '_unit_price_input_raw'),
            ('quantity_threshold_input', '_quantity_threshold_input_raw'),
        ):
            if hasattr(self, raw_attr):
                setattr(instance, attr, getattr(self, raw_attr, '') or '')
        if self.user:
            instance.created_by = self.user
            if not instance.company_id or not instance.account_id:
                from apps.core.utils import get_company_profile_for_user
                company = get_company_profile_for_user(self.user)
                if company:
                    instance.company_id = company.pk
                from apps.core.ownership import get_account_for_user
                acc = get_account_for_user(self.user)
                if acc:
                    instance.account_id = acc.id
            if instance.status == 'approved':
                instance.approved_by = self.user
                instance.approved_at = timezone.now()
            else:
                instance.approved_by = None
                instance.approved_at = None
        if commit:
            instance.save()
        return instance
