from django.contrib import admin

from apps.core.admin_base import AccountScopedAdmin
from .models import Client


@admin.register(Client)
class ClientAdmin(AccountScopedAdmin):
    account_scope_lookup = 'company__account'
    list_display = ("name", "company", "email", "phone", "contact_person", "created_by", "created_at")
    search_fields = ("name", "email", "phone", "company__company_name")
    list_filter = ("company",)
    readonly_fields = ("created_at", "updated_at")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'company' and not request.user.is_superuser:
            account = getattr(request.user, 'account', None)
            if account is not None:
                from apps.core.models import CompanyProfile
                kwargs['queryset'] = CompanyProfile.objects.filter(account=account)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
