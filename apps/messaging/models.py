"""
Messaging models with explicit company (account) scoping.
All models are scoped to Account for tenant isolation.
Messages exist only within a conversation; isolation enforced via membership.
"""
import os
import re
from django.db import models
from django.conf import settings
from django.utils import timezone


def message_file_upload_path(instance, filename):
    """Store messaging files under messaging/files/<conversation_id>/<sanitized_filename>.
    Sanitizes filename so the file is always findable after save (no path traversal, safe chars)."""
    base = os.path.basename(filename) if filename else 'file'
    safe = re.sub(r'[^\w\s\-\.]', '_', base)
    safe = (safe[:200] or 'file').strip()
    if not safe:
        safe = 'file'
    return f'messaging/files/{instance.conversation_id}/{safe}'


class Conversation(models.Model):
    """
    Conversation (private or group) scoped to one account (company).
    """
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='messaging_conversations',
        help_text='Company/tenant this conversation belongs to',
    )
    is_group = models.BooleanField(default=False)
    name = models.CharField(max_length=255, null=True, blank=True, help_text='Group name; null for private chats')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_messaging_conversations',
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Conversation'
        verbose_name_plural = 'Conversations'

    def __str__(self):
        if self.is_group and self.name:
            return self.name
        return f'Conversation #{self.pk}'


class ConversationMember(models.Model):
    """Membership in a conversation; required to see messages."""
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='members',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='messaging_memberships',
    )
    joined_at = models.DateTimeField(default=timezone.now)
    is_admin = models.BooleanField(default=False, help_text='Group moderator')
    last_read_at = models.DateTimeField(null=True, blank=True, help_text='Last time user read messages in this conversation (for unread count)')
    left_at = models.DateTimeField(null=True, blank=True, help_text='When user left; null = active member. Can rejoin by clearing this.')

    class Meta:
        unique_together = [['conversation', 'user']]
        ordering = ['joined_at']
        verbose_name = 'Conversation Member'
        verbose_name_plural = 'Conversation Members'

    def __str__(self):
        return f'{self.user} in {self.conversation}'


class Message(models.Model):
    """
    Message in a conversation. Content and file are optional (e.g. file-only message).
    """
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='messaging_messages_sent',
    )
    content = models.TextField(null=True, blank=True)
    reply_to = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='replies',
    )
    file = models.FileField(upload_to=message_file_upload_path, null=True, blank=True)
    is_image = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True, help_text='When deleted for everyone')

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Message'
        verbose_name_plural = 'Messages'
        indexes = [
            models.Index(fields=['conversation', 'created_at'], name='msg_conv_created_idx'),
        ]

    def __str__(self):
        preview = (self.content or '(file)')[:50]
        return f'{self.sender} @ {self.created_at}: {preview}'


class MessageHiddenForUser(models.Model):
    """
    Tracks messages a user has chosen to hide from their own view ("delete for me").
    The message stays in the conversation for others.
    """
    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name='hidden_for_users',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    hidden_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [['message', 'user']]
        verbose_name = 'Message hidden for user'
        verbose_name_plural = 'Messages hidden for users'

    def __str__(self):
        return f'Message {self.message_id} hidden for user {self.user_id}'


class CallSession(models.Model):
    """Call signaling only (no media); status for UI."""
    STATUS_CHOICES = [
        ('calling', 'Calling'),
        ('active', 'Active'),
        ('ended', 'Ended'),
    ]
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='call_sessions',
    )
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='messaging_calls_started',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='calling')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Call Session'
        verbose_name_plural = 'Call Sessions'

    def __str__(self):
        return f'Call #{self.pk} ({self.status})'


class UserPresence(models.Model):
    """Last-seen heartbeat per user per account for online/offline indicator."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='messaging_presence',
    )
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='messaging_presence',
    )
    last_seen = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [['user', 'account']]
        verbose_name = 'User Presence'
        verbose_name_plural = 'User Presences'

    def __str__(self):
        return f'{self.user} @ {self.last_seen}'


class TypingIndicator(models.Model):
    """Lightweight typing state per user per conversation (for polling)."""
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='typing_indicators',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='messaging_typing',
    )
    last_typing_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [['conversation', 'user']]
        verbose_name = 'Typing Indicator'
        verbose_name_plural = 'Typing Indicators'

    def __str__(self):
        return f'{self.user} typing in {self.conversation}'
