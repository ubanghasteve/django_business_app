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
from django.shortcuts import render, redirect, get_object_or_404
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
from .forms import DepartmentForm, EmployeeForm, LeaveRequestForm, get_account_users_without_employee
from .querysets import (
    get_employee_queryset_for_user,
    get_leave_queryset_for_user,
    get_linked_employee_for_user,
    get_department_queryset_for_employee_form,
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
    """Log activity for the employee's linked user so they see the update on their dashboard."""
    emp = leave_req.employee
    if not emp or not emp.linked_user_id:
        return
    from apps.accounts.models import UserActivity
    UserActivity.log_activity(
        user=emp.linked_user,
        account=leave_req.account,
        activity_type='UPDATE',
        description=f'Your leave request ({leave_req.start_date}–{leave_req.end_date}) was {status_val}.',
        app_name='hr_staff',
        model_name='LeaveRequest',
        object_id=str(leave_req.pk),
        object_repr=str(leave_req),
        url_path=request.build_absolute_uri(f'/hr-staff/leave/{leave_req.pk}/'),
        http_method=request.method,
        ip_address=(request.META.get('HTTP_X_FORWARDED_FOR') or request.META.get('REMOTE_ADDR')) if request else None,
    )


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
