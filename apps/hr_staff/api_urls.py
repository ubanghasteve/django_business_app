# -*- coding: utf-8 -*-
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import api_views

router = DefaultRouter()
router.register(r'departments', api_views.DepartmentViewSet, basename='hr-department')
router.register(r'employees', api_views.EmployeeViewSet, basename='hr-employee')
router.register(r'leave-requests', api_views.LeaveRequestViewSet, basename='hr-leaverequest')
router.register(r'leave-policies', api_views.LeavePolicyViewSet, basename='hr-leave-policy')
router.register(r'attendance', api_views.AttendanceViewSet, basename='hr-attendance')
router.register(r'attendance-settings', api_views.AttendanceSettingsViewSet, basename='hr-attendance-settings')
router.register(r'performance-reviews', api_views.PerformanceReviewViewSet, basename='hr-performance-review')
router.register(r'performance-goals', api_views.PerformanceGoalViewSet, basename='hr-performance-goal')
router.register(r'performance-evaluations', api_views.PerformanceEvaluationViewSet, basename='hr-performance-evaluation')
router.register(r'training-courses', api_views.TrainingCourseViewSet, basename='hr-training-course')
router.register(r'training-enrollments', api_views.TrainingEnrollmentViewSet, basename='hr-training-enrollment')
router.register(r'employee-documents', api_views.EmployeeDocumentViewSet, basename='hr-employee-document')

app_name = 'hr_staff_api'
urlpatterns = [
    path('dashboard-stats/', api_views.dashboard_stats_api, name='dashboard_stats'),
    path('dashboard-widgets/', api_views.dashboard_widgets_api, name='dashboard_widgets'),
    path('notifications/', api_views.hr_notifications_api, name='hr_notifications'),
    path('account-users-without-employee/', api_views.account_users_without_employee_api, name='account_users_without_employee'),
    path('attendance-today/', api_views.attendance_today_api, name='attendance_today'),
    path('attendance-calendar/', api_views.attendance_calendar_api, name='attendance_calendar'),
    path('analytics/', api_views.hr_analytics_api, name='hr_analytics'),
    path('org-chart/', api_views.org_chart_api, name='org_chart'),
    path('my-leave-balance/', api_views.my_leave_balance_api, name='my_leave_balance'),
    path('extract-cv/', api_views.extract_cv_api, name='extract_cv'),
    path('debug-documents/', api_views.debug_documents_api, name='debug_documents'),
    path('', include(router.urls)),
]
