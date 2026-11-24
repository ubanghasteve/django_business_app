# -*- coding: utf-8 -*-
"""
HR & Staff serializers for DRF API.
"""
from rest_framework import serializers
from .models import (
    Department, Employee, LeaveRequest, LeavePolicy, Attendance,
    PerformanceReview, PerformanceGoal, PerformanceEvaluation,
    TrainingCourse, TrainingEnrollment, EmployeeDocument
)


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


class EmployeeDetailSerializer(EmployeeSerializer):
    """Extended serializer for Employee with more fields."""
    
    linked_user_email = serializers.SerializerMethodField()
    is_portal_user = serializers.BooleanField(read_only=True)

    class Meta(EmployeeSerializer.Meta):
        fields = EmployeeSerializer.Meta.fields + [
            'date_of_birth', 'street_address', 'city', 'state_province', 'zip_code',
            'monthly_salary', 'reporting_manager', 'emergency_contact_name',
            'emergency_contact_phone', 'bio', 'linked_user', 'linked_user_email',
            'is_portal_user', 'portal_created_by_hr', 'updated_at',
        ]

    def get_linked_user_email(self, obj):
        return obj.linked_user.email if obj.linked_user else None


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


class LeavePolicySerializer(serializers.ModelSerializer):
    """Serializer for LeavePolicy."""
    
    leave_type_display = serializers.CharField(source='get_leave_type_display', read_only=True)

    class Meta:
        model = LeavePolicy
        fields = [
            'id', 'name', 'leave_type', 'leave_type_display',
            'days_per_year', 'carry_over_allowed', 'max_carry_over',
            'requires_approval', 'max_consecutive_days', 'is_active',
            'created_at',
        ]
        read_only_fields = ['created_at']


class AttendanceSerializer(serializers.ModelSerializer):
    """Serializer for Attendance."""
    
    employee_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    work_hours = serializers.ReadOnlyField()

    class Meta:
        model = Attendance
        fields = [
            'id', 'employee', 'employee_name', 'date',
            'check_in', 'check_out', 'status', 'status_display',
            'work_hours', 'notes', 'is_manual', 'created_at',
        ]
        read_only_fields = ['created_at']

    def get_employee_name(self, obj):
        return obj.employee.full_name if obj.employee else None


class AttendanceSettingsSerializer(serializers.ModelSerializer):
    """Serializer for AttendanceSetting."""

    class Meta:
        from .models import AttendanceSetting
        model = AttendanceSetting
        fields = [
            'id', 'work_start_time', 'work_end_time', 'late_threshold_minutes',
            'enable_check_in_out', 'allow_geo_location',
        ]


class PerformanceReviewSerializer(serializers.ModelSerializer):
    """Serializer for PerformanceReview."""
    
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    review_type_display = serializers.CharField(source='get_review_type_display', read_only=True)
    employee_count = serializers.SerializerMethodField()

    class Meta:
        model = PerformanceReview
        fields = [
            'id', 'title', 'description', 'start_date', 'end_date',
            'status', 'status_display', 'review_type', 'review_type_display',
            'employee_count', 'created_at',
        ]
        read_only_fields = ['created_at']

    def get_employee_count(self, obj):
        return obj.evaluations.count()


class PerformanceGoalSerializer(serializers.ModelSerializer):
    """Serializer for PerformanceGoal."""
    
    employee_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = PerformanceGoal
        fields = [
            'id', 'employee', 'employee_name', 'title', 'description',
            'due_date', 'status', 'status_display', 'progress',
            'review', 'created_at',
        ]
        read_only_fields = ['created_at']

    def get_employee_name(self, obj):
        return obj.employee.full_name if obj.employee else None


class PerformanceEvaluationSerializer(serializers.ModelSerializer):
    """Serializer for PerformanceEvaluation."""
    
    employee_name = serializers.SerializerMethodField()
    evaluator_name = serializers.SerializerMethodField()
    review_title = serializers.SerializerMethodField()

    class Meta:
        model = PerformanceEvaluation
        fields = [
            'id', 'employee', 'employee_name', 'review', 'review_title',
            'evaluator', 'evaluator_name', 'overall_rating',
            'strengths', 'improvements', 'comments', 'is_completed',
            'created_at',
        ]
        read_only_fields = ['created_at']

    def get_employee_name(self, obj):
        return obj.employee.full_name if obj.employee else None

    def get_evaluator_name(self, obj):
        return obj.evaluator.get_full_name() if obj.evaluator else None

    def get_review_title(self, obj):
        return obj.review.title if obj.review else None


class TrainingCourseSerializer(serializers.ModelSerializer):
    """Serializer for TrainingCourse."""
    
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    enrolled_count = serializers.SerializerMethodField()
    completed_count = serializers.SerializerMethodField()

    class Meta:
        model = TrainingCourse
        fields = [
            'id', 'title', 'description', 'category', 'duration_hours',
            'status', 'status_display', 'is_required',
            'enrolled_count', 'completed_count', 'created_at',
        ]
        read_only_fields = ['created_at']

    def get_enrolled_count(self, obj):
        return obj.enrollments.count()

    def get_completed_count(self, obj):
        return obj.enrollments.filter(status='completed').count()


class TrainingEnrollmentSerializer(serializers.ModelSerializer):
    """Serializer for TrainingEnrollment."""
    
    employee_name = serializers.SerializerMethodField()
    course_title = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = TrainingEnrollment
        fields = [
            'id', 'employee', 'employee_name', 'course', 'course_title',
            'status', 'status_display', 'enrolled_date', 'completed_date',
            'certificate', 'created_at',
        ]
        read_only_fields = ['created_at', 'enrolled_date']

    def get_employee_name(self, obj):
        return obj.employee.full_name if obj.employee else None

    def get_course_title(self, obj):
        return obj.course.title if obj.course else None


class EmployeeDocumentSerializer(serializers.ModelSerializer):
    """Serializer for EmployeeDocument."""
    
    employee_name = serializers.SerializerMethodField()
    document_type_display = serializers.CharField(source='get_document_type_display', read_only=True)
    file_url = serializers.SerializerMethodField()
    uploaded_date = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model = EmployeeDocument
        fields = [
            'id', 'employee', 'employee_name', 'document_type', 'document_type_display',
            'title', 'file', 'file_url', 'expiry_date', 'notes', 'created_at', 'uploaded_date',
        ]
        read_only_fields = ['created_at']

    def get_employee_name(self, obj):
        return obj.employee.full_name if obj.employee else None

    def get_file_url(self, obj):
        if obj.file and hasattr(obj.file, 'url'):
            if self.context.get('request'):
                return self.context['request'].build_absolute_uri(obj.file.url)
            return obj.file.url
        return None
