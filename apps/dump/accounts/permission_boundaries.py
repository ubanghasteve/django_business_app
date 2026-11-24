"""
Permission boundaries for privilege-escalation prevention.

Definitions:
- Superuser-only: Permissions that only is_superuser may assign or use to escalate.
  Includes auth Permission/Group add/change/delete so non-superusers cannot grant
  themselves or others the ability to manage permissions or groups.
- Owner-level: Permissions that might be restricted to account owner in the future;
  currently treated as delegatable if the assigner has them.
- Delegatable: Permissions that a user may assign to a role if and only if the
  user already has that permission. No user may assign a permission they don't have.

NON_DELEGATABLE: Never allow non-superusers to put these into a role. Even if a
user has auth.add_group, they must not be able to create a role that grants
auth.add_group to others (that would allow privilege escalation).
"""
from django.contrib.auth.models import Permission


# Permissions that MUST NOT be assignable by non-superusers when creating/editing roles.
# Assigning these would allow a user to grant themselves or others the ability to
# manage permissions and groups, i.e. privilege escalation.
NON_DELEGATABLE_PERMISSION_CODENAMES = frozenset([
    # auth.Permission – managing permissions would allow granting any permission
    'add_permission',
    'change_permission',
    'delete_permission',
    'view_permission',
    # auth.Group – managing groups could allow adding oneself to a more powerful group
    'add_group',
    'change_group',
    'delete_group',
    'view_group',
])

# App labels for the above (Django's auth app).
NON_DELEGATABLE_APP_LABEL = 'auth'


def _permission_spec(perm: Permission) -> str:
    """Return 'app_label.codename' for a permission."""
    return f"{perm.content_type.app_label}.{perm.codename}"


def get_permissions_user_may_assign(user):
    """
    Return a queryset of Permission objects that the given user is allowed to
    assign when creating or editing a role (AccountGroup).

    Rules:
    - Superuser may assign any permission (no restriction).
    - Non-superuser may assign only:
      1. Permissions they already have (via groups or user_permissions), AND
      2. That are not in NON_DELEGATABLE (auth permission/group management).

    Enforced at form validation and in admin; used by views and APIs.
    """
    from django.db.models import Q

    base = Permission.objects.all().order_by(
        'content_type__app_label',
        'content_type__model',
        'codename',
    )

    if getattr(user, 'is_superuser', False):
        return base

    # Exclude non-delegatable (auth permission/group management)
    base = base.exclude(
        content_type__app_label=NON_DELEGATABLE_APP_LABEL,
        codename__in=NON_DELEGATABLE_PERMISSION_CODENAMES,
    )

    # Restrict to permissions the user has
    user_perm_pks = set(
        user.get_all_permissions()  # returns set of 'app_label.codename'
    )
    if not user_perm_pks:
        return base.none()

    # Build filter: (app_label, codename) in user's permissions
    q = Q()
    for spec in user_perm_pks:
        if '.' in spec:
            app_label, codename = spec.split('.', 1)
            q |= Q(content_type__app_label=app_label, codename=codename)
    return base.filter(q)


def role_permissions_are_subset_of_user(account_group, user) -> bool:
    """
    Return True if every permission granted by the role (AccountGroup's group)
    is a permission the given user has. Used to prevent assigning users to a
    role that would grant more power than the assigner has.

    Superusers bypass (return True). Same-account is enforced elsewhere.
    """
    if getattr(user, 'is_superuser', False):
        return True
    role_perms = account_group.group.permissions.all()
    if not role_perms.exists():
        return True
    user_specs = user.get_all_permissions()
    for perm in role_perms:
        if _permission_spec(perm) not in user_specs:
            return False
    return True


def get_groups_assigner_may_assign(account, assigner):
    """
    Return a queryset of Group objects (via AccountGroup) that the assigner
    may assign to users in the account. Only groups whose permissions are
    a subset of the assigner's permissions (and in the same account).
    Live query only—no caching. Excludes orphaned groups (no AccountGroup).

    Approved account owners always see all roles in their account (avoids
    permission-cache or subset-check edge cases so newly created roles
    appear in Create/Edit team member dropdowns).
    """
    from .models import AccountGroup
    from django.contrib.auth.models import Group

    if getattr(assigner, 'is_superuser', False):
        # Only Groups that still have an AccountGroup for this account (excludes deleted roles)
        return Group.objects.filter(
            account_group__account=account
        ).distinct()

    # Approved account owner (company admin): show all roles in the account
    if getattr(account, 'owner_id', None) and assigner.pk == account.owner_id and getattr(account, 'is_approved', False):
        return Group.objects.filter(
            account_group__account=account
        ).distinct()

    allowed_group_ids = []
    for ag in AccountGroup.objects.filter(account=account).select_related('group'):
        if ag.group_id and role_permissions_are_subset_of_user(ag, assigner):
            allowed_group_ids.append(ag.group_id)
    return Group.objects.filter(pk__in=allowed_group_ids) if allowed_group_ids else Group.objects.none()


def get_account_groups_assigner_may_assign(account, assigner):
    """
    Return a queryset of AccountGroup objects (roles) that the assigner may
    assign to users in the account. Used for team member role dropdown;
    only roles whose permissions are a subset of the assigner's permissions.

    Live query only—no caching. Only returns AccountGroups that exist and
    whose backing Django Group exists (excludes deleted/orphaned roles).
    """
    from .models import AccountGroup

    allowed_groups = get_groups_assigner_may_assign(account, assigner)
    return AccountGroup.objects.filter(
        account=account,
        group__in=allowed_groups,
    ).select_related('group').order_by('role_name')
