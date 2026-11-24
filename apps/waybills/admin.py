from django.contrib import admin

from apps.core.admin_base import AccountScopedAdmin
from .models import Waybill, WaybillItem, WaybillTemplate, WaybillFieldTemplate


class WaybillItemInline(admin.TabularInline):
    model = WaybillItem
    extra = 1
    fields = ['item_data', 'row_order']
    readonly_fields = ['row_order']


@admin.register(Waybill)
class WaybillAdmin(AccountScopedAdmin):
    account_scope_lookup = 'user__account'
    list_display = ['waybill_number', 'user', 'template', 'status', 'waybill_date', 'delivery_date']
    list_filter = ['status', 'waybill_date', 'template', 'user']
    search_fields = ['waybill_number', 'user__email', 'custom_data']
    readonly_fields = ['waybill_number', 'created_at', 'updated_at']
    inlines = [WaybillItemInline]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('waybill_number', 'user', 'template', 'waybill_date', 'delivery_date', 'status')
        }),
        ('Custom Data', {
            'fields': ('custom_data', 'notes'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name in ('user', 'template') and not request.user.is_superuser:
            account = getattr(request.user, 'account', None)
            if account is not None:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                if db_field.name == 'user':
                    kwargs['queryset'] = User.objects.filter(account=account)
                else:
                    kwargs['queryset'] = WaybillTemplate.objects.filter(user__account=account)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(WaybillTemplate)
class WaybillTemplateAdmin(AccountScopedAdmin):
    account_scope_lookup = 'user__account'
    list_display = ['name', 'user', 'document_title', 'number_prefix', 'is_default', 'created_at']

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'user' and not request.user.is_superuser:
            account = getattr(request.user, 'account', None)
            if account is not None:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                kwargs['queryset'] = User.objects.filter(account=account)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
    list_filter = ['is_default', 'created_at', 'user']
    search_fields = ['name', 'description', 'user__email']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'user', 'is_default')
        }),
        ('Document Settings', {
            'fields': ('document_title', 'number_prefix')
        }),
        ('Color Customization', {
            'fields': ('primary_color', 'secondary_color', 'text_color')
        }),
        ('Display Options', {
            'fields': ('show_company_logo', 'show_company_details', 'show_bank_details', 'show_signature')
        }),
        ('Custom Configuration', {
            'fields': ('custom_fields', 'table_columns'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(WaybillItem)
class WaybillItemAdmin(AccountScopedAdmin):
    account_scope_lookup = 'waybill__user__account'
    list_display = ['__str__', 'waybill', 'row_order']

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'waybill' and not request.user.is_superuser:
            account = getattr(request.user, 'account', None)
            if account is not None:
                kwargs['queryset'] = Waybill.objects.filter(user__account=account)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
    list_filter = ['waybill__template', 'waybill__user']
    search_fields = ['item_data', 'waybill__waybill_number']
    readonly_fields = ['row_order']


@admin.register(WaybillFieldTemplate)
class WaybillFieldTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'label', 'field_type', 'is_required', 'created_at']
    list_filter = ['field_type', 'is_required', 'created_at']
    search_fields = ['name', 'label', 'help_text']
    readonly_fields = ['created_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'label', 'field_type', 'is_required')
        }),
        ('Field Configuration', {
            'fields': ('placeholder', 'help_text', 'options')
        }),
        ('Timestamp', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )
