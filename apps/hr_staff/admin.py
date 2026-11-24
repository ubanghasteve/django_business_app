# -*- coding: utf-8 -*-
from django.contrib import admin
from .models import (
    Employee, Department, LeaveRequest, LeavePolicy,
    Attendance, AttendanceSetting,
    PerformanceReview, PerformanceGoal, PerformanceEvaluation,
    TrainingCourse, TrainingEnrollment, EmployeeDocument
)
from apps.core.admin_base import AccountScopedAdmin


@admin.register(Department)
class DepartmentAdmin(AccountScopedAdmin):
    account_scope_lookup = 'account'
    list_display = ['name', 'manager_name', 'budget', 'account', 'created_at']
    list_filter = ['account']
    search_fields = ['name', 'manager_name']
    readonly_fields = ['created_at']


@admin.register(Employee)
class EmployeeAdmin(AccountScopedAdmin):
    account_scope_lookup = 'account'
    list_display = ['first_name', 'last_name', 'department', 'position', 'status', 'date_joined', 'account']
    list_filter = ['status', 'department', 'account']
    search_fields = ['first_name', 'last_name', 'position']
    readonly_fields = ['created_at']


@admin.register(LeaveRequest)
class LeaveRequestAdmin(AccountScopedAdmin):
    account_scope_lookup = 'account'
    list_display = ['employee', 'leave_type', 'start_date', 'end_date', 'status', 'account', 'created_at']
    list_filter = ['status', 'leave_type', 'account']
    search_fields = ['employee__first_name', 'employee__last_name']
    readonly_fields = ['created_at']


@admin.register(LeavePolicy)
class LeavePolicyAdmin(AccountScopedAdmin):
    account_scope_lookup = 'account'
    list_display = ['name', 'leave_type', 'days_per_year', 'is_active', 'account']
    list_filter = ['leave_type', 'is_active', 'account']
    search_fields = ['name']


@admin.register(Attendance)
class AttendanceAdmin(AccountScopedAdmin):
    account_scope_lookup = 'account'
    list_display = ['employee', 'date', 'check_in', 'check_out', 'status', 'account']
    list_filter = ['status', 'date', 'account']
    search_fields = ['employee__first_name', 'employee__last_name']
    readonly_fields = ['created_at']


@admin.register(AttendanceSetting)
class AttendanceSettingAdmin(AccountScopedAdmin):
    account_scope_lookup = 'account'
    list_display = ['account', 'work_start_time', 'work_end_time', 'late_threshold_minutes']
    list_filter = ['account']


@admin.register(PerformanceReview)
class PerformanceReviewAdmin(AccountScopedAdmin):
    account_scope_lookup = 'account'
    list_display = ['title', 'review_type', 'start_date', 'end_date', 'status', 'account']
    list_filter = ['status', 'review_type', 'account']
    search_fields = ['title']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(PerformanceGoal)
class PerformanceGoalAdmin(AccountScopedAdmin):
    account_scope_lookup = 'account'
    list_display = ['employee', 'title', 'due_date', 'progress', 'status', 'account']
    list_filter = ['status', 'account']
    search_fields = ['employee__first_name', 'employee__last_name', 'title']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(PerformanceEvaluation)
class PerformanceEvaluationAdmin(AccountScopedAdmin):
    account_scope_lookup = 'account'
    list_display = ['employee', 'review', 'overall_rating', 'is_completed', 'account']
    list_filter = ['is_completed', 'account']
    search_fields = ['employee__first_name', 'employee__last_name']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(TrainingCourse)
class TrainingCourseAdmin(AccountScopedAdmin):
    account_scope_lookup = 'account'
    list_display = ['title', 'category', 'duration_hours', 'status', 'is_required', 'account']
    list_filter = ['status', 'is_required', 'category', 'account']
    search_fields = ['title', 'description']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(TrainingEnrollment)
class TrainingEnrollmentAdmin(AccountScopedAdmin):
    account_scope_lookup = 'account'
    list_display = ['employee', 'course', 'status', 'enrolled_date', 'completed_date', 'account']
    list_filter = ['status', 'account']
    search_fields = ['employee__first_name', 'employee__last_name', 'course__title']
    readonly_fields = ['created_at']


@admin.register(EmployeeDocument)
class EmployeeDocumentAdmin(AccountScopedAdmin):
    account_scope_lookup = 'account'
    list_display = ['title', 'employee', 'document_type', 'created_at', 'expiry_date', 'account']
    list_filter = ['document_type', 'account']
    search_fields = ['title', 'employee__first_name', 'employee__last_name']
    readonly_fields = ['created_at', 'updated_at']
