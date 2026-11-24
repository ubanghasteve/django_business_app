from django.contrib import admin

from apps.core.admin_base import AccountScopedAdmin
from .models import Receipt


@admin.register(Receipt)
class ReceiptAdmin(AccountScopedAdmin):
    account_scope_lookup = 'invoice__user__account'

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if not request.user.is_superuser:
            account = getattr(request.user, 'account', None)
            if account is not None:
                from apps.invoices.models import Invoice
                from django.contrib.auth import get_user_model
                User = get_user_model()
                if db_field.name == 'invoice':
                    kwargs['queryset'] = Invoice.objects.filter(user__account=account)
                elif db_field.name == 'created_by':
                    kwargs['queryset'] = User.objects.filter(account=account)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
    list_display = (
        'receipt_no', 'client_name', 'amount_received', 'payment_method', 'date_received', 'invoice', 'received_by', 'balance_after_payment',
    )
    search_fields = ('receipt_no', 'client_name', 'invoice__invoice_number', 'transaction_id')
    list_filter = ('payment_method', 'date_received', 'received_by')
    readonly_fields = ('created_at', 'updated_at')
