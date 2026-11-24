# -*- coding: utf-8 -*-
from django.contrib import admin
from .models import Document


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ('id', 'company', 'document_type', 'processing_status', 'uploaded_by', 'created_at')
    list_filter = ('company', 'document_type', 'processing_status')
    search_fields = ('file',)
    raw_id_fields = ('company', 'uploaded_by')
