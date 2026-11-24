# -*- coding: utf-8 -*-
"""
HR & Staff queryset helpers: tenant + visibility for Employee and LeaveRequest.

Visibility rules (mandatory data isolation; HR authority is EXPLICIT, not Full Company Visibility):
- Company admin: all records for the account.
- HR (explicit hr_staff.view_hr_dashboard): all records for the account. No created_by filtering.
- Employee (linked_employee, view_own_hr_dashboard): only their own Employee and LeaveRequests.
- Other team members: only records they created (created_by=user).

SECURITY: HR app ignores Full Company Visibility for authority. Having view_hr_dashboard
grants visibility to all employees in the account; full_company_visibility is not used here.
"""
from django.contrib.auth import get_user_model

from apps.core.ownership import (
    get_account_for_user,
    is_company_admin,
    for_user_queryset,
)

from .models import Department, Employee, LeaveRequest

User = get_user_model()


def _is_employee_portal_user(user):
    """True if user is linked to an Employee record (portal user). Cached per request on user."""
    if not user or not getattr(user, 'is_authenticated', True):
        return False
    cache_key = '_hr_is_employee_portal_user'
    if hasattr(user, cache_key):
        return getattr(user, cache_key)
    result = Employee.objects.filter(linked_user=user).exists()
    setattr(user, cache_key, result)
    return result


def get_employee_queryset_for_user(user, request=None, account_lookup='account'):
    """
    Return Employee queryset scoped to tenant and visibility.

    - Company admin: all employees in account.
    - HR (explicit view_hr_dashboard): all employees in account. No created_by filtering.
    - Employee portal user (linked_employee): only their own Employee record.
    - Other: only employees they created (created_by=user).
    """
    account = get_account_for_user(user)
    if account is None:
        return Employee.objects.none()
    qs = Employee.objects.filter(**{account_lookup: account}).filter(is_deleted=False)
    if is_company_admin(user, request):
        return qs
    if user.has_perm('hr_staff.view_hr_dashboard'):
        return qs
    if _is_employee_portal_user(user):
        return qs.filter(linked_user=user)
    return qs.filter(created_by=user)


def get_leave_queryset_for_user(user, request=None, account_lookup='account'):
    """
    Return LeaveRequest queryset scoped to tenant and visibility.

    - Company admin: all leave requests in account.
    - HR (explicit view_hr_dashboard): all leave requests in account.
    - Employee portal user: only leave requests for their linked Employee.
    - Other: only leave requests they created (created_by=user).
    """
    account = get_account_for_user(user)
    if account is None:
        return LeaveRequest.objects.none()
    qs = LeaveRequest.objects.filter(**{account_lookup: account})
    if is_company_admin(user, request):
        return qs
    if user.has_perm('hr_staff.view_hr_dashboard'):
        return qs
    if _is_employee_portal_user(user):
        return qs.filter(employee__linked_user=user)
    return qs.filter(created_by=user)


def get_linked_employee_for_user(user):
    """
    Return the Employee record linked to this user, or None.
    Use to show employee portal dashboard and restrict to self-only data.
    """
    if not user or not getattr(user, 'is_authenticated', True):
        return None
    try:
        return user.linked_employee
    except Employee.DoesNotExist:
        return None


def get_department_queryset_for_employee_form(user, request=None):
    """
    Return Department queryset for use in employee form (create/edit) and API dropdown.
    So that HR and employees (view_own_hr_dashboard) see all account departments and
    can select/change department; others still see only departments they created.
    """
    account = get_account_for_user(user)
    if account is None:
        return Department.objects.none()
    if is_company_admin(user, request):
        return Department.objects.filter(account=account).order_by('name')
    if user.has_perm('hr_staff.view_hr_dashboard'):
        return Department.objects.filter(account=account).order_by('name')
    if user.has_perm('hr_staff.view_own_hr_dashboard'):
        return Department.objects.filter(account=account).order_by('name')
    return for_user_queryset(
        Department, user, request, account_lookup='account'
    ).order_by('name')
