from django.contrib import admin

from apps.core.admin_base import AccountScopedAdmin
from .models import Invoice, InvoiceItem


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 1
    readonly_fields = ('line_total',)


@admin.register(Invoice)
class InvoiceAdmin(AccountScopedAdmin):
    account_scope_lookup = 'user__account'
    list_display = ['invoice_number', 'client_name', 'invoice_date', 'due_date', 'grand_total', 'status', 'user']
    list_filter = ['status', 'invoice_date', 'user']
    search_fields = ['invoice_number', 'client_name', 'client_email']
    readonly_fields = ['invoice_number', 'subtotal', 'grand_total', 'balance_due', 'created_at', 'updated_at']
    inlines = [InvoiceItemInline]
    
    fieldsets = (
        ('Invoice Information', {
            'fields': ('invoice_number', 'invoice_date', 'due_date', 'user')
        }),
        ('Client Information', {
            'fields': ('client_name', 'client_phone', 'client_email', 'client_address')
        }),
        ('Financial Information', {
            'fields': ('subtotal', 'total_tax', 'total_discount', 'shipping_fee', 'other_charges', 'grand_total')
        }),
        ('Payment Information', {
            'fields': ('amount_paid', 'balance_due', 'status')
        }),
        ('Additional Information', {
            'fields': ('notes', 'created_at', 'updated_at')
        })
    )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'user' and not request.user.is_superuser:
            account = getattr(request.user, 'account', None)
            if account is not None:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                kwargs['queryset'] = User.objects.filter(account=account)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(InvoiceItem)
class InvoiceItemAdmin(AccountScopedAdmin):
    account_scope_lookup = 'invoice__user__account'
    list_display = ['invoice', 'description', 'quantity', 'unit_price', 'line_total']
    list_filter = ['invoice__user']
    search_fields = ['description', 'invoice__invoice_number']
    readonly_fields = ['line_total']
