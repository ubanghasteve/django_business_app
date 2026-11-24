import threading
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models.signals import m2m_changed, post_save, pre_save, post_delete, post_migrate
from django.dispatch import receiver

from apps.core.models import Account
from .models import AccountGroup, SubUser, UserActivity
from .services import (
    assign_new_user_to_default_role,
    get_or_create_company_admin_group,
    assign_user_to_account_group,
    get_all_permission_codenames,
    update_account_group_permissions,
    sync_requisition_permissions_to_company_admin,
    sync_staff_offence_permissions_to_company_admin,
    sync_inventory_permissions_to_company_admin,
    sync_expense_permissions_to_company_admin,
    sync_hr_staff_permissions_to_company_admin,
    sync_mailing_permissions_to_company_admin,
    sync_store_permissions_to_company_admin,
    sync_invoice_movement_permissions_to_company_admin,
    sync_videocalls_permissions_to_company_admin,
)
from .default_role import COMPANY_ADMIN_ROLE_NAME

User = get_user_model()

# Store previous is_approved per Account for approval automation
_previous_account_approved = threading.local()


def _get_previous_approved():
    if not hasattr(_previous_account_approved, 'value'):
        _previous_account_approved.value = {}
    return _previous_account_approved.value


def _clear_user_permission_cache(user: User) -> None:
    """
    Clear Django's internal permission caches for a user.

    This ensures that changes to group membership or group permissions are
    reflected immediately in calls to user.has_perm().
    """
    for attr in ('_perm_cache', '_group_perm_cache', '_obj_perm_cache'):
        if hasattr(user, attr):
            delattr(user, attr)


@receiver(post_save, sender=User)
def ensure_user_has_account(sender, instance: User, created: bool, **kwargs) -> None:
    """
    Ensure every User belongs to exactly one Account.

    - On first save of a User without an account, automatically create an
      Account and link the user as its owner.
    - This guarantees the invariant "each user has an owning tenant account"
      without requiring every creation path to remember to set account.
    - New users are then assigned only the default onboarding role (Company Profile
      Viewer) so they start locked down until a superuser upgrades them.
    """
    if not created:
        return

    # If an account was explicitly set, respect it.
    if instance.account_id:
        assign_new_user_to_default_role(instance)
        UserActivity.log_activity(
            user=instance,
            account=instance.account,
            activity_type='CREATE',
            description=f"User account created: {instance.get_full_name() or instance.email}",
            app_name='accounts',
            model_name='User',
            object_id=str(instance.pk),
            object_repr=instance.get_full_name() or instance.email,
        )
        return

    # If this user is linked to a SubUser (team member), inherit the owner's account
    # instead of creating a new standalone tenant. This ensures team members always
    # share the same company/account context (logo, company profile, etc.) as the owner.
    linked_subuser = getattr(instance, 'linked_subuser', None)
    if linked_subuser and getattr(getattr(linked_subuser, 'account_owner', None), 'account_id', None):
        owner_account = linked_subuser.account_owner.account
        instance.account = owner_account
        instance.save(update_fields=['account'])
        assign_new_user_to_default_role(instance)
        UserActivity.log_activity(
            user=instance,
            account=owner_account,
            activity_type='CREATE',
            description=f"Team member user created: {instance.get_full_name() or instance.email}",
            app_name='accounts',
            model_name='User',
            object_id=str(instance.pk),
            object_repr=instance.get_full_name() or instance.email,
        )
        return

    # Fallback: create a new account for standalone users (owners).
    # Use filter().first() and create only when none exists so we never create duplicate Accounts for the same owner.
    account_name = instance.get_full_name() or instance.email or ''
    account = Account.objects.filter(owner=instance).first()
    if not account:
        account = Account.objects.create(owner=instance, name=account_name)
    else:
        if account.name != account_name:
            account.name = account_name
            account.save(update_fields=['name'])
    # Persist link so the account appears in admin for approval; update() ensures the row is committed.
    User.objects.filter(pk=instance.pk).update(account_id=account.id)
    instance.account = account
    # Assign default locked-down role so new users cannot access business modules.
    assign_new_user_to_default_role(instance)

    # Activity log: user creation (account is now set)
    UserActivity.log_activity(
        user=instance,
        account=instance.account,
        activity_type='CREATE',
        description=f"User account created: {instance.get_full_name() or instance.email}",
        app_name='accounts',
        model_name='User',
        object_id=str(instance.pk),
        object_repr=instance.get_full_name() or instance.email,
    )


@receiver(pre_save, sender=Account)
def _store_previous_account_approved(sender, instance: Account, **kwargs) -> None:
    """Store is_approved before save so post_save can detect transition to True."""
    if instance.pk:
        try:
            old = Account.objects.filter(pk=instance.pk).values_list('is_approved', flat=True).first()
            prev = _get_previous_approved()
            prev[instance.pk] = old
        except Exception:
            pass


@receiver(post_save, sender=Account)
def promote_owner_to_company_admin_when_approved(sender, instance: Account, created: bool, **kwargs) -> None:
    """
    When an account is approved (is_approved becomes True), automatically:
    - Ensure Company Admin group exists with ALL permissions from the DB (every app, including
      Bulk Mailing, HR & Staff, Requisitions, Inventory, Expense, Payroll, Smart Attendance,
      Documents, Reports, Accounting, Messaging, and all other apps).
    - Assign the account owner to the Company Admin group so they see all apps in the side nav
      and can use all features without restriction.
    Permissions come from Django's auth_permission table (and project permission tables);
    post_migrate keeps existing Company Admins in sync when new apps are added.
    """
    if not instance.is_approved:
        return
    prev = _get_previous_approved()
    was_approved_before = prev.pop(instance.pk, None) if instance.pk else False
    if was_approved_before and not created:
        return  # Already approved; no transition
    owner_id = getattr(instance, 'owner_id', None)
    if not owner_id:
        return
    try:
        # Create/get Company Admin group with ALL permissions
        ag = get_or_create_company_admin_group(instance)
    except Exception:
        return

    try:
        # Get ALL permissions from database and assign to Company Admin
        all_codenames = get_all_permission_codenames()

        # Add auth permissions for group management
        auth_extra = ['auth.view_group', 'auth.add_group', 'auth.change_group', 'auth.delete_group']
        for c in auth_extra:
            if c not in all_codenames:
                all_codenames.append(c)

        # Assign all permissions to Company Admin
        update_account_group_permissions(ag, all_codenames)

        # Assign owner to Company Admin group
        owner = User.objects.filter(pk=owner_id).first()
        if owner and ag.group_id:
            if ag.group not in owner.groups.all():
                assign_user_to_account_group(owner, ag)
                _clear_user_permission_cache(owner)
            else:
                # Already in group, but ensure cache is clear
                _clear_user_permission_cache(owner)
    except Exception:
        # Fallback: sync each app's permissions individually, then refresh from DB
        for _sync_fn in (
            sync_requisition_permissions_to_company_admin,
            sync_staff_offence_permissions_to_company_admin,
            sync_inventory_permissions_to_company_admin,
            sync_expense_permissions_to_company_admin,
            sync_hr_staff_permissions_to_company_admin,
            sync_mailing_permissions_to_company_admin,
            sync_store_permissions_to_company_admin,
            sync_invoice_movement_permissions_to_company_admin,
            sync_videocalls_permissions_to_company_admin,
        ):
            try:
                _sync_fn()
            except Exception:
                pass
        try:
            all_codenames = get_all_permission_codenames()
            auth_extra = ['auth.view_group', 'auth.add_group', 'auth.change_group', 'auth.delete_group']
            for c in auth_extra:
                if c not in all_codenames:
                    all_codenames.append(c)
            update_account_group_permissions(ag, all_codenames)
            owner = User.objects.filter(pk=owner_id).first()
            if owner and ag.group_id and ag.group not in owner.groups.all():
                assign_user_to_account_group(owner, ag)
                _clear_user_permission_cache(owner)
        except Exception:
            pass
    except Exception:
        pass


@receiver(post_migrate)
def sync_company_admin_all_permissions_after_migrate(sender, **kwargs):
    """
    After any migration, ensure every Company Admin role (all accounts) has ALL
    permissions from the database. This gives existing company owners full access
    to new apps (Inventory, Expense, Requisitions, HR & Staff, etc.) and all
    features so they see every app in the side nav without manual sync.
    """
    try:
        codenames = get_all_permission_codenames()
        auth_extra = ['auth.view_group', 'auth.add_group', 'auth.change_group', 'auth.delete_group']
        for c in auth_extra:
            if c not in codenames:
                codenames.append(c)
        for ag in AccountGroup.objects.filter(role_name=COMPANY_ADMIN_ROLE_NAME).select_related('group'):
            if ag.group_id:
                update_account_group_permissions(ag, codenames)
    except Exception:
        pass


@receiver(post_save, sender=AccountGroup)
def enforce_company_read_only_permissions(sender, instance: AccountGroup, **kwargs) -> None:
    """
    No-op: we do not strip or change permissions for any role. Super admin's
    permission selection (for any role name, including full_company_visibility
    roles) is preserved exactly. Full company visibility is controlled by
    AccountGroup.full_company_visibility; role name is free (e.g. Company Read Only 1, 2, 3).
    """


@receiver(m2m_changed, sender=User.groups.through)
def enforce_account_group_membership(
    sender,
    instance: User,
    action: str,
    reverse: bool,
    pk_set,
    **kwargs,
) -> None:
    """
    Enforce that a User can only be assigned to Groups that belong to their Account.

    Invariants:
    - Every Group that is used by the application must be linked to exactly one
      Account via AccountGroup.
    - Users may only be assigned to Groups whose AccountGroup.account matches
      user.account.
    """
    if action not in {'pre_add', 'pre_set'} or not pk_set:
        return

    # Safety guard: we expect every user to have an account (enforced above),
    # but if for some reason it is missing, block group assignment.
    if not instance.account_id:
        raise ValidationError(
            'Cannot assign groups to a user without an account. '
            'Ensure user.account is set before managing group membership.'
        )

    # When reverse=True, "instance" is a Group and pk_set contains user IDs.
    # We only enforce the invariant when modifying a specific user's groups,
    # not when editing Group.user_set in bulk from other code paths.
    if reverse:
        return

    groups = Group.objects.filter(pk__in=pk_set).select_related('account_group')
    invalid_group_ids = []

    for group in groups:
        try:
            account_group = group.account_group
        except AccountGroup.DoesNotExist:
            invalid_group_ids.append(group.pk)
            continue

        if account_group.account_id != instance.account_id:
            invalid_group_ids.append(group.pk)

    if invalid_group_ids:
        raise ValidationError(
            'Cannot assign groups outside the user account or without tenant binding.'
        )


@receiver(m2m_changed, sender=User.groups.through)
def clear_permission_cache_on_group_membership_change(
    sender,
    instance: User,
    action: str,
    reverse: bool,
    pk_set,
    **kwargs,
) -> None:
    """
    Clear permission caches whenever a user's group membership changes.

    This ensures that user.has_perm() reflects the latest group assignments.
    """
    if action not in {'post_add', 'post_remove', 'post_clear'}:
        return

    if reverse:
        # In reverse mode, "instance" is a Group and pk_set are user IDs
        if not pk_set:
            return
        users = User.objects.filter(pk__in=pk_set)
        for user in users:
            _clear_user_permission_cache(user)
    else:
        _clear_user_permission_cache(instance)


@receiver(m2m_changed, sender=Group.permissions.through)
def enforce_company_read_only_after_permission_change(
    sender,
    instance: Group,
    action: str,
    reverse: bool,
    pk_set,
    **kwargs,
) -> None:
    """
    No-op: we do not strip or change permissions when a group's permissions
    are edited. Admin-selected permissions are preserved for all roles.
    """


@receiver(m2m_changed, sender=Group.permissions.through)
def clear_permission_cache_on_group_permission_change(
    sender,
    instance: Group,
    action: str,
    reverse: bool,
    pk_set,
    **kwargs,
) -> None:
    """
    Clear permission caches whenever permissions on a Group change.

    This ensures that all users who belong to the group see updated
    permissions immediately.
    """
    if action not in {'post_add', 'post_remove', 'post_clear'}:
        return

    # instance is a Group here; clear caches for all related users.
    users = instance.user_set.all()
    for user in users:
        _clear_user_permission_cache(user)


@receiver(m2m_changed, sender=Group.permissions.through)
def sync_company_admin_permissions_when_edited(
    sender,
    instance: Group,
    action: str,
    reverse: bool,
    pk_set,
    **kwargs,
) -> None:
    """
    When a Company Admin group's permissions are edited in Django admin,
    copy its permissions to every other account's Company Admin group so
    all Company Admins stay in sync.
    """
    if action not in {'post_add', 'post_remove', 'post_clear'}:
        return
    from .services import sync_company_admin_permissions_to_all_accounts
    sync_company_admin_permissions_to_all_accounts(instance)


@receiver(m2m_changed, sender=User.user_permissions.through)
def clear_permission_cache_on_user_permission_change(
    sender,
    instance: User,
    action: str,
    reverse: bool,
    pk_set,
    **kwargs,
) -> None:
    """Clear permission caches when a user's direct user_permissions change."""
    if action not in {'post_add', 'post_remove', 'post_clear'}:
        return
    if not reverse:
        _clear_user_permission_cache(instance)
    elif pk_set:
        for user in User.objects.filter(pk__in=pk_set):
            _clear_user_permission_cache(user)


# -----------------------------------------------------------------------------
# Activity logging: SubUser and role/permission changes (automatic, no manual calls)
# -----------------------------------------------------------------------------

@receiver(post_save, sender=SubUser)
def log_subuser_created_or_updated(sender, instance: SubUser, created: bool, **kwargs) -> None:
    """Log team member creation or update to security activity log."""
    if not getattr(instance, 'account_owner_id', None):
        return
    account = instance.account_owner.account if instance.account_owner_id else None
    if not account:
        return
    if created:
        UserActivity.log_activity(
            user=instance.account_owner,
            account=account,
            activity_type='CREATE',
            description=f"Team member added: {instance.full_name} ({instance.email})",
            app_name='accounts',
            model_name='SubUser',
            object_id=str(instance.pk),
            object_repr=f"{instance.full_name} ({instance.email})",
        )
    else:
        UserActivity.log_activity(
            user=instance.account_owner,
            account=account,
            activity_type='UPDATE',
            description=f"Team member updated: {instance.full_name} ({instance.email})",
            app_name='accounts',
            model_name='SubUser',
            object_id=str(instance.pk),
            object_repr=f"{instance.full_name} ({instance.email})",
        )


@receiver(post_delete, sender=SubUser)
def log_subuser_deleted(sender, instance: SubUser, **kwargs) -> None:
    """Log team member removal to security activity log."""
    if not getattr(instance, 'account_owner_id', None):
        return
    try:
        owner = instance.account_owner
        account = owner.account
    except ObjectDoesNotExist:
        # During cascade delete (e.g. Account deleted in admin), owner or account may already be gone.
        return
    if not account:
        return
    UserActivity.log_activity(
        user=owner,
        account=account,
        activity_type='DELETE',
        description=f"Team member removed: {instance.full_name} ({instance.email})",
        app_name='accounts',
        model_name='SubUser',
        object_id=str(instance.pk),
        object_repr=f"{instance.full_name} ({instance.email})",
    )


@receiver(post_delete, sender=SubUser)
def cleanup_subuser_group_membership(sender, instance: SubUser, **kwargs) -> None:
    """
    When a SubUser is removed: remove linked_user from ALL role groups for that account
    and clear Django permission cache. Prevents orphaned group memberships and stale
    role member display.
    """
    linked_user_id = getattr(instance, 'linked_user_id', None)
    account_owner_id = getattr(instance, 'account_owner_id', None)
    if not linked_user_id or not account_owner_id:
        return
    account_id = User.objects.filter(pk=account_owner_id).values_list('account_id', flat=True).first()
    if not account_id:
        return
    user = User.objects.filter(pk=linked_user_id).first()
    if not user:
        return
    from .services import remove_user_from_account_group
    for ag in AccountGroup.objects.filter(account_id=account_id).select_related('group'):
        remove_user_from_account_group(user, ag)
    _clear_user_permission_cache(user)


def _log_role_membership_change(user: User, action_label: str, group_names: list) -> None:
    if not user or not getattr(user, 'account_id', None):
        return
    names = ', '.join(group_names[:5]) if group_names else 'roles'
    if len(group_names) > 5:
        names += f' (+{len(group_names) - 5} more)'
    UserActivity.log_activity(
        user=user,
        account=user.account,
        activity_type='PERMISSION_CHANGE',
        description=f"Role membership changed for {user.get_full_name() or user.email}: {action_label} {names}",
        app_name='accounts',
        model_name='AccountGroup',
        object_repr=names,
    )


@receiver(m2m_changed, sender=User.groups.through)
def log_role_membership_activity(
    sender,
    instance,
    action: str,
    reverse: bool,
    pk_set,
    **kwargs,
) -> None:
    """Log role (group) membership changes to the activity log."""
    if action not in {'post_add', 'post_remove', 'post_clear'}:
        return
    if reverse:
        # instance is Group; pk_set are user IDs
        if not pk_set:
            return
        group = instance
        try:
            ag = group.account_group
            account = ag.account
        except AccountGroup.DoesNotExist:
            return
        users = User.objects.filter(pk__in=pk_set, account_id=account.id)
        role_name = ag.role_name or group.name or str(group.pk)
        for u in users:
            _log_role_membership_change(u, 'assigned to' if action == 'post_add' else 'removed from', [role_name])
    else:
        # instance is User
        user = instance
        if not getattr(user, 'account_id', None):
            return
        if not pk_set:
            if action == 'post_clear':
                _log_role_membership_change(user, 'cleared', [])
            return
        groups = Group.objects.filter(pk__in=pk_set).select_related('account_group')
        names = []
        for g in groups:
            try:
                if g.account_group.account_id == user.account_id:
                    names.append(g.account_group.role_name or g.name or str(g.pk))
            except AccountGroup.DoesNotExist:
                pass
        if names:
            _log_role_membership_change(
                user,
                'assigned to' if action == 'post_add' else 'removed from',
                names,
            )


@receiver(m2m_changed, sender=Group.permissions.through)
def log_group_permission_change(
    sender,
    instance: Group,
    action: str,
    reverse: bool,
    pk_set,
    **kwargs,
) -> None:
    """Log role (group) permission changes to the activity log."""
    if action not in {'post_add', 'post_remove', 'post_clear'}:
        return
    try:
        ag = instance.account_group
        account = ag.account
    except AccountGroup.DoesNotExist:
        return
    role_name = ag.role_name or instance.name or str(instance.pk)
    UserActivity.log_activity(
        user=None,
        account=account,
        activity_type='PERMISSION_CHANGE',
        description=f"Role permissions changed for role '{role_name}' ({action})",
        app_name='accounts',
        model_name='AccountGroup',
        object_id=str(instance.pk),
        object_repr=role_name,
    )

