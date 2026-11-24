# -*- coding: utf-8 -*-
from django.urls import path
from . import views

app_name = 'hr_staff'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('api/dashboard-stats/', views.dashboard_stats_json, name='dashboard_stats_json'),
    # Employees
    path('employees/', views.employee_list, name='employee_list'),
    path('employees/create/', views.employee_create, name='employee_create'),
    path('employees/create-profiles-for-all/', views.employee_create_profiles_for_all, name='employee_create_profiles_for_all'),
    path('employees/<int:pk>/', views.employee_detail, name='employee_detail'),
    path('employees/<int:pk>/json/', views.employee_detail_json, name='employee_detail_json'),
    path('employees/<int:pk>/edit/', views.employee_edit, name='employee_edit'),
    path('employees/<int:pk>/delete/', views.employee_delete, name='employee_delete'),
    path('employees/<int:pk>/reset-password/', views.employee_reset_password, name='employee_reset_password'),
    path('employees/<int:pk>/toggle-active/', views.employee_toggle_active, name='employee_toggle_active'),
    path('portal/', views.employee_portal_dashboard, name='employee_portal_dashboard'),
    # Departments
    path('departments/', views.department_list, name='department_list'),
    path('departments/create/', views.department_create, name='department_create'),
    path('departments/<int:pk>/', views.department_detail, name='department_detail'),
    path('departments/<int:pk>/edit/', views.department_edit, name='department_edit'),
    path('departments/<int:pk>/delete/', views.department_delete, name='department_delete'),
    # Leave requests
    path('leave/', views.leave_list, name='leave_list'),
    path('leave/create/', views.leave_create, name='leave_create'),
    path('leave/<int:pk>/', views.leave_detail, name='leave_detail'),
    path('leave/<int:pk>/edit/', views.leave_edit, name='leave_edit'),
    path('leave/<int:pk>/delete/', views.leave_delete, name='leave_delete'),
    path('leave/<int:pk>/update-status/', views.leave_update_status, name='leave_update_status'),
    # Leave Policies
    path('leave-policies/', views.leave_policy_list, name='leave_policy_list'),
    path('leave-policies/create/', views.leave_policy_create, name='leave_policy_create'),
    path('leave-policies/<int:pk>/', views.leave_policy_detail, name='leave_policy_detail'),
    path('leave-policies/<int:pk>/edit/', views.leave_policy_edit, name='leave_policy_edit'),
    path('leave-policies/<int:pk>/delete/', views.leave_policy_delete, name='leave_policy_delete'),
    # Attendance
    path('attendance/', views.attendance_list, name='attendance_list'),
    path('attendance/create/', views.attendance_create, name='attendance_create'),
    path('attendance/<int:pk>/', views.attendance_detail, name='attendance_detail'),
    path('attendance/<int:pk>/edit/', views.attendance_edit, name='attendance_edit'),
    path('attendance/<int:pk>/delete/', views.attendance_delete, name='attendance_delete'),
    # Attendance Reports
    path('attendance/reports/', views.attendance_reports, name='attendance_reports'),
    # Performance Reviews
    path('performance/', views.performance_review_list, name='performance_review_list'),
    path('performance/create/', views.performance_review_create, name='performance_review_create'),
    path('performance/<int:pk>/', views.performance_review_detail, name='performance_review_detail'),
    path('performance/<int:pk>/edit/', views.performance_review_edit, name='performance_review_edit'),
    path('performance/<int:pk>/delete/', views.performance_review_delete, name='performance_review_delete'),
    # Performance Goals
    path('goals/', views.performance_goal_list, name='performance_goal_list'),
    path('goals/create/', views.performance_goal_create, name='performance_goal_create'),
    path('goals/<int:pk>/edit/', views.performance_goal_edit, name='performance_goal_edit'),
    # Training
    path('training/', views.training_course_list, name='training_course_list'),
    path('training/create/', views.training_course_create, name='training_course_create'),
    path('training/<int:pk>/', views.training_course_detail, name='training_course_detail'),
    path('training/<int:pk>/edit/', views.training_course_edit, name='training_course_edit'),
    path('training/enroll/', views.training_enrollment_create, name='training_enrollment_create'),
    # Documents
    path('documents/', views.document_list, name='document_list'),
    path('documents/create/', views.document_create, name='document_create'),
    path('documents/multi/', views.document_multi_create, name='document_multi_create'),
    path('documents/<int:pk>/', views.document_detail, name='document_detail'),
    path('documents/<int:pk>/edit/', views.document_edit, name='document_edit'),
    path('documents/<int:pk>/delete/', views.document_delete, name='document_delete'),
    # Analytics
    path('analytics/', views.hr_analytics, name='hr_analytics'),
    # Org Chart
    path('org-chart/', views.org_chart, name='org_chart'),
    # Job Seekers
    path('job-seekers/', views.job_seeker_list, name='job_seeker_list'),
    path('job-seekers/create/', views.job_seeker_create, name='job_seeker_create'),
    path('job-seekers/<int:pk>/', views.job_seeker_detail, name='job_seeker_detail'),
    path('job-seekers/<int:pk>/edit/', views.job_seeker_edit, name='job_seeker_edit'),
    path('job-seekers/<int:pk>/delete/', views.job_seeker_delete, name='job_seeker_delete'),
]
