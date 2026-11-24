# -*- coding: utf-8 -*-
from django import forms
from django.utils import timezone
from .models import Expense


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
            'quantity_purchased': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'quantity_out': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'unit_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'quantity_threshold': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
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

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:
            instance.created_by = self.user
            if not instance.company_id or not instance.account_id:
                from apps.core.utils import get_company_profile_for_user
                company = get_company_profile_for_user(self.user)
                if company:
                    instance.company_id = company.pk
                if getattr(self.user, 'account_id', None):
                    instance.account_id = self.user.account_id
            if instance.status == 'approved':
                instance.approved_by = self.user
                instance.approved_at = timezone.now()
            else:
                instance.approved_by = None
                instance.approved_at = None
        if commit:
            instance.save()
        return instance
