# -*- coding: utf-8 -*-
from django.contrib import admin
from .models import FinancialTransaction


@admin.register(FinancialTransaction)
class FinancialTransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'company', 'transaction_type', 'amount', 'vat_amount', 'transaction_date', 'reference')
    list_filter = ('company', 'transaction_type')
    raw_id_fields = ('company', 'document')
