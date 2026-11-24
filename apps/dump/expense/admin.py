# -*- coding: utf-8 -*-
from django.contrib import admin
from django.utils.html import format_html
from django.core.cache import cache
from .models import Expense
from apps.core.admin_base import AccountScopedAdmin


@admin.register(Expense)
class ExpenseAdmin(AccountScopedAdmin):
    account_scope_lookup = 'account'
    list_display = [
        'transaction_id', 'expense_date', 'expense_category', 'department', 'vendor', 'po_number',
        'product_name', 'quantity_purchased', 'quantity_out', 'remaining_quantity_display',
        'unit_price', 'total_amount', 'status', 'approved_by', 'created_by', 'created_at', 'updated_at',
    ]
    list_filter = ['status', 'expense_category', 'expense_date', 'payment_method']
    search_fields = [
        'product_name', 'vendor', 'transaction_id', 'po_number', 'description',
        'expense_category', 'department', 'product_id',
    ]
    readonly_fields = [
        'transaction_id', 'sn', 'total_amount', 'created_at', 'updated_at',
        'company', 'account', 'approved_by', 'approved_at',
    ]
    list_editable = []
    actions = ['approve_selected', 'set_pending']

    fieldsets = (
        ('Identifiers', {'fields': ('transaction_id', 'sn', 'company', 'account', 'created_by', 'approved_by', 'approved_at')}),
        ('Expense header', {'fields': ('expense_date', 'expense_category', 'department', 'vendor', 'po_number', 'description')}),
        ('Product', {'fields': ('product_id', 'product_name', 'product_category', 'product_description', 'unit_of_measurement')}),
        ('Quantities & price', {
            'fields': ('quantity_purchased', 'quantity_out', 'unit_price', 'quantity_threshold',
                       'subtotal', 'tax', 'discount', 'total_amount'),
        }),
        ('Payment', {'fields': ('payment_method', 'payment_date', 'receipt_upload')}),
        ('Status', {'fields': ('status',)}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )

    def remaining_quantity_display(self, obj):
        return obj.remaining_quantity
    remaining_quantity_display.short_description = 'Remaining Quantity'

    @staticmethod
    def _clear_cache_for_queryset(queryset):
        company_ids = queryset.values_list('company_id', flat=True).distinct()
        for cid in company_ids:
            if cid:
                cache.delete(f"expense_list_{cid}")

    @admin.action(description='Approve selected')
    def approve_selected(self, request, queryset):
        updated = queryset.update(status='approved')
        self._clear_cache_for_queryset(queryset)
        self.message_user(request, f'{updated} record(s) approved.')

    @admin.action(description='Set pending')
    def set_pending(self, request, queryset):
        updated = queryset.update(status='pending')
        self._clear_cache_for_queryset(queryset)
        self.message_user(request, f'{updated} record(s) set to pending.')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('company', 'created_by', 'approved_by', 'account')
