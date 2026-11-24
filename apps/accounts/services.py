from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from django.contrib.auth.models import Group, Permission
from django.db import transaction

from apps.core.models import Account
from .models import AccountGroup
from .default_role import (
    DEFAULT_ONBOARDING_ROLE_NAME,
    DEFAULT_ONBOARDING_PERMISSION_CODENAMES,
    COMPANY_ADMIN_ROLE_NAME,
)

# When syncing Company Admin permissions to all accounts, skip signal re-entry
_sync_company_admin_lock = threading.local()

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractUser
    User = AbstractUser
    UserType = AbstractUser
else:
    from django.contrib.auth import get_user_model
    User = get_user_model()
    UserType = User


def _build_group_name(account: Account, role_name: str) -> str:
    """
    Build a globally unique Group.name for a tenant-scoped role.

    We keep Group global but encode the tenant context in the name so it is
    clear and avoids collisions, while AccountGroup provides the real
    per-account scoping.
    """
    # Example: "acct-5:Billing Manager"
    return f"acct-{account.pk}:{role_name}"


def get_all_permission_codenames():
    """
    Return all permission codenames in the database as 'app_label.codename'.
    Use for Company Admin so they get every permission (all app features).
    """
    qs = Permission.objects.select_related('content_type').values_list(
        'content_type__app_label', 'codename'
    ).distinct()
    return [f"{app_label}.{codename}" for app_label, codename in qs]


def get_view_only_permission_codenames():
    """
    Return view_*, print_*, and download_* permission codenames as 'app_label.codename'.
    Used for Company Read Only role: view, download, and print only (no add/change/delete).
    """
    from django.db.models import Q
    qs = Permission.objects.filter(
        Q(codename__startswith='view_') |
        Q(codename__startswith='print_') |
        Q(codename__startswith='download_')
    ).select_related('content_type').values_list(
        'content_type__app_label', 'codename'
    ).distinct()
    return [f"{app_label}.{codename}" for app_label, codename in qs]


def filter_group_to_view_only_codenames(group: Group) -> list[str]:
    """
    Return permission codenames (app_label.codename) for the group that are
    view/print/download only. Used to strip add/change/delete from Company Read Only
    without replacing the user's selection with the full view-only list.
    """
    from django.db.models import Q
    qs = group.permissions.filter(
        Q(codename__startswith='view_') |
        Q(codename__startswith='print_') |
        Q(codename__startswith='download_')
    ).values_list('content_type__app_label', 'codename')
    return [f"{app_label}.{codename}" for app_label, codename in qs]


def _resolve_permissions(permission_codenames: list[str]):
    """
    Resolve a list of permission specs to Permission queryset.

    IMPORTANT: Always pass 'app_label.codename' (e.g. 'receipts.view_receipt').
    Codename-only specs (e.g. 'view_receipt') match ALL apps with that codename.
    Multiple apps share model names (job_orders.Receipt, receipts.Receipt, etc.)
    so codename-only would incorrectly add permissions from unintended apps.
    """
    pks = set()
    for spec in permission_codenames:
        if '.' in spec:
            app_label, codename = spec.split('.', 1)
            perms = Permission.objects.filter(
                content_type__app_label=app_label,
                codename=codename,
            )
        else:
            perms = Permission.objects.filter(codename=spec)
        pks.update(perms.values_list('pk', flat=True))
    return Permission.objects.filter(pk__in=pks) if pks else Permission.objects.none()


@transaction.atomic
def create_account_group(account: Account, role_name: str, permission_codenames: list[str] | None = None) -> AccountGroup:
    """
    Create a new AccountGroup + underlying Django Group for a specific account.

    - Ensures (account, role_name) uniqueness via AccountGroup's Meta.
    - Attaches the requested Permission objects to the Group.
    - permission_codenames should be 'app_label.codename' (see _resolve_permissions).
    - If a Group with the same name already exists (e.g. orphan or duplicate submit),
      reuses it and returns or creates the matching AccountGroup instead of raising.

    DEPENDENCY NOTE: We do NOT auto-add permissions. If a feature depends on another
    (e.g. viewing receipts may require job order context), enforce that at the VIEW
    or FEATURE level (e.g. check has_perm in the view), not by auto-adding extra
    permissions to the role.
    """
    if permission_codenames is None:
        permission_codenames = []

    group_name = _build_group_name(account, role_name)
    group, group_created = Group.objects.get_or_create(name=group_name)

    if permission_codenames:
        perms = _resolve_permissions(permission_codenames)
        group.permissions.set(perms)

    # If Group already existed, an AccountGroup for this account may already exist (e.g. same role)
    existing_ag = AccountGroup.objects.filter(account=account, group=group).first()
    if existing_ag:
        return existing_ag

    # Orphan group (Group exists but no AccountGroup for this account): link it
    if not group_created:
        account_group = AccountGroup.objects.create(
            account=account,
            group=group,
            role_name=role_name,
        )
        return account_group

    account_group = AccountGroup.objects.create(
        account=account,
        group=group,
        role_name=role_name,
    )
    return account_group


@transaction.atomic
def update_account_group_permissions(account_group: AccountGroup, permission_codenames: list[str]) -> None:
    """
    Replace the permissions attached to an AccountGroup's underlying Group.

    Saved permissions == submitted permissions. Unchecked permissions are removed.
    No implicit or derived permissions are added.
    Permission caches are cleared by signals on Group.permissions.m2m.
    """
    perms = _resolve_permissions(permission_codenames)
    account_group.group.permissions.set(perms)


def sync_company_admin_permissions_to_all_accounts(source_group: Group) -> None:
    """
    When a Company Admin group's permissions are edited in Django admin, copy its
    permissions to every other account's Company Admin group so all Company Admins
    stay in sync. Source group must be the Group linked to an AccountGroup with
    role_name=COMPANY_ADMIN_ROLE_NAME.
    """
    if getattr(_sync_company_admin_lock, 'active', False):
        return
    try:
        _sync_company_admin_lock.active = True
        try:
            source_ag = source_group.account_group
        except AccountGroup.DoesNotExist:
            return
        if source_ag.role_name != COMPANY_ADMIN_ROLE_NAME:
            return
        perm_ids = set(source_group.permissions.values_list('pk', flat=True))
        other_company_admins = AccountGroup.objects.filter(
            role_name=COMPANY_ADMIN_ROLE_NAME,
        ).exclude(group_id=source_group.pk).select_related('group')
        for ag in other_company_admins:
            ag.group.permissions.set(perm_ids)
    finally:
        _sync_company_admin_lock.active = False


@transaction.atomic
def assign_user_to_account_group(user: UserType, account_group: AccountGroup) -> None:
    """
    Add a user to an AccountGroup's underlying Group, enforcing tenant match.
    Clears the user's permission cache so the next request (or same-request checks)
    sees the new role permissions (e.g. HR role seeing full HR dashboard).

    Invariants:
    - user.account == account_group.account
    """
    if user.account_id != account_group.account_id:
        raise ValueError("Cannot assign user to a role outside their account.")
    user.groups.add(account_group.group)
    _clear_user_permission_cache(user)


@transaction.atomic
def remove_user_from_account_group(user: UserType, account_group: AccountGroup) -> None:
    """
    Remove a user from an AccountGroup's underlying Group.
    """
    user.groups.remove(account_group.group)


@transaction.atomic
def remove_group_from_all_users_and_delete(account_group: AccountGroup) -> None:
    """
    When an AccountGroup (role) is deleted: remove its Group from all users,
    clear permission caches, then delete AccountGroup and the Group.
    Prevents deleted roles from still appearing in Add Team Member dropdown
    and prevents orphaned Groups.
    """
    group = account_group.group
    user_ids = list(group.user_set.values_list('pk', flat=True))
    for user_id in user_ids:
        try:
            user = User.objects.get(pk=user_id)
            user.groups.remove(group)
            _clear_user_permission_cache(user)
        except User.DoesNotExist:
            pass
    account_group.delete()
    group.delete()


def _clear_user_permission_cache(user: UserType) -> None:
    """
    Clear Django's internal permission caches so has_perm() reflects latest
    group membership. Called after role changes to fix 403 for team members.
    """
    for attr in ('_perm_cache', '_group_perm_cache', '_obj_perm_cache'):
        if hasattr(user, attr):
            delattr(user, attr)


@transaction.atomic
def set_user_account_role(user: UserType, account_group: AccountGroup | None) -> None:
    """
    Set a user's single role within their account: remove all account groups
    for user.account, then add the given AccountGroup if provided.

    Invariants:
    - user.account == account_group.account when account_group is not None
    - When account_group is None, only clears account groups (no role).

    Always clears permission cache after group changes so has_perm() reflects
    the new role immediately (belt-and-suspenders with m2m_changed signals).
    """
    from .models import AccountGroup as AG

    account_id = user.account_id
    if not account_id:
        return
    group_ids = list(AG.objects.filter(account_id=account_id).values_list('group_id', flat=True))
    if group_ids:
        for g in user.groups.filter(pk__in=group_ids):
            user.groups.remove(g)
    if account_group:
        if account_group.account_id != account_id:
            raise ValueError("Cannot assign user to a role outside their account.")
        user.groups.add(account_group.group)
    _clear_user_permission_cache(user)


def get_or_create_default_onboarding_role(account: Account) -> AccountGroup:
    """
    Get or create the default onboarding role (Company Profile Viewer) for an account.

    This role has only minimal permissions: view company profile. Used for all newly
    registered users until a superuser assigns an elevated role. Safe to call on
    every new account; idempotent for a given account.
    """
    from django.db import IntegrityError

    ag = AccountGroup.objects.filter(
        account=account,
        role_name=DEFAULT_ONBOARDING_ROLE_NAME,
    ).select_related("group").first()
    if ag:
        perms = _resolve_permissions(DEFAULT_ONBOARDING_PERMISSION_CODENAMES)
        if set(ag.group.permissions.values_list("pk", flat=True)) != set(perms.values_list("pk", flat=True)):
            ag.group.permissions.set(perms)
        return ag

    group_name = _build_group_name(account, DEFAULT_ONBOARDING_ROLE_NAME)
    try:
        with transaction.atomic():
            group = Group.objects.create(name=group_name)
            ag = AccountGroup.objects.create(
                account=account,
                group=group,
                role_name=DEFAULT_ONBOARDING_ROLE_NAME,
            )
    except IntegrityError:
        ag = AccountGroup.objects.get(account=account, role_name=DEFAULT_ONBOARDING_ROLE_NAME)

    perms = _resolve_permissions(DEFAULT_ONBOARDING_PERMISSION_CODENAMES)
    if set(ag.group.permissions.values_list("pk", flat=True)) != set(perms.values_list("pk", flat=True)):
        ag.group.permissions.set(perms)
    return ag


def assign_new_user_to_default_role(user: UserType) -> None:
    """
    Assign a user to the default onboarding role (Company Profile Viewer) only.

    Call this for every newly registered user so they start with minimal access.
    Requires user.account to be set. Does not add any other groups.
    """
    if not user.account_id:
        return
    default_ag = get_or_create_default_onboarding_role(user.account)
    assign_user_to_account_group(user, default_ag)


def ensure_new_user_has_account_and_default_role(user: UserType) -> None:
    """
    Ensure a newly registered user has an account and the Company Profile Viewer role.

    Call from registration views after form.save() so that even if the post_save signal
    was skipped or failed, the user gets an account and the default role. Idempotent.
    """
    user.refresh_from_db()
    if user.account_id:
        assign_new_user_to_default_role(user)
        return
    account_name = user.get_full_name() or user.email or ''
    account = Account.objects.filter(owner=user).first()
    if not account:
        with transaction.atomic():
            account = Account.objects.create(owner=user, name=account_name)
    else:
        if account.name != account_name:
            account.name = account_name
            account.save(update_fields=['name'])
    User.objects.filter(pk=user.pk).update(account_id=account.id)
    user.account_id = account.id
    user.account = account
    assign_new_user_to_default_role(user)


def sync_requisition_permissions_to_company_admin() -> int:
    """
    Reusable: add ALL requisition permissions to every Company Admin group.
    Call after requisitions migrations or via management command.
    Returns the number of Company Admin groups updated.
    """
    try:
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType
        from apps.requisitions.models import Requisition
    except ImportError:
        return 0
    try:
        content_type = ContentType.objects.get_for_model(Requisition)
    except Exception:
        return 0
    requisition_perm_pks = set(
        Permission.objects.filter(content_type=content_type).values_list('pk', flat=True)
    )
    if not requisition_perm_pks:
        return 0
    updated = 0
    for ag in AccountGroup.objects.filter(role_name=COMPANY_ADMIN_ROLE_NAME).select_related('group'):
        if not ag.group_id:
            continue
        existing = set(ag.group.permissions.values_list('pk', flat=True))
        to_add = requisition_perm_pks - existing
        if to_add:
            ag.group.permissions.add(*to_add)
            updated += 1
    return updated


def sync_staff_offence_permissions_to_company_admin() -> int:
    """
    Add ALL staff offence register + entry permissions to every Company Admin group.
    """
    try:
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType
        from apps.staff_offences.models import StaffOffenceRegister, StaffOffenceEntry
    except ImportError:
        return 0
    perm_pks = set()
    for model in (StaffOffenceRegister, StaffOffenceEntry):
        try:
            ct = ContentType.objects.get_for_model(model)
        except Exception:
            continue
        perm_pks.update(
            Permission.objects.filter(content_type=ct).values_list('pk', flat=True)
        )
    if not perm_pks:
        return 0
    updated = 0
    for ag in AccountGroup.objects.filter(role_name=COMPANY_ADMIN_ROLE_NAME).select_related('group'):
        if not ag.group_id:
            continue
        existing = set(ag.group.permissions.values_list('pk', flat=True))
        to_add = perm_pks - existing
        if to_add:
            ag.group.permissions.add(*to_add)
            updated += 1
    return updated


def sync_inventory_permissions_to_company_admin() -> int:
    """
    Add ALL inventory permissions to every Company Admin group.
    Call after inventory migrations or via management command.
    Returns the number of Company Admin groups updated.
    """
    try:
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType
        from apps.inventory.models import Inventory
    except ImportError:
        return 0
    try:
        content_type = ContentType.objects.get_for_model(Inventory)
    except Exception:
        return 0
    inventory_perm_pks = set(
        Permission.objects.filter(content_type=content_type).values_list('pk', flat=True)
    )
    if not inventory_perm_pks:
        return 0
    updated = 0
    for ag in AccountGroup.objects.filter(role_name=COMPANY_ADMIN_ROLE_NAME).select_related('group'):
        if not ag.group_id:
            continue
        existing = set(ag.group.permissions.values_list('pk', flat=True))
        to_add = inventory_perm_pks - existing
        if to_add:
            ag.group.permissions.add(*to_add)
            updated += 1
    return updated


def sync_store_permissions_to_company_admin() -> int:
    """
    Add ALL store permissions to every Company Admin group.
    Call after store migrations or via management command.
    Returns the number of Company Admin groups updated.
    """
    try:
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType
        from apps.store.models import (
            Store, WasteLog, StoreCategory, StoreCustomField,
            StoreCustomForm, StoreLayout,
        )
    except ImportError:
        return 0
    models = (Store, StoreCategory, StoreCustomField, StoreCustomForm, StoreLayout)
    store_perm_pks = set()
    for model in models:
        try:
            ct = ContentType.objects.get_for_model(model)
            store_perm_pks.update(
                Permission.objects.filter(content_type=ct).values_list('pk', flat=True)
            )
        except Exception:
            pass
    if not store_perm_pks:
        return 0
    updated = 0
    for ag in AccountGroup.objects.filter(role_name=COMPANY_ADMIN_ROLE_NAME).select_related('group'):
        if not ag.group_id:
            continue
        existing = set(ag.group.permissions.values_list('pk', flat=True))
        to_add = store_perm_pks - existing
        if to_add:
            ag.group.permissions.add(*to_add)
            updated += 1
    return updated


def sync_expense_permissions_to_company_admin() -> int:
    """
    Add ALL expense permissions to every Company Admin group.
    Call after expense migrations or via management command.
    Returns the number of Company Admin groups updated.
    """
    try:
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType
        from apps.expense.models import Expense
    except ImportError:
        return 0
    try:
        content_type = ContentType.objects.get_for_model(Expense)
    except Exception:
        return 0
    expense_perm_pks = set(
        Permission.objects.filter(content_type=content_type).values_list('pk', flat=True)
    )
    if not expense_perm_pks:
        return 0
    updated = 0
    for ag in AccountGroup.objects.filter(role_name=COMPANY_ADMIN_ROLE_NAME).select_related('group'):
        if not ag.group_id:
            continue
        existing = set(ag.group.permissions.values_list('pk', flat=True))
        to_add = expense_perm_pks - existing
        if to_add:
            ag.group.permissions.add(*to_add)
            updated += 1
    return updated


def sync_hr_staff_permissions_to_company_admin() -> int:
    """
    Add ALL HR & Staff permissions (Department, Employee, LeaveRequest) to every
    Company Admin group. Call after hr_staff migrations or when account is approved.
    Returns the number of Company Admin groups updated.
    """
    try:
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType
        from apps.hr_staff.models import Department, Employee, LeaveRequest
    except ImportError:
        return 0
    hr_perm_pks = set()
    for model in (Department, Employee, LeaveRequest):
        try:
            ct = ContentType.objects.get_for_model(model)
            hr_perm_pks.update(
                Permission.objects.filter(content_type=ct).values_list('pk', flat=True)
            )
        except Exception:
            continue
    if not hr_perm_pks:
        return 0
    updated = 0
    for ag in AccountGroup.objects.filter(role_name=COMPANY_ADMIN_ROLE_NAME).select_related('group'):
        if not ag.group_id:
            continue
        existing = set(ag.group.permissions.values_list('pk', flat=True))
        to_add = hr_perm_pks - existing
        if to_add:
            ag.group.permissions.add(*to_add)
            updated += 1
    return updated


def sync_mailing_permissions_to_company_admin() -> int:
    """
    Add mailing permissions (e.g. use_bulk_mailing) to every Company Admin group.
    Call after mailing migrations or when account is approved.
    Returns the number of Company Admin groups updated.
    """
    try:
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType
        from apps.mailing.models import BulkSendLog
    except ImportError:
        return 0
    try:
        content_type = ContentType.objects.get_for_model(BulkSendLog)
    except Exception:
        return 0
    mailing_perm_pks = set(
        Permission.objects.filter(content_type=content_type).values_list('pk', flat=True)
    )
    if not mailing_perm_pks:
        return 0
    updated = 0
    for ag in AccountGroup.objects.filter(role_name=COMPANY_ADMIN_ROLE_NAME).select_related('group'):
        if not ag.group_id:
            continue
        existing = set(ag.group.permissions.values_list('pk', flat=True))
        to_add = mailing_perm_pks - existing
        if to_add:
            ag.group.permissions.add(*to_add)
            updated += 1
    return updated


def sync_invoice_movement_permissions_to_company_admin() -> int:
    """
    Add InvoiceMovement permissions to every Company Admin group.
    Returns the number of Company Admin groups updated.
    """
    try:
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType
        from apps.invoices.models import InvoiceMovement
    except ImportError:
        return 0
    try:
        content_type = ContentType.objects.get_for_model(InvoiceMovement)
    except Exception:
        return 0
    movement_perm_pks = set(
        Permission.objects.filter(content_type=content_type).values_list('pk', flat=True)
    )
    if not movement_perm_pks:
        return 0
    updated = 0
    for ag in AccountGroup.objects.filter(role_name=COMPANY_ADMIN_ROLE_NAME).select_related('group'):
        if not ag.group_id:
            continue
        existing = set(ag.group.permissions.values_list('pk', flat=True))
        to_add = movement_perm_pks - existing
        if to_add:
            ag.group.permissions.add(*to_add)
            updated += 1
    return updated


def sync_videocalls_permissions_to_company_admin() -> int:
    """
    Add Video Calls & Recordings permissions to every Company Admin group.
    Call after videocalls migrations or when account is approved.
    Returns the number of Company Admin groups updated.
    """
    try:
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType
        from apps.videocalls.models import VideoCallRoom, CallRecording, ScheduledMeeting, JitsiRoom
    except ImportError:
        return 0
    video_perm_pks = set()
    for model in (VideoCallRoom, CallRecording, ScheduledMeeting, JitsiRoom):
        try:
            ct = ContentType.objects.get_for_model(model)
            video_perm_pks.update(
                Permission.objects.filter(content_type=ct).values_list('pk', flat=True)
            )
        except Exception:
            continue
    if not video_perm_pks:
        return 0
    updated = 0
    for ag in AccountGroup.objects.filter(role_name=COMPANY_ADMIN_ROLE_NAME).select_related('group'):
        if not ag.group_id:
            continue
        existing = set(ag.group.permissions.values_list('pk', flat=True))
        to_add = video_perm_pks - existing
        if to_add:
            ag.group.permissions.add(*to_add)
            updated += 1
    return updated


def get_or_create_company_admin_group(account: Account) -> AccountGroup:
    """
    Get or create the Company Admin group for an account with ALL permissions
    (including requisitions and any future apps). Idempotent.
    """
    ag = AccountGroup.objects.filter(
        account=account,
        role_name=COMPANY_ADMIN_ROLE_NAME,
    ).select_related('group').first()
    all_codenames = get_all_permission_codenames()
    auth_extra = ['auth.view_group', 'auth.add_group', 'auth.change_group', 'auth.delete_group']
    for c in auth_extra:
        if c not in all_codenames:
            all_codenames.append(c)
    if ag:
        current = set(ag.group.permissions.values_list('pk', flat=True))
        target = set(_resolve_permissions(all_codenames).values_list('pk', flat=True))
        if current != target:
            update_account_group_permissions(ag, all_codenames)
        return ag
    return create_account_group(
        account=account,
        role_name=COMPANY_ADMIN_ROLE_NAME,
        permission_codenames=all_codenames,
    )


def ensure_subuser_linked_user(sub_user) -> UserType:
    """
    Ensure the SubUser has a linked Django User for permission/group membership.
    If linked_user is missing, create one in the same account and link it.
    The new User gets the same password hash as the SubUser so login continues to work.
    Returns the linked User (existing or newly created).
    """
    if sub_user.linked_user_id:
        return sub_user.linked_user
    account = sub_user.account_owner.account
    if not account or not getattr(account, 'pk', None):
        raise ValueError("SubUser's account owner has no account.")
    parts = (sub_user.full_name or '').strip().split(None, 1)
    first_name = (parts[0] if parts else sub_user.email)[:30]
    last_name = (parts[1] if len(parts) > 1 else sub_user.email)[:30]
    with transaction.atomic():
        user = User(
            account=account,
            email=sub_user.email,
            first_name=first_name,
            last_name=last_name,
            is_active=sub_user.is_active,
            is_staff=False,
        )
        user.password = sub_user.password_hash  # same hash so same password works at login
        user.save()
        sub_user.linked_user = user
        sub_user.save(update_fields=['linked_user'])
    return user

