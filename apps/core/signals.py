from django.contrib.auth.signals import user_logged_in
from django.contrib.auth.models import Group, Permission
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from .models import UserActivity

# Role name for the strict read-only group (exact or suffix in Group.name)
COMPANY_READ_ONLY_GROUP_NAME = "Company Read Only"


def _is_company_read_only_group(group):
    """True if group.name is 'Company Read Only' or ends with ':Company Read Only'."""
    if not group or not getattr(group, 'name', None):
        return False
    name = (group.name or '').strip()
    return name == COMPANY_READ_ONLY_GROUP_NAME or name.endswith(":" + COMPANY_READ_ONLY_GROUP_NAME)


def _get_view_only_permissions():
    """
    Permissions for Company Read Only: view_*, print_*, download_*.
    No add_*, change_*, delete_* so users can view, download, and print but not modify.
    """
    from django.db.models import Q
    return Permission.objects.filter(
        Q(codename__startswith='view_') |
        Q(codename__startswith='print_') |
        Q(codename__startswith='download_')
    )


@receiver(post_save, sender=Group)
def enforce_company_read_only_group_permissions(sender, instance, **kwargs):
    """
    No-op for tenant roles: Groups linked to AccountGroup have their permissions
    controlled only by the role form; we never add or remove permissions.
    (Legacy groups not linked to AccountGroup are also left unchanged.)
    """
    from apps.accounts.models import AccountGroup
    try:
        instance.account_group
    except AccountGroup.DoesNotExist:
        pass
    else:
        return  # This Group is a tenant role; do not touch its permissions
    if not _is_company_read_only_group(instance):
        return
    view_only = _get_view_only_permissions()
    current = set(instance.permissions.values_list('pk', flat=True))
    target = set(view_only.values_list('pk', flat=True))
    if current != target:
        instance.permissions.set(view_only)


# REMOVED: pre_save _store_previous_is_approved and post_save promote_users_when_account_approved.
# Approval MUST NOT grant permissions or assign roles. It only controls access gating (middleware).
# Companies must manually create roles, assign permissions, and assign users after approval.


@receiver(user_logged_in)
def record_user_login(sender, request, user, **kwargs):
    """Record user login activity"""
    try:
        UserActivity.record_activity(
            user=user,
            activity_type='login',
            description=f'User logged in from {request.META.get("REMOTE_ADDR", "unknown")}',
            metadata={
                'ip_address': request.META.get('REMOTE_ADDR'),
                'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                'timestamp': timezone.now().isoformat()
            }
        )
    except Exception as e:
        # Log error but don't break the login process
        print(f"Error recording login activity: {e}")
        pass
