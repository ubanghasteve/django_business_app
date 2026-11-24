# -*- coding: utf-8 -*-
"""
HR & Staff views: dashboard, employees, departments, leave requests.
All querysets scoped via for_user_queryset(..., request.user, request, account_lookup='account').

SECURITY (visibility vs authority):
- full_company_visibility grants READ only; it does NOT grant create_employee_account,
  reset_employee_password, or view_employee_activity. Those require explicit permission checks.
- Views that create User objects require hr_staff.create_employee_account (guarded in employee_create).
- Password reset requires hr_staff.reset_employee_password (decorator on employee_reset_password).
- HR cannot edit account owner; account-owner checks and audit logging are applied where relevant.
"""
import logging
from django.shortcuts import render, redirect, get_object_or_404

logger = logging.getLogger(__name__)
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from django.db.models import Count, Q, Prefetch

from business_app.views import get_object_or_unauthorized
from apps.core.permissions import company_admin_or_permission_required, company_admin_or_any_permission_required
from apps.core.ownership import for_user_queryset, get_account_for_user, is_company_admin
from apps.core.utils import get_company_profile_for_user, apply_no_cache_headers

from django.contrib.auth import get_user_model
from .models import Employee, Department, LeaveRequest

User = get_user_model()
from .forms import DepartmentForm, EmployeeForm, LeaveRequestForm, EmployeeDocumentForm, get_account_users_without_employee
from .querysets import (
    get_employee_queryset_for_user,
    get_leave_queryset_for_user,
    get_linked_employee_for_user,
    get_department_queryset_for_employee_form,
    get_attendance_queryset_for_user,
    get_performance_review_queryset_for_user,
    get_training_course_queryset_for_user,
)
from . import services as hr_services


def _get_account_owner_id(request):
    """Return account.owner_id for the current user's account, or None."""
    account = get_account_for_user(request.user)
    if not account:
        return None
    return getattr(account, 'owner_id', None)


def _employee_is_account_owner(employee, account_owner_id):
    """True if this employee's linked user is the account owner (cannot be reset/disabled by HR)."""
    if not account_owner_id or not employee or not getattr(employee, 'linked_user_id', None):
        return False
    return employee.linked_user_id == account_owner_id


def _get_company_currency_symbol(request):
    """
    Return the current company's currency symbol for this request.
    Always reads from the active company profile so that when the
    Company Profile currency is updated, HR & Staff screens pick
    up the new symbol on the next request/poll.
    """
    company = getattr(request, 'company', None) or get_company_profile_for_user(
        request.user, request
    )
    return getattr(company, 'currency_symbol', '$') if company else '$'


def _log_hr_audit(request, activity_type, description, app_name='hr_staff', model_name='', object_id='', object_repr='', object_url='', extra_data=None):
    """Log an HR/employee action to UserActivity for audit. Actor = request.user."""
    from apps.accounts.models import UserActivity
    account = get_account_for_user(request.user)
    UserActivity.log_activity(
        user=request.user,
        account=account,
        activity_type=activity_type,
        description=description,
        app_name=app_name,
        model_name=model_name,
        object_id=str(object_id) if object_id else '',
        object_repr=object_repr,
        url_path=object_url or (request.build_absolute_uri() if request else ''),
        http_method=request.method if request else '',
        ip_address=(request.META.get('HTTP_X_FORWARDED_FOR') or request.META.get('REMOTE_ADDR')) if request else None,
        extra_data=extra_data or {},
    )


def _notify_employee_leave_status(leave_req, status_val, request):
    """Log activity for the employee's linked user and send email notification."""
    emp = leave_req.employee
    if not emp:
        return
    
    # Log activity for dashboard notification
    if emp.linked_user_id:
        from apps.accounts.models import UserActivity
        from django.utils import timezone
        base_url = request.build_absolute_uri('/') if request else None
        base_url = base_url.rstrip('/') if base_url else None
        UserActivity.log_activity(
            user=emp.linked_user,
            account=leave_req.account,
            activity_type='UPDATE',
            description=f'Your leave request ({leave_req.start_date}–{leave_req.end_date}) was {status_val}.',
            app_name='hr_staff',
            model_name='LeaveRequest',
            object_id=str(leave_req.pk),
            object_repr=str(leave_req),
            url_path=request.build_absolute_uri(f'/hr-staff/leave/{leave_req.pk}/') if request else None,
            http_method=request.method if request else None,
            ip_address=(request.META.get('HTTP_X_FORWARDED_FOR') or request.META.get('REMOTE_ADDR')) if request else None,
        )
    
    # Send email notification
    try:
        from .services import notify_leave_status
        base_url = None
        if request:
            base_url = request.build_absolute_uri('/')
            if base_url:
                base_url = base_url.rstrip('/')
        notify_leave_status(leave_req, status_val, base_url)
    except Exception:
        pass  # Email is optional; don't fail if email fails


# ----- Dashboard -----

@login_required
@never_cache
def dashboard(request):
    """
    HR & Staff dashboard: metrics, recent employees, leave requests, department overview.
    Access requires company admin, view_hr_dashboard (HR), or view_own_hr_dashboard (Employee). No Full Company Visibility.
    If user has only view_own_hr_dashboard, redirect to employee portal dashboard.
    """
    from apps.core.ownership import is_company_admin
    if not (is_company_admin(request.user, request) or request.user.has_perm('hr_staff.view_hr_dashboard') or request.user.has_perm('hr_staff.view_own_hr_dashboard')):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied('You do not have access to HR & Staff.')
    if request.user.has_perm('hr_staff.view_own_hr_dashboard') and not request.user.has_perm('hr_staff.view_hr_dashboard'):
        linked = get_linked_employee_for_user(request.user)
        if linked:
            return redirect('hr_staff:employee_portal_dashboard')
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied('You need an employee profile to access the employee dashboard.')
    # Shell-first: minimal data; dashboard-widgets API fills stats/lists via JS for instant load.
    currency_symbol = _get_company_currency_symbol(request)
    context = {
        'total_employees': 0,
        'active_employees': 0,
        'total_departments': 0,
        'pending_leaves': 0,
        'recent_employees': [],
        'leave_requests': [],
        'departments_overview': [],
        'user_currency_symbol': currency_symbol,
        'hr_current_page': 'dashboard',
        'is_employee_portal': False,
        'load_async': True,
    }
    response = render(request, 'hr_staff/dashboard.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.view_employee', raise_exception=True)
@require_GET
@never_cache
def dashboard_stats_json(request):
    """JSON endpoint for dashboard metric cards."""
    employees_qs = get_employee_queryset_for_user(
        request.user, request, account_lookup='account'
    )
    departments_qs = for_user_queryset(
        Department, request.user, request, account_lookup='account'
    )
    leaves_qs = get_leave_queryset_for_user(
        request.user, request, account_lookup='account'
    )
    data = {
        'total_employees': employees_qs.count(),
        'active_employees': employees_qs.filter(status='active').count(),
        'total_departments': departments_qs.count(),
        'pending_leaves': leaves_qs.filter(status='pending').count(),
    }
    resp = JsonResponse(data)
    apply_no_cache_headers(resp)
    return resp


# ----- Employees -----

@login_required
@company_admin_or_permission_required('hr_staff.view_employee', raise_exception=True)
@never_cache
def employee_list(request):
    """Employees list with search and status filter. Shell-first: no list query; JS loads via API."""
    search = (request.GET.get('search') or '').strip()
    status_filter = request.GET.get('status', 'all')
    account = get_account_for_user(request.user)
    account_owner_id = getattr(account, 'owner_id', None) if account else None
    context = {
        'employees': [],
        'total_count': 0,
        'status_filter': status_filter,
        'search_query': search,
        'hr_current_page': 'employees',
        'account_owner_id': account_owner_id,
        'users_without_profile_count': 0,
        'can_add_employee': request.user.has_perm('hr_staff.add_employee'),
    }
    response = render(request, 'hr_staff/employee_list.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.view_employee', raise_exception=True)
@never_cache
def employee_detail(request, pk):
    """Employee detail view."""
    qs = get_employee_queryset_for_user(
        request.user, request, account_lookup='account'
    ).select_related('department', 'linked_user').prefetch_related(
        Prefetch('leave_requests', queryset=LeaveRequest.objects.order_by('-start_date'))
    )
    employee, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return resp
    account = get_account_for_user(request.user)
    account_owner_id = getattr(account, 'owner_id', None) if account else None
    employee_is_account_owner = _employee_is_account_owner(employee, account_owner_id)
    leave_requests = list(employee.leave_requests.all())[:10]
    annual_salary = (employee.monthly_salary * 12) if employee.monthly_salary else None
    company = getattr(request, 'company', None) or get_company_profile_for_user(request.user, request)
    currency_symbol = getattr(company, 'currency_symbol', '$') if company else '$'
    display_photo_url = getattr(employee, 'display_photo_url', None) or None
    if display_photo_url and request:
        display_photo_url = request.build_absolute_uri(display_photo_url)
    context = {
        'employee': employee,
        'leave_requests': leave_requests,
        'hr_current_page': 'employees',
        'employee_is_account_owner': employee_is_account_owner,
        'annual_salary': annual_salary,
        'user_currency_symbol': currency_symbol,
        'employee_display_photo_url': display_photo_url,
    }
    response = render(request, 'hr_staff/employee_detail.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.view_employee', raise_exception=True)
@never_cache
@require_GET
def employee_detail_json(request, pk):
    """JSON endpoint for real-time employee detail updates (polling)."""
    qs = get_employee_queryset_for_user(
        request.user, request, account_lookup='account'
    ).select_related('department', 'linked_user')
    employee, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return JsonResponse({'error': 'Not found'}, status=404)
    from apps.core.utils import get_company_context
    company_ctx = get_company_context(request.user, request)
    currency = company_ctx.get('currency_symbol', '$')
    annual = (employee.monthly_salary * 12) if employee.monthly_salary else None
    leave_list = [
        {
            'id': req.pk,
            'leave_type': req.get_leave_type_display(),
            'start_date': req.start_date.strftime('%b %d, %Y'),
            'end_date': req.end_date.strftime('%b %d, %Y'),
            'status': req.get_status_display(),
            'status_class': 'success' if req.status == 'approved' else ('danger' if req.status == 'rejected' else 'warning'),
        }
        for req in employee.leave_requests.all().order_by('-start_date')[:10]
    ]
    photo_url = getattr(employee, 'display_photo_url', None) or None
    if photo_url and request:
        photo_url = request.build_absolute_uri(photo_url)
    # Build a friendly address string (used by detail UI)
    address_parts = [
        (employee.street_address or '').strip(),
        (employee.city or '').strip(),
        (employee.state_province or '').strip(),
        (employee.zip_code or '').strip(),
    ]
    address_parts = [p for p in address_parts if p]
    full_address = ', '.join(address_parts) if address_parts else '—'

    data = {
        'full_name': employee.full_name,
        'first_name': employee.first_name,
        'last_name': employee.last_name,
        'employee_id': employee.employee_id or '—',
        'position': employee.position or '—',
        'department_name': employee.department.name if employee.department else '—',
        'date_joined': employee.date_joined.strftime('%d/%m/%Y') if employee.date_joined else '—',
        'date_joined_long': employee.date_joined.strftime('%B %d, %Y') if employee.date_joined else '—',
        'date_of_birth': employee.date_of_birth.strftime('%d/%m/%Y') if employee.date_of_birth else '—',
        'date_of_birth_long': employee.date_of_birth.strftime('%B %d, %Y') if employee.date_of_birth else '—',
        'reporting_manager': employee.reporting_manager or '—',
        'status': employee.get_status_display(),
        'status_value': employee.status,
        'email': employee.email or '—',
        'phone': employee.phone or '—',
        'street_address': employee.street_address or '—',
        'city': employee.city or '—',
        'state_province': employee.state_province or '—',
        'zip_code': employee.zip_code or '—',
        'full_address': full_address,
        'emergency_contact_name': employee.emergency_contact_name or '—',
        'emergency_contact_phone': employee.emergency_contact_phone or '—',
        'bio': employee.bio or '—',
        'profile_photo_url': photo_url,
        'annual_salary': float(annual) if annual is not None else None,
        'annual_salary_display': f'{currency}{annual:,.2f}' if annual is not None else '—',
        'leave_requests': leave_list,
    }
    response = JsonResponse(data)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.add_employee', raise_exception=True)
@never_cache
def employee_create(request):
    """
    Create a new employee. Optionally create portal access.
    Portal creation is guarded: requires hr_staff.create_employee_account (never implied by
    full_company_visibility or hr_staff.view_employee). User creation and temp password
    are only performed when this explicit permission is present.
    """
    account = get_account_for_user(request.user)
    if not account:
        messages.error(request, 'No account found. Please contact support.')
        return redirect('hr_staff:dashboard')
    # Defer company load until POST (only needed when saving)
    company = None
    enable_portal = False
    users_without_profile = None  # set in GET or POST branch; reused for context
    if request.method == 'POST':
        company = getattr(request, 'company', None) or get_company_profile_for_user(request.user, request)
        users_without_profile = get_account_users_without_employee(account)
        form = EmployeeForm(request.POST, request.FILES, account=account, users_without_employee_queryset=users_without_profile)
        enable_portal = request.POST.get('enable_portal_access') == 'on'
        existing_user = None
        if form.is_valid():
            obj = form.save(commit=False)
            obj.account = account
            obj.company = company
            obj.created_by = request.user
            existing_user = form.cleaned_data.get('link_to_existing_user')
            if existing_user:
                # HR profile only: link to existing User. Never duplicate User; their login stays the same.
                # HR cannot reset password for this user (portal_created_by_hr=False).
                obj.linked_user = existing_user
                obj.first_name = existing_user.first_name or ''
                obj.last_name = existing_user.last_name or ''
                obj.email = existing_user.email or ''
                obj.is_portal_user = True
                obj.portal_created_by_hr = False  # Company Admin created this user; HR may not reset their password
                enable_portal = False  # No new User creation when linking existing
            obj.save()
            temp_password = None
            # Guarded: only explicit create_employee_account permission allows User creation.
            if enable_portal and request.user.has_perm('hr_staff.create_employee_account'):
                # Only when HR (not company admin) creates the portal may HR later reset/disable/delete.
                # Company-admin-created team members must have portal_created_by_hr=False.
                obj.portal_created_by_hr = not is_company_admin(request.user, request)
                obj.save(update_fields=['portal_created_by_hr'])
                try:
                    hr_password = (form.cleaned_data.get('temporary_password') or '').strip() or None
                    _, temp_password = hr_services.create_employee_portal_user(obj, temporary_password=hr_password)
                except ValueError as e:
                    messages.warning(request, str(e))
                else:
                    _log_hr_audit(
                        request, 'CREATE',
                        f'HR created employee portal account for: {obj.full_name} (ID {obj.pk}).',
                        model_name='Employee', object_id=str(obj.pk), object_repr=obj.full_name,
                    )
                    messages.success(
                        request,
                        f'Employee "{obj.full_name}" created with portal access. '
                        'Credentials were generated; show them to the employee once (they will not be shown again).'
                    )
                    context = {
                        'employee': obj,
                        'temp_password': temp_password,
                        'temp_email': obj.email,
                        'hr_current_page': 'employees',
                    }
                    response = render(request, 'hr_staff/employee_credentials_display.html', context)
                    apply_no_cache_headers(response)
                    return response
            if not enable_portal or not request.user.has_perm('hr_staff.create_employee_account'):
                messages.success(request, f'Employee "{obj.full_name}" created successfully.')
            if existing_user:
                # Give the team member the Employee role so they can open HR & Staff and see their profile (My Profile, My Leave).
                from apps.accounts.services import assign_user_to_account_group
                employee_role = hr_services.get_or_create_employee_role(account)
                assign_user_to_account_group(existing_user, employee_role)
                messages.info(request, 'Employee profile linked to existing user. They can now open HR & Staff to see their profile. Their login and password are unchanged; HR cannot reset their password.')
            messages.success(request, f'Employee "{obj.full_name}" saved.')
            return redirect('hr_staff:employee_detail', pk=obj.pk)
    else:
        # GET: shell-first; pre-populate Existing staff dropdown from server so it
        # works immediately (and offline) without relying on the API call.
        users_without_profile = get_account_users_without_employee(account)
        form = EmployeeForm(account=account, users_without_employee_queryset=users_without_profile)
        form.fields['department'].queryset = Department.objects.none()
    if request.method == 'POST' and not form.is_valid():
        messages.error(request, 'Please correct the errors below and try again.')
    if request.method == 'POST':
        departments_qs = get_department_queryset_for_employee_form(request.user, request)
        users_without_profile = get_account_users_without_employee(account)
        form.fields['department'].queryset = departments_qs
        form.fields['link_to_existing_user'].queryset = users_without_profile
        account_users_without_profile = users_without_profile
    else:
        # For GET, mirror the same queryset used in the form so the field stays in sync.
        account_users_without_profile = get_account_users_without_employee(account)
    can_create_portal = request.user.has_perm('hr_staff.create_employee_account')
    currency_symbol = _get_company_currency_symbol(request)
    context = {
        'form': form,
        'hr_current_page': 'employees',
        'create': True,
        'can_create_portal': can_create_portal,
        'default_enable_portal': can_create_portal,  # Default checkbox on so new employees get login
        'account_users_without_profile': account_users_without_profile,
        'user_currency_symbol': currency_symbol,
    }
    response = render(request, 'hr_staff/employee_form.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.add_employee', raise_exception=True)
@require_POST
@never_cache
def employee_create_profiles_for_all(request):
    """
    Create Employee profiles for all users in the account who do not have one.
    Old staff: their login stays the same; app permissions untouched; HR profile only.
    """
    account = get_account_for_user(request.user)
    if not account:
        messages.error(request, 'No account found.')
        return redirect('hr_staff:dashboard')
    users_without = get_account_users_without_employee(account)
    created = 0
    for user in users_without:
        if Employee.objects.filter(account=account, linked_user=user).exists():
            continue
        emp = Employee(
            account=account,
            created_by=request.user,
            first_name=user.first_name or '',
            last_name=user.last_name or '',
            email=user.email or '',
            linked_user=user,
            is_portal_user=True,
            portal_created_by_hr=False,  # Existing user created by Company Admin; HR cannot reset/disable/delete
            status='active',
        )
        emp.save()
        created += 1
    if created:
        messages.success(request, f'Created {created} employee profile(s) for existing users. Their logins and permissions are unchanged.')
    else:
        messages.info(request, 'All users in this account already have an employee profile.')
    return redirect('hr_staff:employee_list')


@login_required
@company_admin_or_permission_required('hr_staff.change_employee', raise_exception=True)
@never_cache
def employee_edit(request, pk):
    """
    Edit an employee. HR can edit HR/profile fields only.
    Auth fields (linked_user, is_portal_user) are never editable here; only Company Admin
    can manage users globally. This prevents HR from breaking app access.
    """
    qs = get_employee_queryset_for_user(
        request.user, request, account_lookup='account'
    )
    employee, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return resp
    account_owner_id = _get_account_owner_id(request)
    if _employee_is_account_owner(employee, account_owner_id) and not is_company_admin(request.user, request):
        messages.error(request, 'You cannot edit the account owner profile.')
        return redirect('hr_staff:employee_detail', pk=employee.pk)
    if request.method == 'POST':
        form = EmployeeForm(request.POST, request.FILES, instance=employee)
        if form.is_valid():
            # Save only form/allowed fields; never persist linked_user/is_portal_user from POST.
            obj = form.save(commit=False)
            update_fields = [f for f in form.Meta.fields if hasattr(Employee, f)]
            if 'first_name' not in update_fields and hasattr(Employee, 'first_name'):
                update_fields.extend(['first_name', 'last_name'])
            obj.save(update_fields=update_fields)
            _log_hr_audit(
                request, 'PROFILE_UPDATE',
                f'Employee profile updated: {employee.full_name} (ID {employee.pk}).',
                model_name='Employee', object_id=str(employee.pk), object_repr=employee.full_name,
            )
            messages.success(request, f'Employee "{employee.full_name}" updated successfully.')
            return redirect('hr_staff:employee_detail', pk=employee.pk)
    else:
        form = EmployeeForm(instance=employee)
    form.fields['department'].queryset = get_department_queryset_for_employee_form(request.user, request)
    current_department = getattr(employee, 'department', None)
    currency_symbol = _get_company_currency_symbol(request)
    context = {
        'form': form,
        'employee': employee,
        'hr_current_page': 'employees',
        'create': False,
        'current_department_id': current_department.pk if current_department else None,
        'current_department_name': current_department.name if current_department else '',
        'user_currency_symbol': currency_symbol,
    }
    response = render(request, 'hr_staff/employee_form.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.delete_employee', raise_exception=True)
@never_cache
def employee_delete(request, pk):
    """Delete an employee (GET: confirm, POST: delete). HR cannot delete User directly or delete account owner."""
    qs = get_employee_queryset_for_user(
        request.user, request, account_lookup='account'
    )
    employee, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return resp
    account_owner_id = _get_account_owner_id(request)
    if _employee_is_account_owner(employee, account_owner_id):
        messages.error(request, 'Cannot delete the account owner.')
        return redirect('hr_staff:employee_detail', pk=pk)
    # HR cannot delete team members created by Company Admin (portal_created_by_hr=False)
    if not is_company_admin(request.user, request) and employee.is_portal_user and not getattr(employee, 'portal_created_by_hr', True):
        raise PermissionDenied(
            'HR cannot delete team members created by the Company Admin. Only profile updates are allowed.'
        )
    if request.method == 'POST':
        name = employee.full_name
        employee.delete()
        messages.success(request, f'Employee "{name}" has been deleted.')
        return redirect('hr_staff:employee_list')
    context = {'employee': employee, 'hr_current_page': 'employees'}
    response = render(request, 'hr_staff/employee_confirm_delete.html', context)
    apply_no_cache_headers(response)
    return response


# ----- Departments -----

@login_required
@company_admin_or_permission_required('hr_staff.view_department', raise_exception=True)
@never_cache
def department_list(request):
    """Departments list. Shell-first: no list query; JS loads via API for instant first paint."""
    search = (request.GET.get('search') or '').strip()
    currency_symbol = _get_company_currency_symbol(request)
    context = {
        'departments': [],
        'search_query': search,
        'total_departments': 0,
        'total_employees': 0,
        'total_budget': 0,
        'user_currency_symbol': currency_symbol,
        'hr_current_page': 'departments',
    }
    response = render(request, 'hr_staff/department_list.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.view_department', raise_exception=True)
@never_cache
def department_detail(request, pk):
    """Department detail with employees."""
    qs = for_user_queryset(
        Department, request.user, request, account_lookup='account'
    )
    department, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return resp
    employees = department.employees.select_related('linked_user').order_by('first_name', 'last_name')
    currency_symbol = _get_company_currency_symbol(request)
    context = {
        'department': department,
        'employees': employees,
        'user_currency_symbol': currency_symbol,
        'hr_current_page': 'departments',
    }
    response = render(request, 'hr_staff/department_detail.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.add_department', raise_exception=True)
@never_cache
def department_create(request):
    """Create a new department."""
    account = get_account_for_user(request.user)
    if not account:
        messages.error(request, 'No account found. Please contact support.')
        return redirect('hr_staff:dashboard')
    if request.method == 'POST':
        form = DepartmentForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.account = account
            obj.created_by = request.user
            obj.save()
            messages.success(request, f'Department "{obj.name}" created successfully.')
            return redirect('hr_staff:department_list')
    else:
        form = DepartmentForm()
    currency_symbol = _get_company_currency_symbol(request)
    context = {
        'form': form,
        'hr_current_page': 'departments',
        'create': True,
        'user_currency_symbol': currency_symbol,
    }
    response = render(request, 'hr_staff/department_form.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.change_department', raise_exception=True)
@never_cache
def department_edit(request, pk):
    """Edit a department."""
    qs = for_user_queryset(
        Department, request.user, request, account_lookup='account'
    )
    department, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return resp
    if request.method == 'POST':
        form = DepartmentForm(request.POST, instance=department)
        if form.is_valid():
            form.save()
            messages.success(request, f'Department "{department.name}" updated successfully.')
            return redirect('hr_staff:department_detail', pk=department.pk)
    else:
        form = DepartmentForm(instance=department)
    currency_symbol = _get_company_currency_symbol(request)
    context = {
        'form': form,
        'department': department,
        'hr_current_page': 'departments',
        'create': False,
        'user_currency_symbol': currency_symbol,
    }
    response = render(request, 'hr_staff/department_form.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.delete_department', raise_exception=True)
@never_cache
def department_delete(request, pk):
    """Delete a department (GET: confirm, POST: delete)."""
    qs = for_user_queryset(
        Department, request.user, request, account_lookup='account'
    )
    department, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return resp
    if request.method == 'POST':
        name = department.name
        department.delete()
        messages.success(request, f'Department "{name}" has been deleted.')
        return redirect('hr_staff:department_list')
    context = {'department': department, 'hr_current_page': 'departments'}
    response = render(request, 'hr_staff/department_confirm_delete.html', context)
    apply_no_cache_headers(response)
    return response


# ----- Leave requests -----

@login_required
@company_admin_or_permission_required('hr_staff.view_leaverequest', raise_exception=True)
@never_cache
def leave_list(request):
    """Leave requests list. Shell-first: no list query; JS loads via API for instant first paint."""
    base_qs = get_leave_queryset_for_user(
        request.user, request, account_lookup='account'
    )
    status_counts = base_qs.aggregate(
        total=Count('id'),
        pending=Count('id', filter=Q(status='pending')),
        approved=Count('id', filter=Q(status='approved')),
        rejected=Count('id', filter=Q(status='rejected')),
    )
    status_filter = request.GET.get('status', 'all')
    leave_type_filter = request.GET.get('leave_type', 'all')
    total_requests = status_counts['total'] or 0
    pending_count = status_counts['pending'] or 0
    approved_count = status_counts['approved'] or 0
    rejected_count = status_counts['rejected'] or 0
    from apps.core.ownership import is_company_admin as _is_admin_for_leave_list
    # HR role (view_hr_dashboard) can approve/reject leave; view_hr_dashboard implies full HR dashboard access
    can_manage_leave = (
        _is_admin_for_leave_list(request.user, request)
        or request.user.has_perm('hr_staff.change_leaverequest')
        or request.user.has_perm('hr_staff.view_hr_dashboard')
    )

    context = {
        'leaves': [],
        'status_filter': status_filter,
        'leave_type_filter': leave_type_filter,
        'total_requests': total_requests,
        'pending_count': pending_count,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
        'hr_current_page': 'leave',
        'is_employee_portal': not request.user.has_perm('hr_staff.view_hr_dashboard'),  # Full HR nav when user has view_hr_dashboard
        'can_manage_leave': can_manage_leave,
    }
    response = render(request, 'hr_staff/leave_list.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.view_leaverequest', raise_exception=True)
@never_cache
def leave_detail(request, pk):
    """Leave request detail."""
    qs = get_leave_queryset_for_user(
        request.user, request, account_lookup='account'
    ).select_related('employee', 'employee__department')
    leave_req, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return resp
    context = {'leave': leave_req, 'hr_current_page': 'leave'}
    response = render(request, 'hr_staff/leave_detail.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.add_leaverequest', raise_exception=True)
@never_cache
def leave_create(request):
    """Create a leave request."""
    account = get_account_for_user(request.user)
    if not account:
        messages.error(request, 'No account found. Please contact support.')
        return redirect('hr_staff:dashboard')
    if request.method == 'POST':
        employees_qs = get_employee_queryset_for_user(
            request.user, request, account_lookup='account'
        ).filter(status='active').order_by('first_name', 'last_name')
        form = LeaveRequestForm(request.POST, request.FILES)
        form.fields['employee'].queryset = employees_qs.select_related('department')
        if form.is_valid():
            obj = form.save(commit=False)
            obj.account = account
            obj.created_by = request.user
            obj.save()
            from apps.core.ownership import is_company_admin as _is_admin_for_leave
            if _is_admin_for_leave(request.user, request) or request.user.has_perm('hr_staff.view_hr_dashboard'):
                messages.success(request, 'Leave request created successfully. You can add another below.')
                return redirect('hr_staff:leave_create')
            messages.success(request, 'Leave request submitted successfully.')
            return redirect('hr_staff:leave_detail', pk=obj.pk)
    else:
        form = LeaveRequestForm()
        form.fields['employee'].queryset = Employee.objects.none()
    context = {'form': form, 'hr_current_page': 'leave', 'create': True}
    response = render(request, 'hr_staff/leave_form.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.change_leaverequest', raise_exception=True)
@never_cache
def leave_edit(request, pk):
    """Edit a leave request."""
    qs = get_leave_queryset_for_user(
        request.user, request, account_lookup='account'
    )
    leave_req, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return resp
    employees_qs = get_employee_queryset_for_user(
        request.user, request, account_lookup='account'
    ).order_by('first_name', 'last_name')
    if request.method == 'POST':
        form = LeaveRequestForm(request.POST, request.FILES, instance=leave_req)
        if form.is_valid():
            form.save()
            messages.success(request, 'Leave request updated successfully.')
            return redirect('hr_staff:leave_detail', pk=leave_req.pk)
    else:
        form = LeaveRequestForm(instance=leave_req)
    form.fields['employee'].queryset = employees_qs.select_related('department')
    context = {'form': form, 'leave': leave_req, 'hr_current_page': 'leave', 'create': False}
    response = render(request, 'hr_staff/leave_form.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.delete_leaverequest', raise_exception=True)
@never_cache
def leave_delete(request, pk):
    """Delete a leave request (GET: confirm, POST: delete)."""
    qs = get_leave_queryset_for_user(
        request.user, request, account_lookup='account'
    ).select_related('employee')
    leave_req, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return resp
    if request.method == 'POST':
        leave_req.delete()
        messages.success(request, 'Leave request has been deleted.')
        return redirect('hr_staff:leave_list')
    context = {'leave': leave_req, 'hr_current_page': 'leave'}
    response = render(request, 'hr_staff/leave_confirm_delete.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_any_permission_required(
    ['hr_staff.change_leaverequest', 'hr_staff.view_hr_dashboard'],
    raise_exception=True,
)
@require_POST
@never_cache
def leave_update_status(request, pk):
    """Update leave request status (approve/reject). Expects POST with status=approved|rejected."""
    qs = get_leave_queryset_for_user(
        request.user, request, account_lookup='account'
    )
    leave_req, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return resp
    status_val = (request.POST.get('status') or request.GET.get('status') or '').strip().lower()
    if status_val in ('approved', 'rejected'):
        from django.utils import timezone
        leave_req.status = status_val
        leave_req.status_changed_by = request.user
        leave_req.status_changed_at = timezone.now()
        leave_req.save(update_fields=['status', 'status_changed_by', 'status_changed_at'])
        _notify_employee_leave_status(leave_req, status_val, request)
        _log_hr_audit(
            request, 'UPDATE',
            f'HR {status_val} leave request: {leave_req.employee.full_name} ({leave_req.start_date}–{leave_req.end_date}).',
            model_name='LeaveRequest', object_id=str(leave_req.pk), object_repr=str(leave_req),
            object_url=request.build_absolute_uri(f'/hr-staff/leave/{leave_req.pk}/'),
        )
        messages.success(request, f'Leave request {status_val}.')
    else:
        messages.error(request, 'Invalid status.')
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        resp = JsonResponse({'success': True, 'status': leave_req.status})
        apply_no_cache_headers(resp)
        return resp
    next_url = request.POST.get('next') or request.GET.get('next') or request.META.get('HTTP_REFERER')
    if next_url:
        return redirect(next_url)
    return redirect('hr_staff:leave_detail', pk=leave_req.pk)


# ----- HR-only: Create portal account, Reset password, Enable/Disable -----

@login_required
# View protection: password reset requires explicit reset_employee_password (not implied by full_company_visibility).
@company_admin_or_permission_required('hr_staff.reset_employee_password', raise_exception=True)
@require_POST
@never_cache
def employee_reset_password(request, pk):
    """Reset linked User password; show temporary password once. HR cannot view password after. Cannot reset account owner."""
    qs = get_employee_queryset_for_user(
        request.user, request, account_lookup='account'
    )
    employee, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return resp
    account_owner_id = _get_account_owner_id(request)
    if _employee_is_account_owner(employee, account_owner_id):
        messages.error(request, 'Cannot reset password for the account owner.')
        return redirect('hr_staff:employee_detail', pk=pk)
    if not getattr(employee, 'portal_created_by_hr', True):
        raise PermissionDenied(
            'HR cannot reset password for team members created by the Company Admin. Only profile updates are allowed.'
        )
    try:
        temp_password = hr_services.reset_employee_password(employee)
        _log_hr_audit(
            request, 'PASSWORD_RESET',
            f'HR reset portal password for employee: {employee.full_name} (ID {employee.pk}).',
            model_name='Employee', object_id=str(employee.pk), object_repr=employee.full_name,
        )
    except ValueError as e:
        messages.error(request, str(e))
        return redirect('hr_staff:employee_detail', pk=pk)
    context = {
        'employee': employee,
        'temp_password': temp_password,
        'temp_email': employee.email,
        'hr_current_page': 'employees',
    }
    response = render(request, 'hr_staff/employee_credentials_display.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.change_employee', raise_exception=True)
@require_POST
@never_cache
def employee_toggle_active(request, pk):
    """Enable or disable employee portal account (User.is_active). Cannot disable account owner."""
    qs = get_employee_queryset_for_user(
        request.user, request, account_lookup='account'
    )
    employee, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return resp
    account_owner_id = _get_account_owner_id(request)
    if _employee_is_account_owner(employee, account_owner_id):
        messages.error(request, 'Cannot disable or modify the account owner.')
        return redirect('hr_staff:employee_detail', pk=pk)
    if not employee.linked_user_id:
        messages.warning(request, 'Employee does not have portal access.')
        return redirect('hr_staff:employee_detail', pk=pk)
    # HR cannot disable team members created by Company Admin (portal_created_by_hr=False)
    if not is_company_admin(request.user, request) and not getattr(employee, 'portal_created_by_hr', True):
        raise PermissionDenied(
            'HR cannot disable team members created by the Company Admin. Only profile updates are allowed.'
        )
    new_active = not employee.linked_user.is_active
    hr_services.set_employee_account_active(employee, new_active)
    status = 'activated' if new_active else 'disabled'
    _log_hr_audit(
        request, 'SETTINGS_CHANGE',
        f'HR {status} portal account for employee: {employee.full_name} (ID {employee.pk}).',
        model_name='Employee', object_id=str(employee.pk), object_repr=employee.full_name,
    )
    messages.success(request, f'Portal account {status}.')
    return redirect('hr_staff:employee_detail', pk=pk)


# ----- Employee portal dashboard (self-only) -----

@login_required
@never_cache
def employee_portal_dashboard(request):
    """
    Dashboard for employees: only their own profile and leave.
    Requires view_own_hr_dashboard and a linked Employee. Employees cannot escalate to HR view.
    """
    if not request.user.has_perm('hr_staff.view_own_hr_dashboard'):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied('You do not have access to the employee portal.')
    linked = get_linked_employee_for_user(request.user)
    if not linked:
        if request.user.has_perm('hr_staff.view_hr_dashboard'):
            return redirect('hr_staff:dashboard')
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied('You need an employee profile to access the employee dashboard.')
    leaves = get_leave_queryset_for_user(
        request.user, request, account_lookup='account'
    ).select_related('employee').order_by('-start_date')[:10]
    company = getattr(request, 'company', None) or get_company_profile_for_user(request.user, request)
    currency_symbol = getattr(company, 'currency_symbol', '$') if company else '$'
    from apps.accounts.models import UserActivity
    recent_activity = list(
        UserActivity.objects.filter(user=request.user, app_name='hr_staff')
        .order_by('-timestamp')[:15]
        .values('activity_type', 'description', 'timestamp', 'object_url')
    )
    for a in recent_activity:
        if a.get('timestamp'):
            a['timestamp'] = a['timestamp'].strftime('%b %d, %Y %H:%M')
    context = {
        'employee': linked,
        'leave_requests': leaves,
        'user_currency_symbol': currency_symbol,
        'hr_current_page': 'portal_dashboard',
        'is_employee_portal': True,
        'recent_activity': recent_activity,
    }
    response = render(request, 'hr_staff/employee_portal_dashboard.html', context)
    apply_no_cache_headers(response)
    return response


# ----- Leave Policies -----

@login_required
@company_admin_or_permission_required('hr_staff.view_leaverequest', raise_exception=True)
@never_cache
def leave_policy_list(request):
    """List all leave policies."""
    from .querysets import get_leave_policy_queryset_for_user
    qs = get_leave_policy_queryset_for_user(request.user, request, account_lookup='account')
    context = {
        'leave_policies': qs,
        'hr_current_page': 'leave_policies',
    }
    response = render(request, 'hr_staff/leave_policy_list.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.add_leaverequest', raise_exception=True)
@never_cache
def leave_policy_create(request):
    """Create new leave policy."""
    from .models import LeavePolicy
    from django import forms
    
    class LeavePolicyForm(forms.ModelForm):
        class Meta:
            model = LeavePolicy
            fields = ['name', 'leave_type', 'days_per_year', 'carry_over_allowed', 
                      'max_carry_over', 'requires_approval', 'max_consecutive_days', 'is_active']
    
    if request.method == 'POST':
        form = LeavePolicyForm(request.POST)
        if form.is_valid():
            policy = form.save(commit=False)
            account = get_account_for_user(request.user)
            policy.account = account
            policy.created_by = request.user
            policy.save()
            _log_hr_audit(request, 'CREATE', f'Created leave policy: {policy.name}', 
                          model_name='LeavePolicy', object_repr=policy.name)
            messages.success(request, 'Leave policy created.')
            return redirect('hr_staff:leave_policy_list')
    else:
        form = LeavePolicyForm()
    
    context = {'form': form, 'hr_current_page': 'leave_policies'}
    response = render(request, 'hr_staff/leave_policy_form.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.view_leaverequest', raise_exception=True)
@never_cache
def leave_policy_detail(request, pk):
    """View leave policy detail."""
    from .querysets import get_leave_policy_queryset_for_user
    qs = get_leave_policy_queryset_for_user(request.user, request, account_lookup='account')
    policy, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return resp
    context = {'policy': policy, 'hr_current_page': 'leave_policies'}
    response = render(request, 'hr_staff/leave_policy_detail.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.change_leaverequest', raise_exception=True)
@never_cache
def leave_policy_edit(request, pk):
    """Edit leave policy."""
    from .models import LeavePolicy
    from django import forms
    
    class LeavePolicyForm(forms.ModelForm):
        class Meta:
            model = LeavePolicy
            fields = ['name', 'leave_type', 'days_per_year', 'carry_over_allowed', 
                      'max_carry_over', 'requires_approval', 'max_consecutive_days', 'is_active']
    
    qs = get_leave_policy_queryset_for_user(request.user, request, account_lookup='account')
    policy, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return resp
    
    if request.method == 'POST':
        form = LeavePolicyForm(request.POST, instance=policy)
        if form.is_valid():
            form.save()
            _log_hr_audit(request, 'UPDATE', f'Updated leave policy: {policy.name}', 
                          model_name='LeavePolicy', object_id=str(pk), object_repr=policy.name)
            messages.success(request, 'Leave policy updated.')
            return redirect('hr_staff:leave_policy_detail', pk=pk)
    else:
        form = LeavePolicyForm(instance=policy)
    
    context = {'form': form, 'policy': policy, 'hr_current_page': 'leave_policies'}
    response = render(request, 'hr_staff/leave_policy_form.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.delete_leaverequest', raise_exception=True)
@require_POST
@never_cache
def leave_policy_delete(request, pk):
    """Delete leave policy."""
    qs = get_leave_policy_queryset_for_user(request.user, request, account_lookup='account')
    policy, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return resp
    name = policy.name
    policy.delete()
    _log_hr_audit(request, 'DELETE', f'Deleted leave policy: {name}', model_name='LeavePolicy')
    messages.success(request, 'Leave policy deleted.')
    return redirect('hr_staff:leave_policy_list')


# ----- Attendance -----

@login_required
@company_admin_or_permission_required('hr_staff.view_employee', raise_exception=True)
@never_cache
def attendance_list(request):
    """List attendance records."""
    from datetime import date
    today = date.today()
    month_start = today.replace(day=1)
    qs = get_attendance_queryset_for_user(request.user, request, account_lookup='account')
    context = {
        'attendance_records': qs.select_related('employee')[:50],
        'hr_current_page': 'attendance',
        'today': today,
    }
    response = render(request, 'hr_staff/attendance_list.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.add_employee', raise_exception=True)
@never_cache
def attendance_create(request):
    """Create manual attendance record."""
    from datetime import date
    from .models import Attendance
    from django import forms
    
    class AttendanceForm(forms.ModelForm):
        class Meta:
            model = Attendance
            fields = ['employee', 'date', 'check_in', 'check_out', 'status', 'notes']
            widgets = {
                'date': forms.DateInput(attrs={'type': 'date'}),
                'check_in': forms.TimeInput(attrs={'type': 'time'}),
                'check_out': forms.TimeInput(attrs={'type': 'time'}),
            }
    
    if request.method == 'POST':
        form = AttendanceForm(request.POST)
        if form.is_valid():
            att = form.save(commit=False)
            account = get_account_for_user(request.user)
            att.account = account
            att.created_by = request.user
            att.is_manual = True
            att.save()
            _log_hr_audit(request, 'CREATE', f'Added attendance for {att.employee}', 
                          model_name='Attendance', object_repr=str(att))
            messages.success(request, 'Attendance record added.')
            return redirect('hr_staff:attendance_list')
    else:
        form = AttendanceForm()
        form.fields['employee'].queryset = get_employee_queryset_for_user(request.user, request, account_lookup='account')
        form.initial['date'] = date.today()
    
    context = {'form': form, 'hr_current_page': 'attendance'}
    response = render(request, 'hr_staff/attendance_form.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.view_employee', raise_exception=True)
@never_cache
def attendance_detail(request, pk):
    """View attendance detail."""
    qs = get_attendance_queryset_for_user(request.user, request, account_lookup='account')
    att, resp = get_object_or_unauthorized(request, qs.select_related('employee'), pk=pk)
    if resp:
        return resp
    context = {'attendance': att, 'hr_current_page': 'attendance'}
    response = render(request, 'hr_staff/attendance_detail.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.change_employee', raise_exception=True)
@never_cache
def attendance_edit(request, pk):
    """Edit attendance record."""
    from .models import Attendance
    from django import forms
    
    class AttendanceForm(forms.ModelForm):
        class Meta:
            model = Attendance
            fields = ['employee', 'date', 'check_in', 'check_out', 'status', 'notes']
            widgets = {
                'date': forms.DateInput(attrs={'type': 'date'}),
                'check_in': forms.TimeInput(attrs={'type': 'time'}),
                'check_out': forms.TimeInput(attrs={'type': 'time'}),
            }
    
    qs = get_attendance_queryset_for_user(request.user, request, account_lookup='account')
    att, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return resp
    
    if request.method == 'POST':
        form = AttendanceForm(request.POST, instance=att)
        if form.is_valid():
            form.save()
            _log_hr_audit(request, 'UPDATE', f'Updated attendance for {att.employee}', 
                          model_name='Attendance', object_id=str(pk), object_repr=str(att))
            messages.success(request, 'Attendance record updated.')
            return redirect('hr_staff:attendance_detail', pk=pk)
    else:
        form = AttendanceForm(instance=att)
        form.fields['employee'].queryset = get_employee_queryset_for_user(request.user, request, account_lookup='account')
    
    context = {'form': form, 'attendance': att, 'hr_current_page': 'attendance'}
    response = render(request, 'hr_staff/attendance_form.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.delete_employee', raise_exception=True)
@require_POST
@never_cache
def attendance_delete(request, pk):
    """Delete attendance record."""
    qs = get_attendance_queryset_for_user(request.user, request, account_lookup='account')
    att, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return resp
    name = str(att)
    att.delete()
    _log_hr_audit(request, 'DELETE', f'Deleted attendance: {name}', model_name='Attendance')
    messages.success(request, 'Attendance record deleted.')
    return redirect('hr_staff:attendance_list')


# ----- Attendance Reports -----

@login_required
@company_admin_or_permission_required('hr_staff.view_employee', raise_exception=True)
@never_cache
def attendance_reports(request):
    """Attendance reports view."""
    from datetime import date, timedelta
    from calendar import monthrange
    
    today = date.today()
    year = int(request.GET.get('year', today.year))
    month = int(request.GET.get('month', today.month))
    
    month_start = date(year, month, 1)
    _, last_day = monthrange(year, month)
    month_end = date(year, month, last_day)
    
    qs = get_attendance_queryset_for_user(request.user, request, account_lookup='account')
    records = qs.filter(date__gte=month_start, date__lte=month_end).select_related('employee')
    
    from django.db.models import Count
    by_status = records.values('status').annotate(count=Count('id'))
    
    employees = get_employee_queryset_for_user(request.user, request, account_lookup='account')
    
    context = {
        'hr_current_page': 'attendance_reports',
        'year': year,
        'month': month,
        'months': list(range(1, 13)),
        'years': [year - 1, year, year + 1],
        'records': records[:100],
        'by_status': by_status,
        'employees': employees,
        'total_days': last_day,
    }
    response = render(request, 'hr_staff/attendance_reports.html', context)
    apply_no_cache_headers(response)
    return response


# ----- Performance Reviews -----

@login_required
@company_admin_or_permission_required('hr_staff.view_employee', raise_exception=True)
@never_cache
def performance_review_list(request):
    """List performance reviews."""
    qs = get_performance_review_queryset_for_user(request.user, request, account_lookup='account')
    context = {
        'reviews': qs,
        'hr_current_page': 'performance',
    }
    response = render(request, 'hr_staff/performance_review_list.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.add_employee', raise_exception=True)
@never_cache
def performance_review_create(request):
    """Create performance review."""
    from .models import PerformanceReview
    from django import forms
    
    class PerformanceReviewForm(forms.ModelForm):
        class Meta:
            model = PerformanceReview
            fields = ['title', 'description', 'start_date', 'end_date', 'status', 'review_type']
            widgets = {
                'start_date': forms.DateInput(attrs={'type': 'date'}),
                'end_date': forms.DateInput(attrs={'type': 'date'}),
            }
    
    if request.method == 'POST':
        form = PerformanceReviewForm(request.POST)
        if form.is_valid():
            review = form.save(commit=False)
            account = get_account_for_user(request.user)
            review.account = account
            review.created_by = request.user
            review.save()
            _log_hr_audit(request, 'CREATE', f'Created performance review: {review.title}', 
                          model_name='PerformanceReview', object_repr=review.title)
            messages.success(request, 'Performance review created.')
            return redirect('hr_staff:performance_review_list')
    else:
        form = PerformanceReviewForm()
    
    context = {'form': form, 'hr_current_page': 'performance'}
    response = render(request, 'hr_staff/performance_review_form.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.view_employee', raise_exception=True)
@never_cache
def performance_review_detail(request, pk):
    """View performance review detail."""
    qs = get_performance_review_queryset_for_user(request.user, request, account_lookup='account')
    review, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return resp
    employees = get_employee_queryset_for_user(request.user, request, account_lookup='account')
    context = {
        'review': review,
        'employees': employees,
        'hr_current_page': 'performance',
    }
    response = render(request, 'hr_staff/performance_review_detail.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.change_employee', raise_exception=True)
@never_cache
def performance_review_edit(request, pk):
    """Edit performance review."""
    from .models import PerformanceReview
    from django import forms
    
    class PerformanceReviewForm(forms.ModelForm):
        class Meta:
            model = PerformanceReview
            fields = ['title', 'description', 'start_date', 'end_date', 'status', 'review_type']
            widgets = {
                'start_date': forms.DateInput(attrs={'type': 'date'}),
                'end_date': forms.DateInput(attrs={'type': 'date'}),
            }
    
    qs = get_performance_review_queryset_for_user(request.user, request, account_lookup='account')
    review, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return resp
    
    if request.method == 'POST':
        form = PerformanceReviewForm(request.POST, instance=review)
        if form.is_valid():
            form.save()
            messages.success(request, 'Performance review updated.')
            return redirect('hr_staff:performance_review_detail', pk=pk)
    else:
        form = PerformanceReviewForm(instance=review)
    
    context = {'form': form, 'review': review, 'hr_current_page': 'performance'}
    response = render(request, 'hr_staff/performance_review_form.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.delete_employee', raise_exception=True)
@require_POST
@never_cache
def performance_review_delete(request, pk):
    """Delete performance review."""
    qs = get_performance_review_queryset_for_user(request.user, request, account_lookup='account')
    review, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return resp
    title = review.title
    review.delete()
    messages.success(request, 'Performance review deleted.')
    return redirect('hr_staff:performance_review_list')


# ----- Performance Goals -----

@login_required
@company_admin_or_permission_required('hr_staff.view_employee', raise_exception=True)
@never_cache
def performance_goal_list(request):
    """List performance goals."""
    from .querysets import get_performance_goal_queryset_for_user
    qs = get_performance_goal_queryset_for_user(request.user, request, account_lookup='account')
    context = {
        'goals': qs.select_related('employee', 'review')[:50],
        'hr_current_page': 'performance_goals',
    }
    response = render(request, 'hr_staff/performance_goal_list.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.add_employee', raise_exception=True)
@never_cache
def performance_goal_create(request):
    """Create performance goal."""
    from .models import PerformanceGoal
    from django import forms
    
    class PerformanceGoalForm(forms.ModelForm):
        class Meta:
            model = PerformanceGoal
            fields = ['employee', 'title', 'description', 'due_date', 'status', 'progress', 'review']
            widgets = {
                'due_date': forms.DateInput(attrs={'type': 'date'}),
            }
    
    if request.method == 'POST':
        form = PerformanceGoalForm(request.POST)
        if form.is_valid():
            goal = form.save(commit=False)
            account = get_account_for_user(request.user)
            goal.account = account
            goal.created_by = request.user
            goal.save()
            _log_hr_audit(request, 'CREATE', f'Created goal: {goal.title}', 
                          model_name='PerformanceGoal', object_repr=goal.title)
            messages.success(request, 'Goal created.')
            return redirect('hr_staff:performance_goal_list')
    else:
        form = PerformanceGoalForm()
        form.fields['employee'].queryset = get_employee_queryset_for_user(request.user, request, account_lookup='account')
        form.fields['review'].queryset = get_performance_review_queryset_for_user(request.user, request, account_lookup='account')
    
    context = {'form': form, 'hr_current_page': 'performance_goals'}
    response = render(request, 'hr_staff/performance_goal_form.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.change_employee', raise_exception=True)
@never_cache
def performance_goal_edit(request, pk):
    """Edit performance goal."""
    from .models import PerformanceGoal
    from django import forms
    
    class PerformanceGoalForm(forms.ModelForm):
        class Meta:
            model = PerformanceGoal
            fields = ['employee', 'title', 'description', 'due_date', 'status', 'progress', 'review']
            widgets = {
                'due_date': forms.DateInput(attrs={'type': 'date'}),
            }
    
    qs = get_performance_goal_queryset_for_user(request.user, request, account_lookup='account')
    goal, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return resp
    
    if request.method == 'POST':
        form = PerformanceGoalForm(request.POST, instance=goal)
        if form.is_valid():
            form.save()
            messages.success(request, 'Goal updated.')
            return redirect('hr_staff:performance_goal_list')
    else:
        form = PerformanceGoalForm(instance=goal)
        form.fields['employee'].queryset = get_employee_queryset_for_user(request.user, request, account_lookup='account')
        form.fields['review'].queryset = get_performance_review_queryset_for_user(request.user, request, account_lookup='account')
    
    context = {'form': form, 'goal': goal, 'hr_current_page': 'performance_goals'}
    response = render(request, 'hr_staff/performance_goal_form.html', context)
    apply_no_cache_headers(response)
    return response


# ----- Training -----

@login_required
@company_admin_or_permission_required('hr_staff.view_employee', raise_exception=True)
@never_cache
def training_course_list(request):
    """List training courses."""
    qs = get_training_course_queryset_for_user(request.user, request, account_lookup='account')
    context = {
        'courses': qs,
        'hr_current_page': 'training',
    }
    response = render(request, 'hr_staff/training_course_list.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.add_employee', raise_exception=True)
@never_cache
def training_course_create(request):
    """Create training course."""
    from .models import TrainingCourse
    from django import forms
    
    class TrainingCourseForm(forms.ModelForm):
        class Meta:
            model = TrainingCourse
            fields = ['title', 'description', 'category', 'duration_hours', 'status', 'is_required']
    
    if request.method == 'POST':
        form = TrainingCourseForm(request.POST)
        if form.is_valid():
            course = form.save(commit=False)
            account = get_account_for_user(request.user)
            course.account = account
            course.created_by = request.user
            course.save()
            _log_hr_audit(request, 'CREATE', f'Created course: {course.title}', 
                          model_name='TrainingCourse', object_repr=course.title)
            messages.success(request, 'Course created.')
            return redirect('hr_staff:training_course_list')
    else:
        form = TrainingCourseForm()
    
    context = {'form': form, 'hr_current_page': 'training'}
    response = render(request, 'hr_staff/training_course_form.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.view_employee', raise_exception=True)
@never_cache
def training_course_detail(request, pk):
    """View training course detail."""
    qs = get_training_course_queryset_for_user(request.user, request, account_lookup='account')
    course, resp = get_object_or_unauthorized(request, qs.prefetch_related('enrollments', 'enrollments__employee'), pk=pk)
    if resp:
        return resp
    context = {'course': course, 'hr_current_page': 'training'}
    response = render(request, 'hr_staff/training_course_detail.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.change_employee', raise_exception=True)
@never_cache
def training_course_edit(request, pk):
    """Edit training course."""
    from .models import TrainingCourse
    from django import forms
    
    class TrainingCourseForm(forms.ModelForm):
        class Meta:
            model = TrainingCourse
            fields = ['title', 'description', 'category', 'duration_hours', 'status', 'is_required']
    
    qs = get_training_course_queryset_for_user(request.user, request, account_lookup='account')
    course, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return resp
    
    if request.method == 'POST':
        form = TrainingCourseForm(request.POST, instance=course)
        if form.is_valid():
            form.save()
            messages.success(request, 'Course updated.')
            return redirect('hr_staff:training_course_detail', pk=pk)
    else:
        form = TrainingCourseForm(instance=course)
    
    context = {'form': form, 'course': course, 'hr_current_page': 'training'}
    response = render(request, 'hr_staff/training_course_form.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.add_employee', raise_exception=True)
@never_cache
def training_enrollment_create(request):
    """Enroll employee in training course."""
    from .models import TrainingEnrollment
    from django import forms
    
    class TrainingEnrollmentForm(forms.ModelForm):
        class Meta:
            model = TrainingEnrollment
            fields = ['employee', 'course', 'status']
    
    if request.method == 'POST':
        form = TrainingEnrollmentForm(request.POST)
        if form.is_valid():
            enrollment = form.save(commit=False)
            account = get_account_for_user(request.user)
            enrollment.account = account
            enrollment.created_by = request.user
            enrollment.save()
            try:
                from .services import notify_training_enrollment
                base_url = request.build_absolute_uri('/')
                if base_url:
                    base_url = base_url.rstrip('/')
                notify_training_enrollment(enrollment, base_url)
            except Exception:
                pass  # Email is optional
            messages.success(request, 'Employee enrolled.')
            return redirect('hr_staff:training_course_list')
    else:
        form = TrainingEnrollmentForm()
        form.fields['employee'].queryset = get_employee_queryset_for_user(request.user, request, account_lookup='account')
        form.fields['course'].queryset = get_training_course_queryset_for_user(request.user, request, account_lookup='account')
    
    context = {'form': form, 'hr_current_page': 'training'}
    response = render(request, 'hr_staff/training_enrollment_form.html', context)
    apply_no_cache_headers(response)
    return response


# ----- Documents -----

@login_required
@company_admin_or_permission_required('hr_staff.add_employee', raise_exception=True)
@never_cache
def document_list(request):
    """List employee documents."""
    from .querysets import get_employee_document_queryset_for_user
    qs = get_employee_document_queryset_for_user(request.user, request, account_lookup='account')
    context = {
        'documents': qs.select_related('employee')[:50],
        'hr_current_page': 'documents',
    }
    response = render(request, 'hr_staff/document_list.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.add_employee', raise_exception=True)
@never_cache
def document_create(request):
    """Upload employee document with smart extraction."""
    from .models import EmployeeDocument
    import json
    
    # Handle AJAX extraction request
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' and request.method == 'POST':
        file = request.FILES.get('file')
        if file:
            try:
                # Read file content
                file_content = file.read()
                filename = file.name
                
                # Try to extract information using CV extractor
                from .cv_extraction import extract_cv_information
                extraction_result = extract_cv_information(file_content, filename)
                
                # Smart document type detection
                document_type = 'other'
                title = filename
                
                text = extraction_result.get('extracted_text', '')
                text_lower = text.lower() if text else ''
                
                # Detect document type based on content
                cv_keywords = ['resume', 'curriculum vitae', 'work experience', 'education', 'skills', 'employment']
                contract_keywords = ['contract', 'employment', 'agreement', 'terms of employment', 'salary', 'benefits']
                certificate_keywords = ['certificate', 'certification', 'completion', 'training', 'awarded']
                id_keywords = ['id card', 'passport', 'national id', 'driver license', 'license']
                
                cv_score = sum(1 for kw in cv_keywords if kw in text_lower)
                contract_score = sum(1 for kw in contract_keywords if kw in text_lower)
                certificate_score = sum(1 for kw in certificate_keywords if kw in text_lower)
                id_score = sum(1 for kw in id_keywords if kw in text_lower)
                
                max_score = max(cv_score, contract_score, certificate_score, id_score)
                
                if cv_score == max_score and cv_score > 0:
                    document_type = 'other'  # CV is not in current choices, use other
                    title = extraction_result.get('name', filename) or filename
                elif contract_score == max_score and contract_score > 0:
                    document_type = 'contract'
                elif certificate_score == max_score and certificate_score > 0:
                    document_type = 'certificate'
                elif id_score == max_score and id_score > 0:
                    document_type = 'id_card'
                
                # Also detect from filename
                filename_lower = filename.lower()
                if 'cv' in filename_lower or 'resume' in filename_lower:
                    document_type = 'other'
                elif 'contract' in filename_lower:
                    document_type = 'contract'
                elif 'certificate' in filename_lower or 'cert' in filename_lower:
                    document_type = 'certificate'
                elif 'id' in filename_lower:
                    document_type = 'id_card'
                
                return JsonResponse({
                    'status': 'success',
                    'extraction': {
                        'document_type': document_type,
                        'title': title,
                        'name': extraction_result.get('name', ''),
                        'email': extraction_result.get('email', ''),
                        'phone': extraction_result.get('phone', []),
                        'skills': extraction_result.get('skills', {}),
                        'education': extraction_result.get('education', []),
                        'work_experience': extraction_result.get('work_experience', []),
                        'position_applied': extraction_result.get('position_applied', ''),
                        'years_of_experience': extraction_result.get('years_of_experience', ''),
                        'address': extraction_result.get('address', ''),
                        'extracted_text': text[:2000] if text else '',  # First 2000 chars
                        'extraction_success': extraction_result.get('extraction_success', False),
                    }
                })
            except Exception as e:
                return JsonResponse({
                    'status': 'error',
                    'message': str(e)
                }, status=500)
    
    if request.method == 'POST':
        form = EmployeeDocumentForm(request.POST, request.FILES)
        
        # Check for extracted data from AJAX
        extracted_json = request.POST.get('extracted_json', '')
        extracted_data = {}
        if extracted_json:
            try:
                import json
                extracted_data = json.loads(extracted_json)
            except:
                pass
        
        if form.is_valid():
            doc = form.save(commit=False)
            
            # Always use the current user's account
            account = get_account_for_user(request.user)
            print(f"DEBUG: Saving document. User: {request.user}, Account: {account}")
            doc.account = account
            doc.created_by = request.user
            
            # Save extracted data if available
            if extracted_data:
                try:
                    import json
                    from django.utils import timezone
                    doc.extracted_data_json = json.dumps(extracted_data)
                    doc.extracted_at = timezone.now()
                    
                    # Auto-detect document type based on extraction
                    if extracted_data.get('skills') or extracted_data.get('education') or extracted_data.get('work_experience'):
                        doc.document_type = 'cv'
                except:
                    pass
            
            doc.save()
            print(f"DEBUG: Document saved with ID: {doc.id}, Account: {doc.account}")
            _log_hr_audit(request, 'FILE_UPLOAD', f'Uploaded document: {doc.title}', 
                          model_name='EmployeeDocument', object_repr=doc.title)
            messages.success(request, 'Document uploaded successfully.')
            
            # Check if request is AJAX, return JSON for auto-update
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'status': 'success',
                    'message': 'Document uploaded successfully.',
                    'document_id': doc.id,
                    'redirect_url': reverse('hr_staff:document_list')
                })
            
            return redirect('hr_staff:document_list')
        else:
            # Form is invalid - return JSON with errors for AJAX
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                errors = {}
                for field, error_list in form.errors.items():
                    errors[field] = [str(e) for e in error_list]
                return JsonResponse({
                    'status': 'error',
                    'message': 'Please fix the form errors.',
                    'errors': errors
                })  # Return 200 with error status so JS can handle it
    else:
        form = EmployeeDocumentForm()
        form.fields['employee'].queryset = get_employee_queryset_for_user(request.user, request, account_lookup='account')
    
    context = {
        'form': form, 
        'hr_current_page': 'documents',
        'is_edit': False,
        'page_title': 'Upload Document',
    }
    response = render(request, 'hr_staff/document_form.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.add_employee', raise_exception=True)
@never_cache
def document_multi_create(request):
    """Multi-document upload with smart extraction."""
    from .models import EmployeeDocument
    import json
    
    # Handle AJAX upload
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' and request.method == 'POST':
        files = request.FILES.getlist('files')
        employee_id = request.POST.get('employee')
        document_type = request.POST.get('document_type', 'other')
        
        if not files:
            return JsonResponse({'status': 'error', 'message': 'No files provided'}, status=400)
        
        account = get_account_for_user(request.user)
        created_docs = []
        
        for file in files:
            try:
                # Read and extract
                file_content = file.read()
                filename = file.name
                
                # Try extraction
                extraction_result = {}
                try:
                    from .cv_extraction import extract_cv_information
                    extraction_result = extract_cv_information(file_content, filename)
                except:
                    pass
                
                # Auto-detect document type
                doc_type = document_type
                title = filename
                
                text = extraction_result.get('extracted_text', '') or ''
                text_lower = text.lower()
                
                # Smart detection
                if 'cv' in filename.lower() or 'resume' in filename.lower() or 'work experience' in text_lower:
                    doc_type = 'other'
                elif 'contract' in filename.lower() or 'employment' in text_lower:
                    doc_type = 'contract'
                elif 'certificate' in filename.lower() or 'certification' in text_lower:
                    doc_type = 'certificate'
                elif 'id' in filename.lower():
                    doc_type = 'id_card'
                
                # Create document
                doc = EmployeeDocument(
                    account=account,
                    created_by=request.user,
                    employee_id=employee_id if employee_id else None,
                    document_type=doc_type,
                    title=extraction_result.get('name', title) or title,
                    file=file,
                )
                doc.save()
                created_docs.append({
                    'id': doc.id,
                    'title': doc.title,
                    'document_type': doc.get_document_type_display()
                })
                
            except Exception as e:
                continue
        
        return JsonResponse({
            'status': 'success',
            'message': f'{len(created_docs)} document(s) uploaded successfully',
            'documents': created_docs
        })
    
    # GET - show multi-upload form
    from .querysets import get_employee_queryset_for_user
    employees = get_employee_queryset_for_user(request.user, request, account_lookup='account')
    
    context = {
        'hr_current_page': 'documents',
        'employees': employees,
        'document_types': EmployeeDocument.DOCUMENT_TYPE_CHOICES
    }
    response = render(request, 'hr_staff/document_multi_form.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.view_employee', raise_exception=True)
@never_cache
def document_detail(request, pk):
    """View document detail with extracted data if available."""
    from .querysets import get_employee_document_queryset_for_user
    import json
    qs = get_employee_document_queryset_for_user(request.user, request, account_lookup='account')
    doc, resp = get_object_or_unauthorized(request, qs.select_related('employee'), pk=pk)
    if resp:
        return resp
    
    # Parse extracted data if available
    extracted_data = {}
    if doc.extracted_data_json:
        try:
            extracted_data = json.loads(doc.extracted_data_json)
        except:
            pass
    
    context = {
        'document': doc, 
        'hr_current_page': 'documents',
        'extracted_data': extracted_data
    }
    response = render(request, 'hr_staff/document_detail.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.change_employee', raise_exception=True)
@never_cache
def document_edit(request, pk):
    """Edit document with extracted data pre-population."""
    from .models import EmployeeDocument
    from .querysets import get_employee_document_queryset_for_user
    import json
    
    qs = get_employee_document_queryset_for_user(request.user, request, account_lookup='account')
    doc, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return resp
    
    # Handle AJAX extraction request
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' and request.method == 'POST':
        file = request.FILES.get('file')
        if file:
            try:
                file_content = file.read()
                filename = file.name
                
                from .cv_extraction import extract_cv_information
                extraction_result = extract_cv_information(file_content, filename)
                
                document_type = 'other'
                title = filename
                
                text = extraction_result.get('extracted_text', '')
                text_lower = text.lower() if text else ''
                
                cv_keywords = ['resume', 'curriculum vitae', 'work experience', 'education', 'skills', 'employment']
                contract_keywords = ['contract', 'employment', 'agreement', 'terms of employment', 'salary', 'benefits']
                certificate_keywords = ['certificate', 'certification', 'completion', 'training', 'awarded']
                id_keywords = ['id card', 'passport', 'national id', 'driver license', 'license']
                
                cv_score = sum(1 for kw in cv_keywords if kw in text_lower)
                contract_score = sum(1 for kw in contract_keywords if kw in text_lower)
                certificate_score = sum(1 for kw in certificate_keywords if kw in text_lower)
                id_score = sum(1 for kw in id_keywords if kw in text_lower)
                
                max_score = max(cv_score, contract_score, certificate_score, id_score)
                
                if cv_score == max_score and cv_score > 0:
                    document_type = 'other'
                    title = extraction_result.get('name', filename) or filename
                elif contract_score == max_score and contract_score > 0:
                    document_type = 'contract'
                elif certificate_score == max_score and certificate_score > 0:
                    document_type = 'certificate'
                elif id_score == max_score and id_score > 0:
                    document_type = 'id_card'
                
                filename_lower = filename.lower()
                if 'cv' in filename_lower or 'resume' in filename_lower:
                    document_type = 'other'
                elif 'contract' in filename_lower:
                    document_type = 'contract'
                elif 'certificate' in filename_lower or 'cert' in filename_lower:
                    document_type = 'certificate'
                elif 'id' in filename_lower:
                    document_type = 'id_card'
                
                return JsonResponse({
                    'status': 'success',
                    'extraction': {
                        'document_type': document_type,
                        'title': title,
                        'name': extraction_result.get('name', ''),
                        'email': extraction_result.get('email', ''),
                        'phone': extraction_result.get('phone', []),
                        'skills': extraction_result.get('skills', {}),
                        'education': extraction_result.get('education', []),
                        'work_experience': extraction_result.get('work_experience', []),
                        'position_applied': extraction_result.get('position_applied', ''),
                        'years_of_experience': extraction_result.get('years_of_experience', ''),
                        'address': extraction_result.get('address', ''),
                        'extracted_text': text[:2000] if text else '',
                        'extraction_success': extraction_result.get('extraction_success', False),
                    }
                })
            except Exception as e:
                return JsonResponse({
                    'status': 'error',
                    'message': str(e)
                }, status=500)
    
    if request.method == 'POST':
        form = EmployeeDocumentForm(request.POST, request.FILES, instance=doc)
        
        extracted_json = request.POST.get('extracted_json', '')
        extracted_data = {}
        if extracted_json:
            try:
                extracted_data = json.loads(extracted_json)
            except:
                pass
        
        if form.is_valid():
            doc = form.save(commit=False)
            
            if extracted_data:
                try:
                    from django.utils import timezone
                    doc.extracted_data_json = json.dumps(extracted_data)
                    doc.extracted_at = timezone.now()
                    
                    if extracted_data.get('skills') or extracted_data.get('education') or extracted_data.get('work_experience'):
                        doc.document_type = 'cv'
                except:
                    pass
            
            doc.save()
            messages.success(request, 'Document updated.')
            return redirect('hr_staff:document_detail', pk=doc.pk)
    else:
        form = EmployeeDocumentForm(instance=doc)
        form.fields['employee'].queryset = get_employee_queryset_for_user(request.user, request, account_lookup='account')
    
    # Get existing extracted data for display
    existing_extracted = {}
    if doc.extracted_data_json:
        try:
            existing_extracted = json.loads(doc.extracted_data_json)
        except:
            pass
    
    context = {
        'form': form, 
        'hr_current_page': 'documents',
        'document': doc,
        'existing_extracted': existing_extracted,
        'is_edit': True
    }
    response = render(request, 'hr_staff/document_form.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.delete_employee', raise_exception=True)
@require_POST
@never_cache
def document_delete(request, pk):
    """Delete document."""
    qs = get_employee_document_queryset_for_user(request.user, request, account_lookup='account')
    doc, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return resp
    title = doc.title
    doc.delete()
    messages.success(request, 'Document deleted.')
    return redirect('hr_staff:document_list')


# ----- HR Analytics -----

@login_required
@company_admin_or_permission_required('hr_staff.view_hr_dashboard', raise_exception=True)
@never_cache
def hr_analytics(request):
    """HR Analytics dashboard."""
    context = {'hr_current_page': 'analytics'}
    response = render(request, 'hr_staff/hr_analytics.html', context)
    apply_no_cache_headers(response)
    return response


# ----- Org Chart -----

@login_required
@company_admin_or_permission_required('hr_staff.view_employee', raise_exception=True)
@never_cache
def org_chart(request):
    """Organization chart view."""
    context = {'hr_current_page': 'org_chart'}
    response = render(request, 'hr_staff/org_chart.html', context)
    apply_no_cache_headers(response)
    return response


# ----- Job Seekers -----

@login_required
@company_admin_or_permission_required('hr_staff.view_employee', raise_exception=True)
@never_cache
def job_seeker_list(request):
    """Job Seekers list with CVs."""
    search = (request.GET.get('search') or '').strip()
    status_filter = request.GET.get('status', '')
    
    account = get_account_for_user(request.user)
    if not account:
        messages.error(request, 'No account found. Please contact support.')
        return redirect('hr_staff:dashboard')
    
    from .models import JobSeeker
    queryset = JobSeeker.objects.filter(account=account)
    
    if search:
        queryset = queryset.filter(
            Q(full_name__icontains=search) |
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(email__icontains=search) |
            Q(phone__icontains=search) |
            Q(position_applied__icontains=search)
        )
    
    if status_filter:
        queryset = queryset.filter(status=status_filter)
    
    job_seekers = queryset[:100]
    status_counts = JobSeeker.objects.filter(account=account).values('status').annotate(count=Count('id'))
    
    context = {
        'job_seekers': job_seekers,
        'search_query': search,
        'status_filter': status_filter,
        'status_counts': status_counts,
        'hr_current_page': 'job_seekers',
    }
    response = render(request, 'hr_staff/job_seeker_list.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.view_employee', raise_exception=True)
@never_cache
def job_seeker_detail(request, pk):
    """Job Seeker detail with CV document view."""
    account = get_account_for_user(request.user)
    if not account:
        messages.error(request, 'No account found. Please contact support.')
        return redirect('hr_staff:dashboard')
    
    from .models import JobSeeker, JobSeekerDocument
    qs = JobSeeker.objects.filter(account=account)
    job_seeker, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return resp
    
    # Get all documents for this job seeker
    documents = JobSeekerDocument.objects.filter(job_seeker=job_seeker).order_by('-id')
    
    context = {
        'job_seeker': job_seeker,
        'documents': documents,
        'hr_current_page': 'job_seekers',
    }
    response = render(request, 'hr_staff/job_seeker_detail.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('hr_staff.add_employee', raise_exception=True)
@never_cache
def job_seeker_create(request):
    """Create a new Job Seeker with CV upload and auto-extraction."""
    account = get_account_for_user(request.user)
    company = get_company_profile_for_user(request.user, request)
    
    if not account:
        messages.error(request, 'No account found. Please contact support.')
        return redirect('hr_staff:dashboard')
    
    from .forms import JobSeekerForm
    from .models import JobSeeker, JobSeekerDocument
    from .cv_extraction import extract_cv_information
    
    extracted_data = {}
    
    if request.method == 'POST':
        form = JobSeekerForm(request.POST, request.FILES)
        
        # Check if main cv_file was uploaded
        cv_file = request.FILES.get('cv_file')
        
        if cv_file:
            try:
                file_content = cv_file.read()
                cv_file.seek(0)
                
                extracted = extract_cv_information(file_content, cv_file.name)
                extracted_data = extracted
                
                if extracted.get('raw_text'):
                    request.session['cv_raw_text'] = extracted['raw_text'][:5000]
                    
            except Exception as e:
                logger.error(f"CV extraction error: {e}")
        
        # Also check multiple files
        cv_files = request.FILES.getlist('cv_files')
        
        if cv_files and not extracted_data:
            for cv_file in cv_files:
                if cv_file:
                    try:
                        file_content = cv_file.read()
                        cv_file.seek(0)
                        
                        extracted = extract_cv_information(file_content, cv_file.name)
                        extracted_data = extracted
                        
                        if extracted.get('raw_text'):
                            request.session['cv_raw_text'] = extracted['raw_text'][:5000]
                        
                    except Exception as e:
                        logger.error(f"CV extraction error: {e}")
        
        if form.is_valid():
            # Check for duplicates before saving
            duplicates = form.find_duplicates(account)
            
            # Handle duplicate confirmation
            confirm_duplicate = request.POST.get('confirm_duplicate', 'false').lower() == 'true'
            
            if duplicates and not confirm_duplicate:
                # Show warning and ask for confirmation
                context = {
                    'form': form,
                    'extracted_data': extracted_data,
                    'hr_current_page': 'job_seekers',
                    'duplicates': duplicates,
                    'show_duplicate_warning': True,
                }
                return render(request, 'hr_staff/job_seeker_form.html', context)
            
            obj = form.save(commit=False)
            obj.account = account
            obj.company = company
            obj.created_by = request.user
            
            # Use extracted data to fill fields if they're empty
            if extracted_data:
                if not obj.full_name and extracted_data.get('name'):
                    obj.full_name = extracted_data['name']
                if not obj.email and extracted_data.get('email'):
                    obj.email = extracted_data['email']
                if not obj.phone and extracted_data.get('phone'):
                    phone_list = extracted_data.get('phone', [])
                    # Store all phone numbers separated by comma
                    if isinstance(phone_list, list) and phone_list:
                        obj.phone = ', '.join(phone_list)
                    else:
                        obj.phone = str(phone_list)
                if not obj.address and extracted_data.get('address'):
                    obj.address = extracted_data['address']
                if not obj.position_applied and extracted_data.get('position_applied'):
                    obj.position_applied = extracted_data['position_applied']
                if not obj.years_of_experience and extracted_data.get('years_of_experience'):
                    obj.years_of_experience = extracted_data['years_of_experience']
                    
                # Skills - convert dict to string
                skills = extracted_data.get('skills', {})
                if skills and not obj.skills:
                    if isinstance(skills, dict):
                        skill_list = []
                        for category, skill_items in skills.items():
                            skill_list.extend(skill_items)
                        obj.skills = ', '.join(skill_list)
                    else:
                        obj.skills = str(skills)
                        
                # Education - convert list to string
                education = extracted_data.get('education', [])
                if education and not obj.education:
                    if isinstance(education, list):
                        # Check for full_text first (complete section)
                        for edu in education:
                            if isinstance(edu, dict) and edu.get('full_text'):
                                obj.education = edu['full_text']
                                break
                        else:
                            # Fallback: parse individual entries
                            edu_texts = []
                            for edu in education:
                                if isinstance(edu, dict):
                                    parts = []
                                    if edu.get('degree'): parts.append(edu['degree'])
                                    if edu.get('institution'): parts.append(edu['institution'])
                                    if edu.get('year'): parts.append(edu['year'])
                                    if edu.get('text'): parts.append(edu['text'])
                                    if parts:
                                        edu_texts.append(' - '.join(parts))
                                else:
                                    edu_texts.append(str(edu))
                            obj.education = '\n'.join(edu_texts)
                    else:
                        obj.education = str(education)
                        
                # Work experience - convert list to string
                experience = extracted_data.get('work_experience', [])
                if experience and not obj.work_experience:
                    if isinstance(experience, list):
                        # Check for full_text first (complete section)
                        for exp in experience:
                            if isinstance(exp, dict) and exp.get('full_text'):
                                obj.work_experience = exp['full_text']
                                break
                        else:
                            # Fallback: parse individual entries
                            exp_texts = []
                            for exp in experience:
                                if isinstance(exp, dict):
                                    parts = []
                                    if exp.get('position'): parts.append(exp['position'])
                                    if exp.get('company'): parts.append(exp['company'])
                                    if exp.get('period'): parts.append(exp['period'])
                                    if exp.get('text'): parts.append(exp['text'])
                                    if parts:
                                        exp_texts.append(' - '.join(parts))
                                else:
                                    exp_texts.append(str(exp))
                            obj.work_experience = '\n'.join(exp_texts)
                    else:
                        obj.work_experience = str(experience)
                        
                if extracted_data.get('raw_text'):
                    obj.extracted_text = extracted_data['raw_text']
            
            if request.FILES.get('cv_file'):
                obj.cv_file_name = request.FILES['cv_file'].name
                obj.cv_uploaded_at = now()
                
                # Extract from main CV file
                try:
                    cv_file = request.FILES['cv_file']
                    cv_file.seek(0)
                    file_content = cv_file.read()
                    cv_file.seek(0)
                    
                    extracted = extract_cv_information(file_content, cv_file.name)
                    if extracted.get('raw_text'):
                        obj.extracted_text = extracted['raw_text']
                    
                    # Also populate fields from main CV file if not already set
                    if extracted.get('phone'):
                        phone_list = extracted.get('phone', [])
                        if isinstance(phone_list, list) and phone_list:
                            if not obj.phone:
                                obj.phone = ', '.join(phone_list)
                            elif obj.phone:
                                # Append to existing phones
                                existing = obj.phone.split(', ') if ', ' in obj.phone else [obj.phone]
                                all_phones = existing + phone_list
                                obj.phone = ', '.join(list(dict.fromkeys(all_phones)))  # Remove duplicates
                    
                    if extracted.get('email') and not obj.email:
                        obj.email = extracted.get('email')
                    if extracted.get('name') and not obj.full_name:
                        obj.full_name = extracted.get('name')
                    if extracted.get('skills') and not obj.skills:
                        skills = extracted.get('skills', {})
                        if isinstance(skills, dict):
                            skill_list = []
                            for category, skill_items in skills.items():
                                skill_list.extend(skill_items)
                            obj.skills = ', '.join(skill_list)
                    if extracted.get('education') and not obj.education:
                        education = extracted.get('education', [])
                        if education and isinstance(education, list):
                            for edu in education:
                                if isinstance(edu, dict) and edu.get('full_text'):
                                    obj.education = edu['full_text']
                                    break
                    if extracted.get('work_experience') and not obj.work_experience:
                        experience = extracted.get('work_experience', [])
                        if experience and isinstance(experience, list):
                            for exp in experience:
                                if isinstance(exp, dict) and exp.get('full_text'):
                                    obj.work_experience = exp['full_text']
                                    break
                                    
                except Exception as e:
                    logger.error(f"Main CV extraction error: {e}")
            
            obj.save()
            
            # Handle multiple document uploads
            cv_files = request.FILES.getlist('cv_files')
            for cv_file in cv_files:
                if cv_file:
                    doc = JobSeekerDocument(
                        job_seeker=obj,
                        document_type='cv',
                        file=cv_file,
                        file_name=cv_file.name,
                        file_size=cv_file.size,
                    )
                    doc.save()
                    
                    # Extract from additional documents
                    try:
                        cv_file.seek(0)
                        file_content = cv_file.read()
                        cv_file.seek(0)
                        
                        extracted = extract_cv_information(file_content, cv_file.name)
                        doc.extracted_text = extracted.get('raw_text', '')
                        doc.extracted_email = extracted.get('email', '')
                        doc.extracted_phone = extracted.get('phone', '')
                        doc.extracted_name = extracted.get('name', '')
                        doc.extracted_skills = extracted.get('skills', '')
                        doc.extracted_education = extracted.get('education', '')
                        doc.extracted_experience = extracted.get('work_experience', '')
                        doc.extraction_success = extracted.get('extraction_success', False)
                        doc.extraction_error = extracted.get('error', '')
                        doc.save()
                    except Exception as e:
                        logger.error(f"Document extraction error: {e}")
            
            messages.success(request, 'Job seeker added successfully!')
            if extracted_data and extracted_data.get('extraction_success'):
                messages.info(request, 'Information was automatically extracted from the uploaded CV.')
            return redirect('hr_staff:job_seeker_detail', pk=obj.pk)
    else:
        form = JobSeekerForm()
    
    context = {
        'form': form,
        'extracted_data': extracted_data,
        'hr_current_page': 'job_seekers',
    }
    return render(request, 'hr_staff/job_seeker_form.html', context)


@login_required
@company_admin_or_permission_required('hr_staff.add_employee', raise_exception=True)
@never_cache
def job_seeker_edit(request, pk):
    """Edit an existing Job Seeker."""
    account = get_account_for_user(request.user)
    if not account:
        messages.error(request, 'No account found. Please contact support.')
        return redirect('hr_staff:dashboard')
    
    from .models import JobSeeker, JobSeekerDocument
    from .cv_extraction import extract_cv_information
    
    qs = JobSeeker.objects.filter(account=account)
    job_seeker, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return resp
    
    from .forms import JobSeekerForm
    
    if request.method == 'POST':
        form = JobSeekerForm(request.POST, request.FILES, instance=job_seeker)
        
        # Handle new document uploads
        cv_files = request.FILES.getlist('cv_files')
        
        if form.is_valid():
            # Check for duplicates before saving (excluding current record)
            duplicates = form.find_duplicates(account)
            
            # Handle duplicate confirmation
            confirm_duplicate = request.POST.get('confirm_duplicate', 'false').lower() == 'true'
            
            if duplicates and not confirm_duplicate:
                # Show warning and ask for confirmation
                context = {
                    'form': form,
                    'job_seeker': job_seeker,
                    'hr_current_page': 'job_seekers',
                    'duplicates': duplicates,
                    'show_duplicate_warning': True,
                }
                return render(request, 'hr_staff/job_seeker_form.html', context)
            
            obj = form.save(commit=False)
            
            # Handle new document uploads
            for cv_file in cv_files:
                if cv_file:
                    doc = JobSeekerDocument(
                        job_seeker=obj,
                        document_type='cv',
                        file=cv_file,
                        file_name=cv_file.name,
                        file_size=cv_file.size,
                    )
                    doc.save()
                    
                    # Extract from document
                    try:
                        cv_file.seek(0)
                        file_content = cv_file.read()
                        cv_file.seek(0)
                        
                        extracted = extract_cv_information(file_content, cv_file.name)
                        doc.extracted_text = extracted.get('raw_text', '')
                        doc.extracted_email = extracted.get('email', '')
                        doc.extracted_phone = extracted.get('phone', '')
                        doc.extracted_name = extracted.get('name', '')
                        doc.extracted_skills = extracted.get('skills', '')
                        doc.extracted_education = extracted.get('education', '')
                        doc.extracted_experience = extracted.get('work_experience', '')
                        doc.extraction_success = extracted.get('extraction_success', False)
                        doc.extraction_error = extracted.get('error', '')
                        doc.save()
                    except Exception as e:
                        logger.error(f"Document extraction error: {e}")
            
            if request.FILES.get('cv_file'):
                obj.cv_file_name = request.FILES['cv_file'].name
                obj.cv_uploaded_at = now()
                
                # Extract from main CV
                try:
                    cv_file = request.FILES['cv_file']
                    cv_file.seek(0)
                    file_content = cv_file.read()
                    cv_file.seek(0)
                    
                    extracted = extract_cv_information(file_content, cv_file.name)
                    if extracted.get('raw_text'):
                        obj.extracted_text = extracted['raw_text']
                except Exception as e:
                    logger.error(f"Main CV extraction error: {e}")
            
            obj.save()
            messages.success(request, 'Job seeker updated successfully!')
            return redirect('hr_staff:job_seeker_detail', pk=obj.pk)
    else:
        form = JobSeekerForm(instance=job_seeker)
    
    context = {
        'form': form,
        'job_seeker': job_seeker,
        'hr_current_page': 'job_seekers',
    }
    return render(request, 'hr_staff/job_seeker_form.html', context)


@login_required
@company_admin_or_permission_required('hr_staff.delete_leaverequest', raise_exception=True)
@never_cache
def job_seeker_delete(request, pk):
    """Delete a job seeker (GET: confirm, POST: delete)."""
    account = get_account_for_user(request.user)
    from .models import JobSeeker
    qs = JobSeeker.objects.filter(account=account)
    job_seeker, resp = get_object_or_unauthorized(request, qs, pk=pk)
    if resp:
        return resp
    if request.method == 'POST':
        name = job_seeker.name or f"JobSeeker {job_seeker.pk}"
        job_seeker.delete()
        messages.success(request, f'Job seeker "{name}" has been deleted.')
        return redirect('hr_staff:job_seeker_list')
    context = {'job_seeker': job_seeker, 'hr_current_page': 'job_seekers'}
    response = render(request, 'hr_staff/job_seeker_confirm_delete.html', context)
    apply_no_cache_headers(response)
    return response


from django.utils import timezone
now = timezone.now
