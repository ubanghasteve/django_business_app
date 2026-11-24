# -*- coding: utf-8 -*-
"""
HR & Staff API: ViewSets for Department, Employee, LeaveRequest.
Uses drf_filter_queryset_for_user(account_lookup='account') for tenant + visibility.
Real-time: dashboard_widgets, hr_notifications for polling without page refresh.
"""
from django.db.models import Count
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend

from apps.core.permissions import DjangoModelPermissions
from apps.core.ownership import drf_filter_queryset_for_user, get_account_for_user, is_company_admin
from apps.core.utils import get_company_profile_for_user

from .models import Department, Employee, LeaveRequest
from .forms import get_account_users_without_employee
from .querysets import (
    get_employee_queryset_for_user,
    get_leave_queryset_for_user,
    get_department_queryset_for_employee_form,
)
from .serializers import DepartmentSerializer, EmployeeSerializer, LeaveRequestSerializer


class DepartmentViewSet(viewsets.ModelViewSet):
    """CRUD for Departments. Uses HR app visibility so employees see all account departments in form dropdown."""
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = DepartmentSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['name', 'manager_name']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']

    def get_queryset(self):
        return get_department_queryset_for_employee_form(self.request.user, self.request)

    def perform_create(self, serializer):
        account = get_account_for_user(self.request.user)
        serializer.save(account=account, created_by=self.request.user)


class EmployeeViewSet(viewsets.ModelViewSet):
    """CRUD for Employees. Tenant-scoped. Search and status filter for real-time list sync."""
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = EmployeeSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status']
    search_fields = ['first_name', 'last_name', 'position', 'email']
    ordering_fields = ['first_name', 'last_name', 'created_at', 'date_joined']
    ordering = ['first_name', 'last_name']

    def get_queryset(self):
        return get_employee_queryset_for_user(
            self.request.user, self.request, account_lookup='account'
        ).select_related('department', 'linked_user')

    def perform_create(self, serializer):
        account = get_account_for_user(self.request.user)
        company = get_company_profile_for_user(self.request.user, self.request)
        serializer.save(
            account=account,
            company=company,
            created_by=self.request.user
        )


class HRLeaveRequestPagination(PageNumberPagination):
    """Allow page_size up to 500 so leave list page can fetch all for accurate stats/table."""
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 500


class LeaveRequestViewSet(viewsets.ModelViewSet):
    """CRUD for LeaveRequests. Tenant-scoped. Status/leave_type filter for real-time list sync."""
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = LeaveRequestSerializer
    pagination_class = HRLeaveRequestPagination
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['status', 'leave_type']
    ordering_fields = ['start_date', 'end_date', 'created_at']
    ordering = ['-start_date']

    def get_queryset(self):
        return get_leave_queryset_for_user(
            self.request.user, self.request, account_lookup='account'
        ).select_related('employee')

    def perform_create(self, serializer):
        account = get_account_for_user(self.request.user)
        serializer.save(account=account, created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def status_update(self, request, pk=None):
        """POST with status=approved|rejected to update leave status."""
        obj = self.get_object()
        status_val = (request.data.get('status') or '').strip().lower()
        if status_val in ('approved', 'rejected'):
            obj.status = status_val
            obj.save()
            serializer = self.get_serializer(obj)
            return Response(serializer.data)
        return Response({'detail': 'Invalid status. Use approved or rejected.'}, status=400)


from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from apps.core.ownership import is_company_admin


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_stats_api(request):
    """
    API endpoint for dashboard stats. Uses drf_filter_queryset_for_user.
    Permission: company admin, view_hr_dashboard, view_own_hr_dashboard, or view_employee (sync with app access).
    """
    if not (request.user.is_superuser or is_company_admin(request.user, request) or
            request.user.has_perm('hr_staff.view_hr_dashboard') or request.user.has_perm('hr_staff.view_own_hr_dashboard') or request.user.has_perm('hr_staff.view_employee')):
        return Response({'detail': 'Permission denied'}, status=403)
    employees_qs = get_employee_queryset_for_user(
        request.user, request, account_lookup='account'
    )
    departments_qs = drf_filter_queryset_for_user(
        Department.objects.all(), request, account_lookup='account'
    )
    leaves_qs = get_leave_queryset_for_user(
        request.user, request, account_lookup='account'
    )
    return Response({
        'total_employees': employees_qs.count(),
        'active_employees': employees_qs.filter(status='active').count(),
        'total_departments': departments_qs.count(),
        'pending_leaves': leaves_qs.filter(status='pending').count(),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_widgets_api(request):
    """
    Single endpoint for dashboard real-time widgets: stats, recent employees,
    recent leave requests, department overview. Poll this to update without refresh.
    """
    if not (request.user.is_superuser or is_company_admin(request.user, request) or
            request.user.has_perm('hr_staff.view_hr_dashboard') or request.user.has_perm('hr_staff.view_own_hr_dashboard') or request.user.has_perm('hr_staff.view_employee')):
        return Response({'detail': 'Permission denied'}, status=403)
    company = get_company_profile_for_user(request.user, request)
    currency_symbol = getattr(company, 'currency_symbol', '$') if company else '$'

    employees_qs = get_employee_queryset_for_user(
        request.user, request, account_lookup='account'
    ).select_related('department', 'linked_user')
    departments_qs = drf_filter_queryset_for_user(
        Department.objects.all(), request, account_lookup='account'
    )
    leaves_qs = get_leave_queryset_for_user(
        request.user, request, account_lookup='account'
    ).select_related('employee', 'employee__department')

    stats = {
        'total_employees': employees_qs.count(),
        'active_employees': employees_qs.filter(status='active').count(),
        'total_departments': departments_qs.count(),
        'pending_leaves': leaves_qs.filter(status='pending').count(),
    }

    recent_employees = employees_qs.order_by('-created_at')[:6]
    leave_requests = leaves_qs.order_by('-start_date')[:6]
    departments_overview = departments_qs.annotate(
        employee_count=Count('employees')
    ).order_by('name')

    return Response({
        'stats': stats,
        'user_currency_symbol': currency_symbol,
        'recent_employees': EmployeeSerializer(
            recent_employees, many=True, context={'request': request}
        ).data,
        'leave_requests': LeaveRequestSerializer(
            leave_requests, many=True, context={'request': request}
        ).data,
        'departments_overview': [
            {
                'id': d.id,
                'name': d.name,
                'manager_name': d.manager_name or '',
                'budget': str(d.budget or 0),
                'employee_count': d.employee_count,
            }
            for d in departments_overview
        ],
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def hr_notifications_api(request):
    """
    HR-specific notifications for the nav modal: pending leave count,
    new employees, etc. Real-time; poll to update without refresh.
    """
    if not (request.user.is_superuser or is_company_admin(request.user, request) or
            request.user.has_perm('hr_staff.view_hr_dashboard') or request.user.has_perm('hr_staff.view_own_hr_dashboard') or request.user.has_perm('hr_staff.view_employee')):
        return Response({'detail': 'Permission denied'}, status=403)
    leaves_qs = get_leave_queryset_for_user(
        request.user, request, account_lookup='account'
    ).select_related('employee')
    employees_qs = get_employee_queryset_for_user(
        request.user, request, account_lookup='account'
    )
    departments_qs = drf_filter_queryset_for_user(
        Department.objects.all(), request, account_lookup='account'
    )
    from django.utils.dateformat import DateFormat
    from apps.accounts.models import AccountGroup

    today = timezone.now().date()
    pending_leaves = leaves_qs.filter(status='pending').order_by('-created_at')[:10]
    new_today = employees_qs.filter(created_at__date=today).select_related('linked_user').order_by('-created_at')[:5]
    new_departments_today = departments_qs.filter(created_at__date=today).order_by('-created_at')[:5]
    notifications = []
    for leave in pending_leaves:
        created = leave.created_at
        notifications.append({
            'type': 'info',
            'title': 'Pending Leave Request',
            'message': f'{leave.employee.full_name} – {leave.get_leave_type_display()} ({leave.start_date} to {leave.end_date})',
            'action_url': f'/hr-staff/leave/{leave.id}/',
            'timestamp': created.isoformat(),
            'created_display': DateFormat(created).format('j M Y, g:i A') if created else '',
            'priority': 'medium',
        })
    for emp in new_today:
        created = emp.created_at
        date_str = DateFormat(created).format('j M Y') if created else ''
        time_str = DateFormat(created).format('g:i A') if created else ''
        role_display = '—'
        if getattr(emp, 'linked_user_id', None) and emp.linked_user_id:
            role_names = list(
                AccountGroup.objects.filter(
                    account_id=emp.account_id,
                    group__in=emp.linked_user.groups.all(),
                ).values_list('role_name', flat=True).order_by('role_name')
            )
            role_display = ', '.join(role_names) if role_names else '—'
        message = f'{emp.full_name} was added on {date_str} at {time_str}. Role: {role_display}.'
        notifications.append({
            'type': 'info',
            'title': 'New Employee',
            'message': message,
            'action_url': f'/hr-staff/employees/{emp.id}/',
            'timestamp': emp.created_at.isoformat(),
            'created_display': DateFormat(emp.created_at).format('j M Y, g:i A') if emp.created_at else '',
            'priority': 'low',
        })
    for dept in new_departments_today:
        created = dept.created_at
        date_str = DateFormat(created).format('j M Y') if created else ''
        time_str = DateFormat(created).format('g:i A') if created else ''
        message = f'Department "{dept.name}" was created on {date_str} at {time_str}.'
        notifications.append({
            'type': 'info',
            'title': 'New Department',
            'message': message,
            'action_url': f'/hr-staff/departments/{dept.id}/',
            'timestamp': dept.created_at.isoformat(),
            'created_display': DateFormat(dept.created_at).format('j M Y, g:i A') if dept.created_at else '',
            'priority': 'low',
        })
    notifications.sort(key=lambda x: x['timestamp'], reverse=True)
    return Response({
        'notifications': notifications[:15],
        'unread_count': len(notifications),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def account_users_without_employee_api(request):
    """Users in account without an Employee profile (for create-employee form dropdown)."""
    if not (request.user.is_superuser or is_company_admin(request.user, request) or
            request.user.has_perm('hr_staff.add_employee') or request.user.has_perm('hr_staff.view_hr_dashboard')):
        return Response({'detail': 'Permission denied'}, status=403)
    account = get_account_for_user(request.user)
    if not account:
        return Response({'results': []})
    qs = get_account_users_without_employee(account)
    results = [
        {'id': u.id, 'email': u.email or '', 'first_name': u.first_name or '', 'last_name': u.last_name or ''}
        for u in qs[:500]
    ]
    return Response({'results': results})
