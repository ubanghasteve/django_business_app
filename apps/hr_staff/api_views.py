# -*- coding: utf-8 -*-
"""
HR & Staff API: ViewSets for Department, Employee, LeaveRequest, Attendance, Performance, Training, Documents.
Uses drf_filter_queryset_for_user(account_lookup='account') for tenant + visibility.
Real-time: dashboard_widgets, hr_notifications for polling without page refresh.
"""
from datetime import date, datetime, timedelta
from django.db.models import Count, Q, Sum
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

from .models import (
    Department, Employee, LeaveRequest, LeavePolicy, Attendance,
    PerformanceReview, PerformanceGoal, PerformanceEvaluation,
    TrainingCourse, TrainingEnrollment, EmployeeDocument, AttendanceSetting
)
from .forms import get_account_users_without_employee
from .querysets import (
    get_employee_queryset_for_user,
    get_leave_queryset_for_user,
    get_department_queryset_for_employee_form,
    get_attendance_queryset_for_user,
    get_performance_review_queryset_for_user,
    get_performance_goal_queryset_for_user,
    get_training_course_queryset_for_user,
    get_training_enrollment_queryset_for_user,
    get_employee_document_queryset_for_user,
    get_leave_policy_queryset_for_user,
    get_linked_employee_for_user,
)
from .serializers import (
    DepartmentSerializer, EmployeeSerializer, EmployeeDetailSerializer,
    LeaveRequestSerializer, LeavePolicySerializer, AttendanceSerializer,
    AttendanceSettingsSerializer, PerformanceReviewSerializer,
    PerformanceGoalSerializer, PerformanceEvaluationSerializer,
    TrainingCourseSerializer, TrainingEnrollmentSerializer,
    EmployeeDocumentSerializer,
)


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


class LeavePolicyViewSet(viewsets.ModelViewSet):
    """CRUD for LeavePolicy."""
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = LeavePolicySerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['name', 'leave_type']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']

    def get_queryset(self):
        return get_leave_policy_queryset_for_user(
            self.request.user, self.request, account_lookup='account'
        )

    def perform_create(self, serializer):
        account = get_account_for_user(self.request.user)
        serializer.save(account=account, created_by=self.request.user)


class AttendanceViewSet(viewsets.ModelViewSet):
    """CRUD for Attendance records."""
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = AttendanceSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status', 'employee', 'date']
    search_fields = ['employee__first_name', 'employee__last_name']
    ordering_fields = ['date', 'created_at']
    ordering = ['-date']

    def get_queryset(self):
        return get_attendance_queryset_for_user(
            self.request.user, self.request, account_lookup='account'
        ).select_related('employee')

    def perform_create(self, serializer):
        account = get_account_for_user(self.request.user)
        serializer.save(account=account, created_by=self.request.user)

    @action(detail=False, methods=['post'])
    def check_in(self, request):
        """Employee check-in for today."""
        employee_id = request.data.get('employee_id')
        if not employee_id:
            return Response({'detail': 'employee_id required'}, status=400)
        
        emp_qs = get_employee_queryset_for_user(request.user, request, account_lookup='account')
        try:
            employee = emp_qs.get(pk=employee_id)
        except Employee.DoesNotExist:
            return Response({'detail': 'Employee not found'}, status=404)
        
        today = date.today()
        attendance, created = Attendance.objects.get_or_create(
            employee=employee,
            date=today,
            defaults={
                'account': get_account_for_user(request.user),
                'check_in': datetime.now().time(),
                'status': 'present',
                'created_by': request.user,
            }
        )
        
        if not created:
            if attendance.check_in:
                return Response({'detail': 'Already checked in'}, status=400)
            attendance.check_in = datetime.now().time()
            attendance.save()
        
        return Response(AttendanceSerializer(attendance).data)

    @action(detail=False, methods=['post'])
    def check_out(self, request):
        """Employee check-out for today."""
        employee_id = request.data.get('employee_id')
        if not employee_id:
            return Response({'detail': 'employee_id required'}, status=400)
        
        emp_qs = get_employee_queryset_for_user(request.user, request, account_lookup='account')
        try:
            employee = emp_qs.get(pk=employee_id)
        except Employee.DoesNotExist:
            return Response({'detail': 'Employee not found'}, status=404)
        
        today = date.today()
        try:
            attendance = Attendance.objects.get(employee=employee, date=today)
        except Attendance.DoesNotExist:
            return Response({'detail': 'No check-in record found'}, status=404)
        
        if attendance.check_out:
            return Response({'detail': 'Already checked out'}, status=400)
        
        attendance.check_out = datetime.now().time()
        
        setting = AttendanceSetting.objects.filter(account=attendance.account).first()
        if setting and attendance.check_in:
            from datetime import datetime as dt
            check_in_dt = dt.combine(today, attendance.check_in)
            threshold_min = setting.late_threshold_minutes or 15
            if (dt.now() - check_in_dt).total_seconds() > threshold_min * 60:
                attendance.status = 'late'
        
        attendance.save()
        return Response(AttendanceSerializer(attendance).data)


class AttendanceSettingsViewSet(viewsets.ModelViewSet):
    """CRUD for AttendanceSettings."""
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = AttendanceSettingsSerializer

    def get_queryset(self):
        account = get_account_for_user(self.request.user)
        if not account:
            return AttendanceSetting.objects.none()
        return AttendanceSetting.objects.filter(account=account)

    def perform_create(self, serializer):
        account = get_account_for_user(self.request.user)
        AttendanceSetting.objects.filter(account=account).delete()
        serializer.save(account=account, created_by=self.request.user)


class PerformanceReviewViewSet(viewsets.ModelViewSet):
    """CRUD for PerformanceReview."""
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = PerformanceReviewSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['title', 'description']
    ordering_fields = ['start_date', 'created_at']
    ordering = ['-start_date']

    def get_queryset(self):
        return get_performance_review_queryset_for_user(
            self.request.user, self.request, account_lookup='account'
        )

    def perform_create(self, serializer):
        account = get_account_for_user(self.request.user)
        serializer.save(account=account, created_by=self.request.user)


class PerformanceGoalViewSet(viewsets.ModelViewSet):
    """CRUD for PerformanceGoal."""
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = PerformanceGoalSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status', 'employee', 'review']
    search_fields = ['title', 'employee__first_name', 'employee__last_name']
    ordering_fields = ['due_date', 'created_at']
    ordering = ['-created_at']

    def get_queryset(self):
        return get_performance_goal_queryset_for_user(
            self.request.user, self.request, account_lookup='account'
        ).select_related('employee', 'review')

    def perform_create(self, serializer):
        account = get_account_for_user(self.request.user)
        serializer.save(account=account, created_by=self.request.user)


class PerformanceEvaluationViewSet(viewsets.ModelViewSet):
    """CRUD for PerformanceEvaluation."""
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = PerformanceEvaluationSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['employee', 'review', 'is_completed']
    ordering_fields = ['created_at']
    ordering = ['-created_at']

    def get_queryset(self):
        account = get_account_for_user(self.request.user)
        if account is None:
            return PerformanceEvaluation.objects.none()
        qs = PerformanceEvaluation.objects.filter(account=account)
        if is_company_admin(self.request.user, self.request):
            return qs
        if self.request.user.has_perm('hr_staff.view_hr_dashboard'):
            return qs
        return qs.filter(evaluator=self.request.user)
    
    def perform_create(self, serializer):
        account = get_account_for_user(self.request.user)
        serializer.save(account=account, created_by=self.request.user, evaluator=self.request.user)


class TrainingCourseViewSet(viewsets.ModelViewSet):
    """CRUD for TrainingCourse."""
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = TrainingCourseSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['title', 'description', 'category']
    ordering_fields = ['title', 'created_at']
    ordering = ['title']

    def get_queryset(self):
        return get_training_course_queryset_for_user(
            self.request.user, self.request, account_lookup='account'
        )

    def perform_create(self, serializer):
        account = get_account_for_user(self.request.user)
        serializer.save(account=account, created_by=self.request.user)


class TrainingEnrollmentViewSet(viewsets.ModelViewSet):
    """CRUD for TrainingEnrollment."""
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = TrainingEnrollmentSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status', 'employee', 'course']
    search_fields = ['employee__first_name', 'employee__last_name', 'course__title']
    ordering_fields = ['enrolled_date', 'created_at']
    ordering = ['-enrolled_date']

    def get_queryset(self):
        return get_training_enrollment_queryset_for_user(
            self.request.user, self.request, account_lookup='account'
        ).select_related('employee', 'course')

    def perform_create(self, serializer):
        account = get_account_for_user(self.request.user)
        serializer.save(account=account, created_by=self.request.user)


class EmployeeDocumentViewSet(viewsets.ModelViewSet):
    """CRUD for EmployeeDocument."""
    permission_classes = [IsAuthenticated]
    serializer_class = EmployeeDocumentSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['document_type', 'employee']
    search_fields = ['title', 'employee__first_name', 'employee__last_name']
    ordering_fields = ['created_at']
    ordering = ['-created_at']

    def get_queryset(self):
        return get_employee_document_queryset_for_user(
            self.request.user, self.request, account_lookup='account'
        ).select_related('employee')

    def perform_create(self, serializer):
        account = get_account_for_user(self.request.user)
        serializer.save(account=account, created_by=self.request.user)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def debug_documents_api(request):
    """Debug endpoint to see all documents in database."""
    from apps.hr_staff.models import EmployeeDocument
    from apps.core.utils import get_account_for_user
    
    account = get_account_for_user(request.user)
    all_docs = EmployeeDocument.objects.all()[:10]
    
    return Response({
        'user': str(request.user),
        'account': str(account) if account else None,
        'total_documents': EmployeeDocument.objects.count(),
        'documents': [
            {
                'id': d.id,
                'title': d.title,
                'account': str(d.account) if d.account else None,
                'created_by': str(d.created_by) if d.created_by else None,
            }
            for d in all_docs
        ]
    })


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def attendance_today_api(request):
    """Get or create today's attendance for logged-in employee."""
    if request.method == 'GET':
        employee = get_linked_employee_for_user(request.user)
        if not employee:
            return Response({'detail': 'No employee profile'}, status=404)
        
        today = date.today()
        attendance = Attendance.objects.filter(employee=employee, date=today).first()
        
        if attendance:
            return Response(AttendanceSerializer(attendance).data)
        
        return Response({
            'checked_in': False,
            'checked_out': False,
            'employee_id': employee.id,
            'employee_name': employee.full_name,
            'date': today.isoformat(),
        })
    
    if request.method == 'POST':
        action_type = request.data.get('action')
        employee = get_linked_employee_for_user(request.user)
        if not employee:
            return Response({'detail': 'No employee profile'}, status=404)
        
        today = date.today()
        
        if action_type == 'check_in':
            attendance, created = Attendance.objects.get_or_create(
                employee=employee,
                date=today,
                defaults={
                    'account': get_account_for_user(request.user),
                    'check_in': datetime.now().time(),
                    'status': 'present',
                    'created_by': request.user,
                }
            )
            if not created and attendance.check_in:
                return Response({'detail': 'Already checked in'}, status=400)
            if not created:
                attendance.check_in = datetime.now().time()
                attendance.save()
            return Response(AttendanceSerializer(attendance).data)
        
        elif action_type == 'check_out':
            try:
                attendance = Attendance.objects.get(employee=employee, date=today)
            except Attendance.DoesNotExist:
                return Response({'detail': 'No check-in record'}, status=404)
            
            if attendance.check_out:
                return Response({'detail': 'Already checked out'}, status=400)
            
            attendance.check_out = datetime.now().time()
            
            setting = AttendanceSetting.objects.filter(account=attendance.account).first()
            if setting and attendance.check_in:
                check_in_dt = datetime.combine(today, attendance.check_in)
                threshold_min = setting.late_threshold_minutes or 15
                if (datetime.now() - check_in_dt).total_seconds() > threshold_min * 60:
                    attendance.status = 'late'
            
            attendance.save()
            return Response(AttendanceSerializer(attendance).data)
        
        return Response({'detail': 'Invalid action'}, status=400)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def attendance_calendar_api(request):
    """Get attendance records for a date range."""
    start_date = request.GET.get('start')
    end_date = request.GET.get('end')
    employee_id = request.GET.get('employee')
    
    if not start_date or not end_date:
        today = date.today()
        start_date = today.replace(day=1)
        next_month = today.replace(day=28) + timedelta(days=4)
        end_date = next_month.replace(day=1) - timedelta(days=1)
    else:
        start_date = date.fromisoformat(start_date)
        end_date = date.fromisoformat(end_date)
    
    qs = get_attendance_queryset_for_user(request.user, request, account_lookup='account')
    
    if employee_id:
        qs = qs.filter(employee_id=employee_id)
    
    qs = qs.filter(date__gte=start_date, date__lte=end_date).select_related('employee')
    
    records = []
    for att in qs:
        records.append({
            'id': att.id,
            'employee_id': att.employee_id,
            'employee_name': att.employee.full_name,
            'date': att.date.isoformat(),
            'check_in': att.check_in.strftime('%H:%M') if att.check_in else None,
            'check_out': att.check_out.strftime('%H:%M') if att.check_out else None,
            'status': att.status,
            'work_hours': att.work_hours,
        })
    
    return Response({'records': records})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def hr_analytics_api(request):
    """HR Analytics: headcount, turnover, leave balances, etc."""
    if not (request.user.is_superuser or is_company_admin(request.user, request) or
            request.user.has_perm('hr_staff.view_hr_dashboard')):
        return Response({'detail': 'Permission denied'}, status=403)
    
    account = get_account_for_user(request.user)
    if not account:
        return Response({})
    
    employees_qs = get_employee_queryset_for_user(request.user, request, account_lookup='account')
    leaves_qs = get_leave_queryset_for_user(request.user, request, account_lookup='account')
    attendance_qs = get_attendance_queryset_for_user(request.user, request, account_lookup='account')
    
    today = date.today()
    current_month_start = today.replace(day=1)
    current_year_start = today.replace(month=1, day=1)
    
    total_employees = employees_qs.count()
    active_employees = employees_qs.filter(status='active').count()
    
    new_hires_this_month = employees_qs.filter(created_at__gte=current_month_start).count()
    
    departed = employees_qs.filter(status='resigned').count()
    turnover_rate = round((departed / total_employees * 100), 1) if total_employees > 0 else 0
    
    pending_leaves = leaves_qs.filter(status='pending').count()
    approved_leaves = leaves_qs.filter(status='approved').count()
    
    attendance_this_month = attendance_qs.filter(date__gte=current_month_start)
    present_days = attendance_this_month.filter(status='present').count()
    late_days = attendance_this_month.filter(status='late').count()
    absent_days = attendance_this_month.filter(status='absent').count()
    total_days = attendance_this_month.count()
    attendance_rate = round((present_days / total_days * 100), 1) if total_days > 0 else 0
    
    by_department = list(
        employees_qs.values('department__name')
        .annotate(count=Count('id'))
        .filter(department__name__isnull=False)
    )
    
    by_status = list(
        employees_qs.values('status')
        .annotate(count=Count('id'))
    )
    
    return Response({
        'total_employees': total_employees,
        'active_employees': active_employees,
        'new_hires_this_month': new_hires_this_month,
        'departed_employees': departed,
        'turnover_rate': turnover_rate,
        'pending_leaves': pending_leaves,
        'approved_leaves': approved_leaves,
        'attendance_rate': attendance_rate,
        'present_days': present_days,
        'late_days': late_days,
        'absent_days': absent_days,
        'by_department': by_department,
        'by_status': by_status,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def org_chart_api(request):
    """Organization chart data for visualization."""
    if not (request.user.is_superuser or is_company_admin(request.user, request) or
            request.user.has_perm('hr_staff.view_hr_dashboard') or
            request.user.has_perm('hr_staff.view_employee')):
        return Response({'detail': 'Permission denied'}, status=403)
    
    employees_qs = get_employee_queryset_for_user(request.user, request, account_lookup='account')
    departments_qs = drf_filter_queryset_for_user(
        Department.objects.all(), request, account_lookup='account'
    )
    
    departments = []
    for dept in departments_qs:
        dept_employees = employees_qs.filter(department=dept)
        employees = []
        for emp in dept_employees:
            employees.append({
                'id': emp.id,
                'name': emp.full_name,
                'position': emp.position or '',
                'photo_url': getattr(emp, 'display_photo_url', None),
            })
        departments.append({
            'id': dept.id,
            'name': dept.name,
            'manager_name': dept.manager_name or '',
            'employees': employees,
            'employee_count': dept_employees.count(),
        })
    
    return Response({'departments': departments})


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def my_leave_balance_api(request):
    """Get leave balance for logged-in employee."""
    employee = get_linked_employee_for_user(request.user)
    if not employee:
        return Response({'detail': 'No employee profile'}, status=404)
    
    account = get_account_for_user(request.user)
    policies = LeavePolicy.objects.filter(account=account, is_active=True)
    
    leaves = get_leave_queryset_for_user(request.user, request, account_lookup='account')
    today = date.today()
    year_start = today.replace(month=1, day=1)
    
    balances = []
    for policy in policies:
        approved_days = leaves.filter(
            employee=employee,
            leave_type=policy.leave_type,
            status='approved',
            start_date__gte=year_start
        ).aggregate(total=Sum(models.F('end_date') - models.F('start_date') + 1))['total'] or 0
        
        if hasattr(approved_days, 'days'):
            approved_days = approved_days.days
        
        balance = policy.days_per_year - int(approved_days)
        balances.append({
            'policy_id': policy.id,
            'leave_type': policy.leave_type,
            'leave_type_display': policy.get_leave_type_display(),
            'days_allocated': policy.days_per_year,
            'days_used': int(approved_days),
            'days_remaining': max(0, balance),
        })
    
    return Response({'balances': balances})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def extract_cv_api(request):
    """API endpoint to extract information from uploaded CV - Enhanced version"""
    from .cv_extraction import extract_cv_information, extract_multiple_files
    from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
    
    try:
        # Handle single file upload
        uploaded_file = request.FILES.get('file')
        
        if uploaded_file:
            file_content = uploaded_file.read()
            result = extract_cv_information(file_content, uploaded_file.name)
            
            # Format the response for better frontend display
            if result.get('extraction_success'):
                # Convert skills dict to string for form
                skills_dict = result.get('skills', {})
                skills_list = []
                for category, skill_list in skills_dict.items():
                    skills_list.extend(skill_list)
                result['skills_text'] = ', '.join(skills_list)
                
                # Convert education list to text
                education_list = result.get('education', [])
                if education_list:
                    edu_texts = []
                    for edu in education_list:
                        if isinstance(edu, dict):
                            parts = []
                            if edu.get('degree'): parts.append(edu['degree'])
                            if edu.get('institution'): parts.append(edu['institution'])
                            if edu.get('year'): parts.append(edu['year'])
                            if parts:
                                edu_texts.append(' - '.join(parts))
                        else:
                            edu_texts.append(str(edu))
                    result['education_text'] = '\n'.join(edu_texts)
                
                # Check for full_text (complete section) - PRIORITIZE THIS
                education_list = result.get('education', [])
                for edu in education_list:
                    if isinstance(edu, dict) and edu.get('full_text'):
                        result['education_text'] = edu['full_text']
                        break
                
                # Convert experience list to text
                experience_list = result.get('work_experience', [])
                exp_texts = []
                for exp in experience_list:
                    if isinstance(exp, dict):
                        # Check for full_text first (complete section)
                        if exp.get('full_text'):
                            result['experience_text'] = exp['full_text']
                            break
                        # Otherwise use parsed parts
                        parts = []
                        if exp.get('position'): parts.append(exp['position'])
                        if exp.get('company'): parts.append(exp['company'])
                        if exp.get('period'): parts.append(exp['period'])
                        if exp.get('text'): parts.append(exp['text'])
                        if parts:
                            exp_texts.append(' - '.join(parts))
                    else:
                        exp_texts.append(str(exp))
                if not result.get('experience_text'):
                    result['experience_text'] = '\n'.join(exp_texts)
                
                # Add first/last name if only full name was extracted
                if result.get('name') and not result.get('first_name'):
                    name_parts = result['name'].strip().split()
                    if len(name_parts) >= 2:
                        result['first_name'] = name_parts[0]
                        result['last_name'] = ' '.join(name_parts[1:])
                    else:
                        result['first_name'] = result['name']
            
            return Response(result)
        
        # Handle multiple files
        uploaded_files = request.FILES.getlist('files')
        
        if uploaded_files and len(uploaded_files) > 1:
            files_data = []
            for f in uploaded_files:
                f.seek(0)
                files_data.append((f.read(), f.name))
                f.seek(0)
            
            result = extract_multiple_files(files_data)
            
            # Format response
            if result.get('extraction_success'):
                skills_dict = result.get('skills', {})
                skills_list = []
                for category, skill_list in skills_dict.items():
                    skills_list.extend(skill_list)
                result['skills_text'] = ', '.join(skills_list)
                
                education_list = result.get('education', [])
                if education_list:
                    edu_texts = []
                    for edu in education_list:
                        if isinstance(edu, dict):
                            parts = []
                            if edu.get('degree'): parts.append(edu['degree'])
                            if edu.get('institution'): parts.append(edu['institution'])
                            if edu.get('year'): parts.append(edu['year'])
                            if parts:
                                edu_texts.append(' - '.join(parts))
                        else:
                            edu_texts.append(str(edu))
                    result['education_text'] = '\n'.join(edu_texts)
                
                experience_list = result.get('work_experience', [])
                if experience_list:
                    exp_texts = []
                    for exp in experience_list:
                        if isinstance(exp, dict):
                            parts = []
                            if exp.get('position'): parts.append(exp['position'])
                            if exp.get('company'): parts.append(exp['company'])
                            if exp.get('period'): parts.append(exp['period'])
                            if parts:
                                exp_texts.append(' - '.join(parts))
                        else:
                            exp_texts.append(str(exp))
                    result['experience_text'] = '\n'.join(exp_texts)
            
            return Response(result)
        
        return Response({'error': 'No file provided'}, status=400)
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"CV extraction API error: {e}")
        return Response({'error': str(e)}, status=500)


from django.db import models
