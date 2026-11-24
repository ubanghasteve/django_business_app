from django.contrib import admin

from .models import BulkSendLog


@admin.register(BulkSendLog)
class BulkSendLogAdmin(admin.ModelAdmin):
    list_display = ['id', 'sent_at', 'send_type', 'recipient_count', 'initiated_by']
    list_filter = ['send_type', 'sent_at']
    search_fields = ['initiated_by__email', 'initiated_by__username']
    date_hierarchy = 'sent_at'
