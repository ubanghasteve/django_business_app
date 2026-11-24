"""
Django admin for messaging. Company-scoped; admins can view all company
conversations and inspect messages (read-only). No editing of messages.
"""
from django.contrib import admin
from django.utils.html import format_html
from apps.core.admin_base import AccountScopedAdmin
from .models import Conversation, ConversationMember, Message, CallSession, UserPresence, TypingIndicator


@admin.register(Conversation)
class ConversationAdmin(AccountScopedAdmin):
    account_scope_lookup = 'account'
    list_display = ('id', 'name', 'is_group', 'created_by', 'created_at', 'account')
    list_filter = ('is_group', 'created_at')
    search_fields = ('name',)
    readonly_fields = ('created_at',)
    raw_id_fields = ('created_by',)


@admin.register(ConversationMember)
class ConversationMemberAdmin(admin.ModelAdmin):
    list_display = ('conversation', 'user', 'joined_at', 'is_admin', 'last_read_at')
    list_filter = ('is_admin',)
    raw_id_fields = ('conversation', 'user')
    readonly_fields = ('last_read_at',)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        account = getattr(request.user, 'account', None)
        if account:
            return qs.filter(conversation__account=account)
        return qs.none()


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    """Messages are read-only in admin: view only, no add/change/delete."""
    list_display = ('id', 'conversation', 'sender', 'content_preview', 'created_at', 'is_deleted')
    list_filter = ('is_deleted', 'is_image', 'created_at')
    search_fields = ('content',)
    readonly_fields = ('conversation', 'sender', 'content', 'reply_to', 'file', 'is_image', 'created_at', 'is_deleted')
    raw_id_fields = ('reply_to',)

    def content_preview(self, obj):
        if obj.content:
            return (obj.content[:60] + '…') if len(obj.content) > 60 else obj.content
        return '(file)' if obj.file else '—'
    content_preview.short_description = 'Content'

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        account = getattr(request.user, 'account', None)
        if account:
            return qs.filter(conversation__account=account)
        return qs.none()

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CallSession)
class CallSessionAdmin(AccountScopedAdmin):
    account_scope_lookup = 'conversation__account'
    list_display = ('id', 'conversation', 'started_by', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    readonly_fields = ('created_at',)
    raw_id_fields = ('conversation', 'started_by')


@admin.register(UserPresence)
class UserPresenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'account', 'last_seen')
    list_filter = ('last_seen',)
    raw_id_fields = ('user', 'account')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        account = getattr(request.user, 'account', None)
        if account:
            return qs.filter(account=account)
        return qs.none()


@admin.register(TypingIndicator)
class TypingIndicatorAdmin(admin.ModelAdmin):
    list_display = ('conversation', 'user', 'last_typing_at')
    list_filter = ('last_typing_at',)
    raw_id_fields = ('conversation', 'user')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        account = getattr(request.user, 'account', None)
        if account:
            return qs.filter(conversation__account=account)
        return qs.none()
