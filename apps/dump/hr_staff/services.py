# -*- coding: utf-8 -*-
"""
HR employee account services: create portal user, reset password, get/create Employee role.

Security:
- HR cannot assign permissions outside HR scope (enforced by permission_boundaries in role form).
- HR cannot edit Account or CompanyProfile; cannot delete User directly.
- Employee role has full_company_visibility=False so employees see only their own data via querysets.
"""
import secrets
import string
from django.contrib.auth import get_user_model
from django.db import transaction

from apps.core.models import Account
from apps.accounts.models import AccountGroup
from apps.accounts.services import (
    create_account_group,
    assign_user_to_account_group,
    set_user_account_role,
)

from .models import Employee

User = get_user_model()

# Role name for employees with portal access. full_company_visibility=False.
EMPLOYEE_ROLE_NAME = 'Employee'

# Permissions for Employee role: view own HR dashboard (portal), view/edit own profile, view/create own leave. No HR-only perms.
EMPLOYEE_ROLE_PERMISSION_CODENAMES = [
    'hr_staff.view_own_hr_dashboard',  # so employee can open HR & Staff and see their dashboard (My Profile, My Leave)
    'hr_staff.view_department',   # e.g. show department name on profile
    'hr_staff.view_employee',
    'hr_staff.change_employee',
    'hr_staff.view_leaverequest',
    'hr_staff.add_leaverequest',
    'core.view_companyprofile',
]


def get_or_create_employee_role(account: Account) -> AccountGroup:
    """
    Get or create the "Employee" role for an account.
    full_company_visibility=False so visibility is enforced by queryset (self-only).
    Ensures view_own_hr_dashboard is on the role so employees can access the portal.
    """
    ag = AccountGroup.objects.filter(
        account=account,
        role_name=EMPLOYEE_ROLE_NAME,
    ).select_related('group').first()
    if ag:
        # Ensure Employee role has view_own_hr_dashboard (for existing roles created before we added it)
        from apps.accounts.services import update_account_group_permissions
        existing = set(ag.group.permissions.values_list('content_type__app_label', 'codename'))
        if ('hr_staff', 'view_own_hr_dashboard') not in existing:
            current = [f"{p.content_type.app_label}.{p.codename}" for p in ag.group.permissions.all()]
            merged = set(current) | set(EMPLOYEE_ROLE_PERMISSION_CODENAMES)
            update_account_group_permissions(ag, list(merged))
        return ag
    return create_account_group(
        account=account,
        role_name=EMPLOYEE_ROLE_NAME,
        permission_codenames=EMPLOYEE_ROLE_PERMISSION_CODENAMES,
    )


def _generate_temporary_password(length=12):
    """Generate a secure temporary password (letters + digits)."""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


@transaction.atomic
def create_employee_portal_user(
    employee: Employee,
    temporary_password: str | None = None,
) -> tuple[User, str]:
    """
    Create a Django User for the employee and link it.

    - User email from employee.email (must be unique and not empty).
    - User account = employee.account.
    - Assigns Employee role (full_company_visibility=False).
    - Sets employee.linked_user, employee.is_portal_user = True.
    - Returns (user, password). If temporary_password is None, generates one; caller must show/send it once (HR never sees it again).

    Raises ValueError if employee already has linked_user or email is missing/duplicate.
    """
    if employee.linked_user_id:
        raise ValueError('Employee already has portal access.')
    email = (employee.email or '').strip()
    if not email:
        raise ValueError('Employee must have an email to create portal access.')
    if User.objects.filter(email__iexact=email).exists():
        raise ValueError('A user with this email already exists.')
    account = employee.account
    if not account:
        raise ValueError('Employee must belong to an account.')
    password = temporary_password or _generate_temporary_password()
    user = User.objects.create_user(
        email=email,
        password=password,
        first_name=employee.first_name or '',
        last_name=employee.last_name or '',
        account=account,
        is_staff=False,
        is_active=True,
    )
    user.force_password_change = True  # Force change on first login; never reveal temp password again.
    user.save(update_fields=['force_password_change'])
    employee_role = get_or_create_employee_role(account)
    set_user_account_role(user, employee_role)
    employee.linked_user = user
    employee.is_portal_user = True
    employee.portal_created_by_hr = True  # HR created this account; HR may reset password
    employee.save(update_fields=['linked_user', 'is_portal_user', 'portal_created_by_hr'])
    return user, password


def reset_employee_password(employee: Employee, new_password: str | None = None) -> str:
    """
    Reset the linked User's password. If new_password is None, generates a temporary one.
    Returns the new password (caller shows/sends once; HR never sees it after).

    Raises ValueError if employee has no linked_user.
    """
    if not employee.linked_user_id:
        raise ValueError('Employee does not have portal access.')
    user = employee.linked_user
    password = new_password or _generate_temporary_password()
    user.set_password(password)
    user.save(update_fields=['password'])
    return password


def set_employee_account_active(employee: Employee, active: bool) -> None:
    """Enable or disable the linked User's login (is_active). No-op if no linked_user."""
    if not employee.linked_user_id:
        return
    User.objects.filter(pk=employee.linked_user_id).update(is_active=active)
