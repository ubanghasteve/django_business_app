# -*- coding: utf-8 -*-
from django.contrib import admin
from .models import TaxRecord


@admin.register(TaxRecord)
class TaxRecordAdmin(admin.ModelAdmin):
    list_display = ('id', 'company', 'period_type', 'period_start', 'period_end', 'total_revenue', 'total_expenses', 'corporate_tax', 'vat_payable')
    list_filter = ('company', 'period_type')
    raw_id_fields = ('company',)
