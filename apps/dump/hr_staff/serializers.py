# -*- coding: utf-8 -*-
"""
HR & Staff serializers for DRF API.
"""
from rest_framework import serializers
from .models import Department, Employee, LeaveRequest


class DepartmentSerializer(serializers.ModelSerializer):
    """Serializer for Department."""

    employee_count = serializers.SerializerMethodField()

    class Meta:
        model = Department
        fields = [
            'id', 'name', 'manager_name', 'budget',
            'employee_count', 'created_at',
        ]
        read_only_fields = ['created_at']

    def get_employee_count(self, obj):
        if hasattr(obj, 'employee_count'):
            return obj.employee_count
        return obj.employees.count()


class EmployeeSerializer(serializers.ModelSerializer):
    """Serializer for Employee. profile_photo is the display URL (User profile_picture or HR profile_photo)."""

    full_name = serializers.ReadOnlyField()
    department_name = serializers.SerializerMethodField()
    profile_photo = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = [
            'id', 'employee_id', 'first_name', 'last_name', 'full_name',
            'department', 'department_name', 'position',
            'email', 'phone', 'profile_photo', 'status',
            'date_joined', 'created_at',
        ]
        read_only_fields = ['created_at']

    def get_department_name(self, obj):
        return obj.department.name if obj.department else None

    def get_profile_photo(self, obj):
        url = getattr(obj, 'display_photo_url', None) or (obj.profile_photo.url if obj.profile_photo else None)
        if url and self.context.get('request'):
            return self.context['request'].build_absolute_uri(url)
        return url


class LeaveRequestSerializer(serializers.ModelSerializer):
    """Serializer for LeaveRequest. duration_days is computed from start_date/end_date."""

    employee_name = serializers.SerializerMethodField()
    leave_type_display = serializers.CharField(source='get_leave_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    duration_days = serializers.ReadOnlyField()
    status_changed_by_name = serializers.SerializerMethodField()
    status_changed_at_display = serializers.SerializerMethodField()

    class Meta:
        model = LeaveRequest
        fields = [
            'id', 'employee', 'employee_name',
            'leave_type', 'leave_type_display',
            'start_date', 'end_date',
            'duration_days',
            'reason',
            'status', 'status_display',
            'created_at',
            'status_changed_by', 'status_changed_by_name',
            'status_changed_at', 'status_changed_at_display',
        ]
        read_only_fields = ['created_at']

    def get_employee_name(self, obj):
        return obj.employee.full_name if obj.employee else None

    def get_status_changed_by_name(self, obj):
        user = getattr(obj, 'status_changed_by', None)
        if not user:
            return None
        return (getattr(user, 'get_full_name', lambda: '')() or getattr(user, 'email', None) or str(user))

    def get_status_changed_at_display(self, obj):
        from django.utils.dateformat import DateFormat
        if not getattr(obj, 'status_changed_at', None):
            return None
        return DateFormat(obj.status_changed_at).format('j M Y, g:i A')
