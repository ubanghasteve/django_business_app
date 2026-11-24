# -*- coding: utf-8 -*-
from django.contrib import admin
from .models import Employee, Department, LeaveRequest
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
