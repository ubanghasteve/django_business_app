"""
Notification creation service. Use this to create notifications from any app.
Respects RBAC and multi-tenant isolation - only creates for users in the same account.
Production-safe: resolves user's account for team members (linked_subuser.account_owner).
"""
from django.conf import settings
from django.db.models import Q

from apps.core.ownership import get_account_for_user

from .models import Notification


def _user_account_id(user):
    """Resolve account id for any user: direct account_id or via linked_subuser.account_owner (team members)."""
    if not user:
        return None
    aid = getattr(user, 'account_id', None)
    if aid is not None:
        return aid
    sub = getattr(user, 'linked_subuser', None)
    if sub is not None:
        owner = getattr(sub, 'account_owner', None)
        if owner is not None:
            return getattr(owner, 'account_id', None)
    return None


def create_notification(
    user,
    account,
    source_app,
    title,
    message,
    actor=None,
    action_url='',
    target_type='',
    target_id=None,
):
    """
    Create a notification for a user. Call from signals or views.
    user: recipient (must belong to account)
    account: tenant scope (Account instance or id; will use account.id)
    source_app: one of Notification.SOURCE_APP_CHOICES keys
    title, message: display text
    actor: User who triggered (sender, approver, etc.)
    action_url: URL to navigate when clicked
    target_type, target_id: optional reference to related object
    """
    if not user or not account:
        return None
    account_id = getattr(account, 'id', account) if account else None
    if not account_id:
        return None
    # Ensure user belongs to this account (multi-tenant isolation); works for owner and team members
    user_account = _user_account_id(user)
    if user_account is not None and user_account != account_id:
        return None  # Don't notify users from other tenants
    return Notification.objects.create(
        user=user,
        account_id=account_id,
        source_app=source_app,
        title=title,
        message=message,
        actor=actor,
        action_url=action_url or '',
        target_type=target_type or '',
        target_id=target_id,
    )


def notify_conversation_members(conversation, sender, title, message, action_url, exclude_user=None):
    """
    Create notifications for all conversation members except sender and exclude_user.
    Used for new messages.
    """
    from apps.messaging.models import ConversationMember

    account = conversation.account
    members = ConversationMember.objects.filter(
        conversation=conversation,
        left_at__isnull=True,
    ).exclude(user=sender)
    if exclude_user:
        members = members.exclude(user=exclude_user)
    for m in members.select_related('user'):
        create_notification(
            user=m.user,
            account=account,
            source_app='messaging',
            title=title,
            message=message,
            actor=sender,
            action_url=action_url,
            target_type='conversation',
            target_id=conversation.id,
        )


def get_hr_notification_recipients(account):
    """
    Users in the account who should receive HR notifications (new leave, new employee).
    Automatically detects: account owner, team members with HR permissions
    (view_hr_dashboard, view_employee, or view_own_hr_dashboard) scoped to hr_staff app.
    """
    from django.contrib.auth import get_user_model
    from django.contrib.contenttypes.models import ContentType
    from django.db.models import Q

    User = get_user_model()
    if not account:
        return User.objects.none()
    # HR permission IDs (hr_staff app only) so we don't match same codename from other apps
    try:
        ct = ContentType.objects.get(app_label='hr_staff', model='employee')
        hr_perm_ids = list(
            ct.permission_set.filter(
                codename__in=['view_hr_dashboard', 'view_employee', 'view_own_hr_dashboard']
            ).values_list('id', flat=True)
        )
    except Exception:
        hr_perm_ids = []
    base = User.objects.filter(account_id=account.id)
    owner_id = getattr(account, 'owner_id', None)
    if hr_perm_ids:
        if owner_id:
            recipients = base.filter(
                Q(pk=owner_id) | Q(groups__permissions__in=hr_perm_ids)
            ).distinct()
        else:
            recipients = base.filter(groups__permissions__in=hr_perm_ids).distinct()
    else:
        recipients = base.filter(pk=owner_id) if owner_id else User.objects.none()
    return recipients


def get_company_admin_and_visibility_recipients(account):
    """
    Users in the account who should receive watcher notifications for
    record changes:
    - Company admin (account owner)
    - Any role with full_company_visibility=True (Full company visibility)

    Final visibility and authority are still enforced via:
    - Notification tenant scoping (account)
    - Notification list API permission filtering (per app)
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    if not account:
        return User.objects.none()

    base = User.objects.filter(account_id=account.id)
    owner_id = getattr(account, 'owner_id', None)

    watcher_filter = Q(groups__account_group__account=account,
                       groups__account_group__full_company_visibility=True)
    if owner_id:
        watcher_filter = watcher_filter | Q(pk=owner_id)

    return base.filter(watcher_filter).distinct()


def get_users_in_account(account):
    """
    All users in the account (owner + team members with linked_user).
    Used for notifications that should go to anyone in the account with app access.
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()
    if not account:
        return User.objects.none()
    return User.objects.filter(account_id=account.id)
