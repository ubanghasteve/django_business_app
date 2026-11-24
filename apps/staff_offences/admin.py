from django.contrib import admin
from apps.core.admin_base import AccountScopedAdmin
from .models import StaffOffenceRegister, StaffOffenceEntry


class StaffOffenceEntryInline(admin.TabularInline):
    model = StaffOffenceEntry
    extra = 0
    fields = ['date', 'description', 'amount', 'created_by', 'created_at']
    readonly_fields = ['created_at']


@admin.register(StaffOffenceRegister)
class StaffOffenceRegisterAdmin(AccountScopedAdmin):
    account_scope_lookup = 'account'
    list_display = [
        'reference_number', 'staff_name', 'department_name', 'month', 'year',
        'payment_status', 'created_by', 'created_at',
    ]
    list_filter = ['company', 'year', 'month', 'payment_status']
    search_fields = ['reference_number', 'department_name', 'staff_name']
    readonly_fields = ['reference_number', 'created_at', 'updated_at']
    inlines = [StaffOffenceEntryInline]
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Reference', {
            'fields': ('reference_number', 'year', 'month'),
        }),
        ('Tenant', {
            'fields': ('account', 'company', 'created_by'),
        }),
        ('Staff', {
            'fields': ('staff_name', 'department_name'),
        }),
        ('Payment', {
            'fields': ('payment_status',),
        }),
        ('Authorization', {
            'fields': ('authorized_signatory_name', 'authorized_signature'),
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


@admin.register(StaffOffenceEntry)
class StaffOffenceEntryAdmin(admin.ModelAdmin):
    list_display = ['date', 'description', 'amount', 'register', 'created_by', 'created_at']
    list_filter = ['date']
    search_fields = ['description', 'register__reference_number', 'register__staff_name']
    readonly_fields = ['created_at', 'updated_at']
