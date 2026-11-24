# -*- coding: utf-8 -*-
import re
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal

from apps.waybills.utils.quantity_parser import extract_numeric_value
from .models import Store, WasteLog, StoreCategory, StoreCustomField, StoreCustomForm, StoreLayout


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


class StoreForm(forms.ModelForm):
    class Meta:
        model = Store
        fields = [
            'product_name', 'category', 'company_name', 'vendor', 'stock_location', 'phone_number',
            'quantity_in', 'quantity_out', 'waste', 'unit_price', 'low_stock_threshold',
            'approval_status', 'workflow_status', 'remark', 'date', 'opening_stock',
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
            'waste': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 5bags'}),
            'unit_price': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 45,000 per bag'}),
            'low_stock_threshold': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 10bags'}),
            'approval_status': forms.Select(attrs={'class': 'form-control'}, choices=Store.APPROVAL_STATUS_CHOICES),
            'workflow_status': forms.Select(attrs={'class': 'form-control'}, choices=Store.WORKFLOW_STATUS_CHOICES),
            'remark': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Remark'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'opening_stock': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 500bags'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if not self.instance.pk:
            from datetime import date
            self.fields['date'].initial = date.today()

        # Replace numeric fields with CharField so we can accept mixed text
        # and parse them ourselves, while still assigning Decimal values to
        # the underlying model instance.
        for name in ('quantity_in', 'quantity_out', 'waste', 'unit_price', 'low_stock_threshold', 'opening_stock'):
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
                ('opening_stock', 'opening_stock'),
                ('waste', 'waste_input'),
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

    def clean_waste(self):
        raw = self.cleaned_data.get('waste', '')
        raw_text = '' if raw is None else str(raw).strip()
        self._waste_input_raw = raw_text
        value = _parse_mixed_decimal(raw_text)
        return max(Decimal('0'), value)

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

    def clean_opening_stock(self):
        raw = self.cleaned_data.get('opening_stock', '')
        raw_text = '' if raw is None else str(raw).strip()
        self._opening_stock_input = raw_text
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
            ('opening_stock_input', getattr(self, '_opening_stock_input', None)),
            ('waste_input', getattr(self, '_waste_input_raw', None)),
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
                from apps.core.ownership import get_account_for_user
                acc = get_account_for_user(self.user)
                if acc:
                    instance.account_id = acc.id
            if instance.approval_status == 'approved':
                instance.approved_by = self.user
                instance.approved_at = timezone.now()
            else:
                instance.approved_by = None
                instance.approved_at = None
        if commit:
            instance.save()
        return instance


class WasteLogForm(forms.ModelForm):
    class Meta:
        model = WasteLog
        fields = ['store', 'quantity', 'reason', 'description', 'waste_date']
        widgets = {
            'store': forms.Select(attrs={'class': 'form-control'}),
            'quantity': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 5bags'}),
            'reason': forms.Select(attrs={'class': 'form-control'}, choices=WasteLog.WASTE_REASON_CHOICES),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Additional details about the waste incident...'}),
            'waste_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.company = kwargs.pop('company', None)
        super().__init__(*args, **kwargs)
        if 'quantity' in self.fields:
            self.fields['quantity'] = forms.CharField(
                required=False,
                widget=self.Meta.widgets.get('quantity', forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 5bags'})),
                label='Quantity',
                help_text='Quantity wasted.',
            )
        instance = getattr(self, 'instance', None)
        if instance and instance.pk and instance.store_id:
            self.initial['store'] = instance.store_id
        
        # Limit store choices to current company's active store items
        if self.company:
            from apps.core.ownership import for_user_queryset
            self.fields['store'].queryset = Store.objects.filter(
                company=self.company, is_deleted=False
            ).exclude(quantity_in=Decimal('0')).order_by('product_name')

    def clean_quantity(self):
        raw = self.cleaned_data.get('quantity', '')
        raw_text = '' if raw is None else str(raw).strip()
        self._quantity_input_raw = raw_text
        value = _parse_mixed_decimal(raw_text)
        return max(Decimal('0'), value)

    def clean(self):
        cleaned_data = super().clean()
        store = cleaned_data.get('store')
        quantity = cleaned_data.get('quantity', Decimal('0'))
        if store:
            actual_qty = store.actual_quantity
            if quantity > actual_qty:
                raise forms.ValidationError({
                    'quantity': f'Waste quantity ({quantity}) cannot exceed actual usable quantity ({actual_qty}).'
                })
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:
            instance.created_by = self.user
        if instance.store_id:
            instance.unit_price = instance.store.unit_price or Decimal('0')
        if commit:
            instance.save()
        return instance


import json


class StoreCategoryForm(forms.ModelForm):
    class Meta:
        model = StoreCategory
        fields = ['name', 'description', 'color']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Category Name'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Description (optional)'}),
            'color': forms.TextInput(attrs={'class': 'form-control', 'type': 'color', 'style': 'height:38px;width:60px;'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.company = kwargs.pop('company', None)
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip()
        if not name:
            raise forms.ValidationError('Category name is required.')
        if self.company:
            exists = StoreCategory.objects.filter(
                company=self.company, name__iexact=name
            ).exclude(pk=self.instance.pk if self.instance.pk else None).exists()
            if exists:
                raise forms.ValidationError('A category with this name already exists.')
        return name

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:
            instance.created_by = self.user
        if self.company and not instance.company_id:
            instance.company_id = self.company.id
        if commit:
            instance.save()
        return instance


class StoreCustomFieldForm(forms.ModelForm):
    options_text = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'One option per line, e.g.\nOption 1\nOption 2\nOption 3'}),
        label='Options (for select fields)',
        help_text='Enter one option per line. Only used when field type is "Select".',
    )

    class Meta:
        model = StoreCustomField
        fields = ['name', 'field_key', 'field_type', 'required', 'order', 'active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Field Display Name'}),
            'field_key': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'field_key'}),
            'field_type': forms.Select(attrs={'class': 'form-control'}),
            'required': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'order': forms.NumberInput(attrs={'class': 'form-control'}),
            'active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.company = kwargs.pop('company', None)
        super().__init__(*args, **kwargs)
        instance = getattr(self, 'instance', None)
        if instance and instance.pk:
            self.fields['options_text'].initial = '\n'.join(instance.get_options())

    def clean_field_key(self):
        key = self.cleaned_data.get('field_key', '').strip().lower()
        if not key:
            raise forms.ValidationError('Field key is required.')
        if not re.match(r'^[a-z0-9_]+$', key):
            raise forms.ValidationError('Field key must contain only lowercase letters, numbers, and underscores.')
        return key

    def clean_options_text(self):
        text = self.cleaned_data.get('options_text', '')
        if text:
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            return json.dumps(lines)
        return ''

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.options = self.cleaned_data.get('options_text', '')
        if commit:
            instance.save()
        return instance


class StoreCustomFormForm(forms.ModelForm):
    class Meta:
        model = StoreCustomForm
        fields = [
            'name', 'description', 'fields', 'primary_color', 'secondary_color',
            'accent_color', 'text_color', 'show_logo', 'show_company_name',
            'show_currency', 'footer_text',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Form Name'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Description'}),
            'fields': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'JSON list of field keys'}),
            'primary_color': forms.TextInput(attrs={'class': 'form-control', 'type': 'color', 'style': 'height:38px;width:60px;'}),
            'secondary_color': forms.TextInput(attrs={'class': 'form-control', 'type': 'color', 'style': 'height:38px;width:60px;'}),
            'accent_color': forms.TextInput(attrs={'class': 'form-control', 'type': 'color', 'style': 'height:38px;width:60px;'}),
            'text_color': forms.TextInput(attrs={'class': 'form-control', 'type': 'color', 'style': 'height:38px;width:60px;'}),
            'show_logo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_company_name': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_currency': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'footer_text': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Footer text for printouts'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.company = kwargs.pop('company', None)
        super().__init__(*args, **kwargs)
        instance = getattr(self, 'instance', None)
        if instance and instance.pk:
            try:
                keys = json.loads(instance.fields)
                if isinstance(keys, list):
                    self.initial['fields'] = json.dumps(keys, indent=2)
            except (json.JSONDecodeError, TypeError):
                pass

    def clean_fields(self):
        fields = self.cleaned_data.get('fields', '').strip()
        if not fields:
            return '[]'
        try:
            parsed = json.loads(fields)
            if not isinstance(parsed, list):
                raise forms.ValidationError('Fields must be a JSON list.')
            return json.dumps(parsed)
        except json.JSONDecodeError:
            raise forms.ValidationError('Invalid JSON format.')

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:
            instance.created_by = self.user
        if self.company and not instance.company_id:
            instance.company_id = self.company.id
        if commit:
            instance.save()
        return instance

class StoreLayoutForm(forms.ModelForm):
    columns_json = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 12, 'style': 'font-family:monospace;font-size:0.85rem;'}),
        label='Columns JSON',
        help_text='JSON array of column definitions. Each column: {"key","label","width","visible","order"}',
    )

    class Meta:
        model = StoreLayout
        fields = [
            'name', 'description', 'columns', 'supports_calculations',
            'show_totals', 'show_grand_total', 'primary_color', 'secondary_color',
            'accent_color', 'text_color', 'is_default',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Layout Name'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Description'}),
            'columns': forms.HiddenInput(),
            'supports_calculations': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_totals': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_grand_total': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'primary_color': forms.TextInput(attrs={'class': 'form-control', 'type': 'color', 'style': 'height:38px;width:60px;'}),
            'secondary_color': forms.TextInput(attrs={'class': 'form-control', 'type': 'color', 'style': 'height:38px;width:60px;'}),
            'accent_color': forms.TextInput(attrs={'class': 'form-control', 'type': 'color', 'style': 'height:38px;width:60px;'}),
            'text_color': forms.TextInput(attrs={'class': 'form-control', 'type': 'color', 'style': 'height:38px;width:60px;'}),
            'is_default': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.company = kwargs.pop('company', None)
        super().__init__(*args, **kwargs)
        instance = getattr(self, 'instance', None)
        if instance and instance.pk:
            cols = instance.get_columns()
            self.fields['columns_json'].initial = json.dumps(cols, indent=2)
        else:
            default_cols = StoreLayout()._default_columns()
            self.fields['columns_json'].initial = json.dumps(default_cols, indent=2)

    def clean_columns_json(self):
        text = self.cleaned_data.get('columns_json', '').strip()
        if not text:
            return '[]'
        try:
            parsed = json.loads(text)
            if not isinstance(parsed, list):
                raise forms.ValidationError('Columns must be a JSON array.')
            for col in parsed:
                if not isinstance(col, dict):
                    raise forms.ValidationError('Each column must be a JSON object.')
                if 'key' not in col:
                    raise forms.ValidationError('Each column must have a "key" field.')
            return json.dumps(parsed)
        except json.JSONDecodeError as e:
            raise forms.ValidationError(f'Invalid JSON: {e}')

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.columns = self.cleaned_data.get('columns_json', '[]')
        if self.user:
            instance.created_by = self.user
        if self.company and not instance.company_id:
            instance.company_id = self.company.id
        if commit:
            instance.save()
        return instance
