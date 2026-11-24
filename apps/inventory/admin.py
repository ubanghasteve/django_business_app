# -*- coding: utf-8 -*-
from django.contrib import admin
from django.utils.html import format_html
from django.core.cache import cache
from .models import Inventory, WasteLog, InventoryIssue
from apps.core.admin_base import AccountScopedAdmin


@admin.register(Inventory)
class InventoryAdmin(AccountScopedAdmin):
    account_scope_lookup = 'account'
    list_display = [
        'transaction_id', 'sn', 'product_name', 'category', 'vendor',
        'quantity_in', 'quantity_out', 'waste', 'actual_quantity_display',
        'unit_price', 'total_amount', 'balance_quantity',
        'stock_status_badge', 'approval_status', 'workflow_status',
        'created_by', 'created_at',
    ]
    list_filter = ['approval_status', 'stock_status', 'workflow_status', 'created_at']
    search_fields = ['product_name', 'vendor', 'transaction_id', 'stock_location', 'category', 'remark']
    readonly_fields = [
        'transaction_id', 'sn', 'total_amount', 'balance_quantity', 'stock_status',
        'created_at', 'updated_at', 'company', 'account',
    ]
    list_editable = []  # use actions for approval
    actions = ['approve_selected', 'set_pending']

    fieldsets = (
        ('Identifiers', {'fields': ('transaction_id', 'sn', 'company', 'account', 'created_by')}),
        ('Product', {'fields': ('product_name', 'category', 'vendor', 'stock_location', 'phone_number')}),
        ('Quantities & Price', {
            'fields': ('quantity_in', 'quantity_out', 'waste', 'unit_price', 'low_stock_threshold',
                       'total_amount', 'balance_quantity', 'stock_status'),
        }),
        ('Status', {'fields': ('approval_status', 'workflow_status', 'remark')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )

    def remaining_quantity_display(self, obj):
        return obj.remaining_quantity
    remaining_quantity_display.short_description = 'Rem. qqt'

    def stock_status_badge(self, obj):
        colors = {'out_of_stock': '#dc3545', 'low_stock': '#ffc107', 'in_stock': '#28a745'}
        color = colors.get(obj.stock_status, '#6c757d')
        return format_html(
            '<span style="background-color:{}; color:white; padding:2px 8px; border-radius:4px;">{}</span>',
            color, obj.get_stock_status_display()
        )
    stock_status_badge.short_description = 'Stock'

    def _clear_cache_for_queryset(queryset):
        company_ids = queryset.values_list('company_id', flat=True).distinct()
        for cid in company_ids:
            if cid:
                cache.delete(f"inventory_list_{cid}")

    @admin.action(description='Approve selected')
    def approve_selected(self, request, queryset):
        updated = queryset.update(approval_status='approved', workflow_status='approved')
        self._clear_cache_for_queryset(queryset)
        self.message_user(request, f'{updated} record(s) approved.')

    @admin.action(description='Set pending')
    def set_pending(self, request, queryset):
        updated = queryset.update(approval_status='pending', workflow_status='pending_approval')
        self._clear_cache_for_queryset(queryset)
        self.message_user(request, f'{updated} record(s) set to pending.')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('company', 'created_by', 'account')

    def actual_quantity_display(self, obj):
        return obj.actual_quantity
    actual_quantity_display.short_description = 'Actual qty'


@admin.register(WasteLog)
class WasteLogAdmin(AccountScopedAdmin):
    account_scope_lookup = 'account'
    list_display = [
        'waste_date', 'inventory', 'quantity', 'total_value_display',
        'reason_badge', 'created_by', 'created_at',
    ]
    list_filter = ['reason', 'waste_date', 'created_at']
    search_fields = ['inventory__product_name', 'description']
    readonly_fields = ['total_value', 'created_at', 'company', 'account']
    date_hierarchy = 'waste_date'

    def total_value_display(self, obj):
        return obj.total_value
    total_value_display.short_description = 'Total Value'

    def reason_badge(self, obj):
        return format_html('<span class="badge bg-warning text-dark">{}</span>', obj.get_reason_display())
    reason_badge.short_description = 'Reason'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('inventory', 'created_by', 'company')


@admin.register(InventoryIssue)
class InventoryIssueAdmin(AccountScopedAdmin):
    account_scope_lookup = 'account'
    list_display = [
        'issued_at', 'inventory', 'quantity', 'recipient_name',
        'created_by', 'created_at',
    ]
    list_filter = ['issued_at', 'created_at']
    search_fields = ['recipient_name', 'inventory__product_name', 'remark']
    readonly_fields = ['created_at', 'company', 'account']
    date_hierarchy = 'issued_at'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('inventory', 'created_by', 'company')
