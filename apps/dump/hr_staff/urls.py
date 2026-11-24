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
]
