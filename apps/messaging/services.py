"""
Queryset and isolation helpers for messaging.
- conversations_for_user(user, request): conversations user is member of; admin sees all company conversations.
- messages_for_user(conversation, user): messages only if user is a member.
DO NOT use raw .objects.all() for user-facing data.
"""
from django.utils import timezone

from apps.core.ownership import get_account_for_user, is_company_admin
from .models import Conversation, ConversationMember, Message, UserPresence


def conversations_for_user(user, request=None):
    """
    Return conversations visible to the user:
    - Team members: only conversations where they are a member.
    - Company admin: all conversations for the account (read-only unless participant).
    """
    if not user or not getattr(user, 'is_authenticated', True):
        return Conversation.objects.none()
    account = get_account_for_user(user)
    if not account:
        return Conversation.objects.none()
    base = Conversation.objects.filter(account=account).distinct()
    if is_company_admin(user, request):
        return base
    member_conversation_ids = ConversationMember.objects.filter(
        user=user, conversation__account=account
    ).values_list('conversation_id', flat=True).distinct()
    return base.filter(id__in=member_conversation_ids).distinct()


def user_can_access_conversation(conversation, user, request=None):
    """
    True if user is allowed to access this conversation (member or company admin).
    """
    if not user or not getattr(user, 'is_authenticated', True):
        return False
    account = get_account_for_user(user)
    if not account or conversation.account_id != account.id:
        return False
    if is_company_admin(user, request):
        return True
    return ConversationMember.objects.filter(
        conversation=conversation, user=user, left_at__isnull=True
    ).exists()


def user_is_group_admin(conversation, user, request=None):
    """True if user can remove members, rename group, or add members (group admin or company admin)."""
    if not user_can_access_conversation(conversation, user, request):
        return False
    if is_company_admin(user, request):
        return True
    if not conversation.is_group:
        return False
    return ConversationMember.objects.filter(
        conversation=conversation, user=user, is_admin=True
    ).exists()


def messages_for_user(conversation, user, request=None):
    """
    Return messages for a conversation only if user is a member (or admin).
    Excludes messages deleted globally (is_deleted) and messages hidden for this user.
    """
    if not user_can_access_conversation(conversation, user, request):
        return Message.objects.none()
    return Message.objects.filter(
        conversation=conversation, is_deleted=False
    ).exclude(
        hidden_for_users__user=user
    ).select_related('sender', 'reply_to').order_by('created_at')


def update_presence(user, request=None):
    """Update last_seen for user in their account; used by heartbeat."""
    if not user or not getattr(user, 'is_authenticated', True):
        return
    account = get_account_for_user(user)
    if not account:
        return
    UserPresence.objects.update_or_create(
        user=user, account=account,
        defaults={'last_seen': timezone.now()},
    )


def set_presence_offline(user, request=None):
    """Set last_seen to the past so user appears offline immediately to others."""
    if not user or not getattr(user, 'is_authenticated', True):
        return
    account = get_account_for_user(user)
    if not account:
        return
    from datetime import timedelta
    past = timezone.now() - timedelta(seconds=120)
    UserPresence.objects.update_or_create(
        user=user, account=account,
        defaults={'last_seen': past},
    )


def is_user_online(user_id, account_id, within_seconds=90):
    """Consider user online if last_seen within the given seconds."""
    threshold = timezone.now() - timezone.timedelta(seconds=within_seconds)
    return UserPresence.objects.filter(
        user_id=user_id, account_id=account_id, last_seen__gte=threshold
    ).exists()
