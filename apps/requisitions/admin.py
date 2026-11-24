from django.contrib import admin
from apps.core.admin_base import AccountScopedAdmin
from .models import Requisition


@admin.register(Requisition)
class RequisitionAdmin(AccountScopedAdmin):
    account_scope_lookup = 'account'
    list_display = [
        'reference_number', 'organization_name', 'date', 'job_type',
        'status', 'created_by', 'created_at',
    ]
    list_filter = ['company', 'status', 'date']
    search_fields = ['reference_number', 'organization_name']
    readonly_fields = ['reference_number', 'created_at', 'updated_at']
    date_hierarchy = 'date'

    fieldsets = (
        ('Reference', {
            'fields': ('reference_number', 'status', 'date'),
        }),
        ('Tenant', {
            'fields': ('account', 'company', 'created_by'),
        }),
        ('Organization', {
            'fields': ('organization_name', 'address', 'contact_number'),
        }),
        ('Job Details', {
            'fields': ('job_type', 'print_product', 'quantity', 'colors', 'size', 'micron', 'other_info'),
        }),
        ('Signature', {
            'fields': ('signature',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
        }),
    )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'created_by' and not request.user.is_superuser:
            account = getattr(request.user, 'account', None)
            if account is not None:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                kwargs['queryset'] = User.objects.filter(account=account)
        if db_field.name == 'company' and not request.user.is_superuser:
            from apps.core.utils import get_company_profile_for_user
            company = get_company_profile_for_user(request.user, request)
            if company is not None:
                from apps.core.models import CompanyProfile
                kwargs['queryset'] = CompanyProfile.objects.filter(pk=company.pk)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
