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
    drf_filter_queryset_for_user,
)

from .models import (
    Department, Employee, LeaveRequest, LeavePolicy, Attendance,
    PerformanceReview, PerformanceGoal, PerformanceEvaluation,
    TrainingCourse, TrainingEnrollment, EmployeeDocument
)

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


def _is_hr_user(user, request=None):
    """True if user is company admin or has HR dashboard permission."""
    if is_company_admin(user, request):
        return True
    if user.has_perm('hr_staff.view_hr_dashboard'):
        return True
    return False


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


def get_attendance_queryset_for_user(user, request=None, account_lookup='account'):
    """
    Return Attendance queryset scoped to tenant and visibility.

    - Company admin: all attendance records in account.
    - HR: all attendance records in account.
    - Employee portal user: only their own attendance.
    - Other: only records they created (created_by=user).
    """
    account = get_account_for_user(user)
    if account is None:
        return Attendance.objects.none()
    qs = Attendance.objects.filter(**{account_lookup: account})
    if is_company_admin(user, request):
        return qs
    if user.has_perm('hr_staff.view_hr_dashboard'):
        return qs
    if _is_employee_portal_user(user):
        emp = get_linked_employee_for_user(user)
        if emp:
            return qs.filter(employee=emp)
        return Attendance.objects.none()
    return qs.filter(created_by=user)


def get_performance_review_queryset_for_user(user, request=None, account_lookup='account'):
    """Return PerformanceReview queryset with visibility."""
    return drf_filter_queryset_for_user(
        PerformanceReview.objects.all(), request, account_lookup=account_lookup
    )


def get_performance_goal_queryset_for_user(user, request=None, account_lookup='account'):
    """Return PerformanceGoal queryset with visibility."""
    account = get_account_for_user(user)
    if account is None:
        return PerformanceGoal.objects.none()
    qs = PerformanceGoal.objects.filter(**{account_lookup: account})
    if is_company_admin(user, request):
        return qs
    if user.has_perm('hr_staff.view_hr_dashboard'):
        return qs
    if _is_employee_portal_user(user):
        emp = get_linked_employee_for_user(user)
        if emp:
            return qs.filter(employee=emp)
        return PerformanceGoal.objects.none()
    return qs.filter(created_by=user)


def get_training_course_queryset_for_user(user, request=None, account_lookup='account'):
    """Return TrainingCourse queryset with visibility."""
    return drf_filter_queryset_for_user(
        TrainingCourse.objects.all(), request, account_lookup=account_lookup
    )


def get_training_enrollment_queryset_for_user(user, request=None, account_lookup='account'):
    """Return TrainingEnrollment queryset with visibility."""
    account = get_account_for_user(user)
    if account is None:
        return TrainingEnrollment.objects.none()
    qs = TrainingEnrollment.objects.filter(**{account_lookup: account})
    if is_company_admin(user, request):
        return qs
    if user.has_perm('hr_staff.view_hr_dashboard'):
        return qs
    if _is_employee_portal_user(user):
        emp = get_linked_employee_for_user(user)
        if emp:
            return qs.filter(employee=emp)
        return TrainingEnrollment.objects.none()
    return qs.filter(created_by=user)


def get_employee_document_queryset_for_user(user, request=None, account_lookup='account'):
    """Return EmployeeDocument queryset with visibility."""
    from django.db.models import Q
    account = get_account_for_user(user)
    if account is None:
        return EmployeeDocument.objects.none()
    # Show documents in user's account OR created by user (in case account wasn't set)
    qs = EmployeeDocument.objects.filter(
        Q(**{account_lookup: account}) | Q(created_by=user)
    ).distinct()
    if is_company_admin(user, request):
        return qs
    if user.has_perm('hr_staff.view_hr_dashboard'):
        return qs
    # Users who can add documents should also see all documents
    if user.has_perm('hr_staff.add_employee'):
        return qs
    if _is_employee_portal_user(user):
        emp = get_linked_employee_for_user(user)
        if emp:
            return qs.filter(employee=emp)
        return EmployeeDocument.objects.none()
    return qs.filter(created_by=user)


def get_leave_policy_queryset_for_user(user, request=None, account_lookup='account'):
    """Return LeavePolicy queryset with visibility."""
    return drf_filter_queryset_for_user(
        LeavePolicy.objects.all(), request, account_lookup=account_lookup
    )
