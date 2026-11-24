# -*- coding: utf-8 -*-
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal

from apps.waybills.utils.quantity_parser import extract_numeric_value
from .models import Inventory


def _parse_mixed_decimal(raw: str) -> Decimal:
    """
    Parse a mixed text+number string into a Decimal using the same semantics
    as waybill quantity parsing. Examples:
        "500bags" -> Decimal('500')
        "7.5 kg"  -> Decimal('7.5')
        "bags only" -> Decimal('0')
    """
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


class InventoryForm(forms.ModelForm):
    class Meta:
        model = Inventory
        fields = [
            'product_name', 'category', 'company_name', 'vendor', 'stock_location', 'phone_number',
            'quantity_in', 'quantity_out', 'unit_price', 'low_stock_threshold',
            'approval_status', 'workflow_status', 'remark',
        ]
        widgets = {
            'product_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Product Name'}),
            'category': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Category'}),
            'company_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Company'}),
            'vendor': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Vendor'}),
            'stock_location': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Stock Location'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone Number'}),
            # Text inputs so users can type values like "500bags", "45,000 per bag"
            'quantity_in': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 500bags'}),
            'quantity_out': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 50bags'}),
            'unit_price': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 45,000 per bag'}),
            'low_stock_threshold': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 10bags'}),
            'approval_status': forms.Select(attrs={'class': 'form-control'}, choices=Inventory.APPROVAL_STATUS_CHOICES),
            'workflow_status': forms.Select(attrs={'class': 'form-control'}, choices=Inventory.WORKFLOW_STATUS_CHOICES),
            'remark': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Remark'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Replace numeric fields with CharField so we can accept mixed text
        # and parse them ourselves, while still assigning Decimal values to
        # the underlying model instance.
        for name in ('quantity_in', 'quantity_out', 'unit_price', 'low_stock_threshold'):
            if name in self.fields:
                widget = self.Meta.widgets.get(name, forms.TextInput(attrs={'class': 'form-control'}))
                self.fields[name] = forms.CharField(
                    required=False,
                    widget=widget,
                    label=self.fields[name].label,
                    help_text=self.fields[name].help_text,
                )

        # When editing, pre-fill the form with the original mixed input text
        # if available; otherwise fall back to the numeric value.
        instance = getattr(self, 'instance', None)
        if instance and instance.pk:
            for field_name, input_attr in (
                ('quantity_in', 'quantity_in_input'),
                ('quantity_out', 'quantity_out_input'),
                ('unit_price', 'unit_price_input'),
                ('low_stock_threshold', 'low_stock_threshold_input'),
            ):
                raw = getattr(instance, input_attr, '') or ''
                if raw:
                    self.initial[field_name] = raw
                else:
                    numeric = getattr(instance, field_name, None)
                    if numeric is not None:
                        self.initial[field_name] = str(numeric)

    def clean_quantity_in(self):
        raw = self.cleaned_data.get('quantity_in', '')
        raw_text = '' if raw is None else str(raw).strip()
        self._quantity_in_input_raw = raw_text
        return _parse_mixed_decimal(raw_text)

    def clean_quantity_out(self):
        raw = self.cleaned_data.get('quantity_out', '')
        raw_text = '' if raw is None else str(raw).strip()
        self._quantity_out_input_raw = raw_text
        return _parse_mixed_decimal(raw_text)

    def clean_unit_price(self):
        raw = self.cleaned_data.get('unit_price', '')
        raw_text = '' if raw is None else str(raw).strip()
        self._unit_price_input_raw = raw_text
        value = _parse_mixed_decimal(raw_text)
        # Ensure unit price never goes negative from parsing
        return max(Decimal('0'), value)

    def clean_low_stock_threshold(self):
        raw = self.cleaned_data.get('low_stock_threshold', '')
        raw_text = '' if raw is None else str(raw).strip()
        self._low_stock_threshold_input_raw = raw_text
        value = _parse_mixed_decimal(raw_text)
        return max(Decimal('0'), value)

    def save(self, commit=True):
        instance = super().save(commit=False)

        # Persist the original mixed text in the *_input fields so that it
        # survives page refreshes and is visible in the list/detail views.
        for attr, value in (
            ('quantity_in_input', getattr(self, '_quantity_in_input_raw', None)),
            ('quantity_out_input', getattr(self, '_quantity_out_input_raw', None)),
            ('unit_price_input', getattr(self, '_unit_price_input_raw', None)),
            ('low_stock_threshold_input', getattr(self, '_low_stock_threshold_input_raw', None)),
        ):
            if value is not None:
                setattr(instance, attr, value)

        if self.user:
            instance.created_by = self.user
            if not instance.company_id or not instance.account_id:
                from apps.core.utils import get_company_profile_for_user
                company = get_company_profile_for_user(self.user)
                if company:
                    instance.company_id = company.pk
                if getattr(self.user, 'account_id', None):
                    instance.account_id = self.user.account_id
            if instance.approval_status == 'approved':
                instance.approved_by = self.user
                instance.approved_at = timezone.now()
            else:
                instance.approved_by = None
                instance.approved_at = None
        if commit:
            instance.save()
        return instance
