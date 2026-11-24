# -*- coding: utf-8 -*-
"""
HR & Staff app – Employee, Department, LeaveRequest.
All models tenant-isolated via account; use for_user_queryset(..., account_lookup='account').
"""
import uuid
from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator

from apps.core.ownership import TenantOwnedManager
from apps.core.sync_mixin import SyncMixin

User = settings.AUTH_USER_MODEL


def employee_photo_upload_path(instance, filename):
    """Upload path for employee profile photos."""
    return f'hr_staff/employees/{instance.account_id}/{instance.pk or "new"}/{filename}'


class Department(SyncMixin, models.Model):
    """Department: tenant-scoped; has manager name and budget."""
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='hr_departments',
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=200)
    manager_name = models.CharField(max_length=200, blank=True, default='')
    budget = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        help_text='Department budget',
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hr_departments_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantOwnedManager()

    class Meta:
        ordering = ['name']
        verbose_name = 'Department'
        verbose_name_plural = 'Departments'

    def __str__(self):
        return self.name


class Employee(models.Model):
    """Employee: tenant-scoped; links to Department; has position, photo, status."""
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('on_leave', 'On Leave'),
        ('suspended', 'Suspended'),
        ('resigned', 'Resigned'),
    ]
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='hr_employees',
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hr_employees',
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hr_employees_created',
    )
    employee_id = models.CharField(max_length=50, blank=True, default='', help_text='e.g. EMP-12345')
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='employees',
    )
    position = models.CharField(max_length=200, blank=True, default='')
    email = models.EmailField(blank=True, default='')
    phone = models.CharField(max_length=50, blank=True, default='')
    profile_photo = models.ImageField(
        upload_to=employee_photo_upload_path,
        blank=True,
        null=True,
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='active',
    )
    date_joined = models.DateField(null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    street_address = models.CharField(max_length=255, blank=True, default='')
    city = models.CharField(max_length=100, blank=True, default='')
    state_province = models.CharField(max_length=100, blank=True, default='')
    zip_code = models.CharField(max_length=20, blank=True, default='')
    monthly_salary = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    reporting_manager = models.CharField(max_length=200, blank=True, default='')
    emergency_contact_name = models.CharField(max_length=200, blank=True, default='')
    emergency_contact_phone = models.CharField(max_length=50, blank=True, default='')
    bio = models.TextField(blank=True, default='', help_text='Short bio or notes for this employee.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    is_deleted = models.BooleanField(default=False)
    # Portal / login: link to Django User for employees who have their own login.
    # When set, this employee sees only their own data (dashboard, leave) via linked_user.
    linked_user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='linked_employee',
        help_text='Django User for portal access. When set, this employee can log in and see only their own data.',
    )
    is_portal_user = models.BooleanField(
        default=False,
        help_text='True when this employee has been granted portal (login) access.',
    )
    # True when the portal User was created by HR (create_employee_portal_user). False when employee
    # was linked to an existing User created by Company Admin. HR may only reset password when True.
    portal_created_by_hr = models.BooleanField(
        default=False,
        help_text='True if HR created the portal account; False if linked to existing team member. HR cannot reset password when False.',
    )

    objects = TenantOwnedManager()

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Employee'
        verbose_name_plural = 'Employees'
        permissions = [
            ('view_hr_dashboard', 'View HR dashboard'),
            ('view_own_hr_dashboard', 'View own HR dashboard'),
            ('create_employee_account', 'Create employee portal account'),
            ('reset_employee_password', 'Reset employee password'),
            ('view_employee_activity', 'View employee activity'),
        ]

    def __str__(self):
        return f'{self.first_name} {self.last_name}'.strip() or 'Employee'

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'.strip() or '—'

    @property
    def display_photo_url(self):
        """
        Profile picture URL for display in HR app. Prefers the linked User's
        profile_picture (updated in Accounts → My Profile) so when an employee
        updates their profile picture it shows immediately in HR & Staff
        without re-uploading. Falls back to HR-only profile_photo if set.
        """
        if self.linked_user_id:
            try:
                user_pic = getattr(self.linked_user, 'profile_picture', None)
                if user_pic and getattr(user_pic, 'name', None):
                    return user_pic.url
            except (ValueError, AttributeError):
                pass
        if self.profile_photo and getattr(self.profile_photo, 'name', None):
            try:
                return self.profile_photo.url
            except (ValueError, AttributeError):
                pass
        return None


class LeaveRequest(SyncMixin, models.Model):
    """Leave request: tenant-scoped; links to Employee; has type, dates, status."""
    LEAVE_TYPE_CHOICES = [
        ('vacation', 'Vacation'),
        ('sick', 'Sick'),
        ('personal', 'Personal'),
        ('other', 'Other'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='hr_leave_requests',
        null=True,
        blank=True,
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='leave_requests',
    )
    leave_type = models.CharField(
        max_length=20,
        choices=LEAVE_TYPE_CHOICES,
        default='vacation',
    )
    reason = models.CharField(max_length=500, blank=True, default='')
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
    )
    supporting_document = models.FileField(
        upload_to='hr_staff/leave_docs/%Y/%m/',
        blank=True,
        null=True,
    )
    supervisor_manager = models.CharField(max_length=200, blank=True, default='')
    work_handover_to = models.CharField(max_length=200, blank=True, default='')
    handover_notes = models.TextField(blank=True, default='')
    contact_number = models.CharField(max_length=50, blank=True, default='')
    address_during_leave = models.CharField(max_length=500, blank=True, default='')
    emergency_contact_name = models.CharField(max_length=200, blank=True, default='')
    emergency_contact_phone = models.CharField(max_length=50, blank=True, default='')
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hr_leave_requests_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # When status changes (approved/rejected), record who changed it and when so
    # employee cards and tables can show accurate approver and timestamp.
    status_changed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hr_leave_requests_status_changed',
    )
    status_changed_at = models.DateTimeField(null=True, blank=True)

    objects = TenantOwnedManager()

    class Meta:
        ordering = ['-start_date']
        verbose_name = 'Leave Request'
        verbose_name_plural = 'Leave Requests'

    def __str__(self):
        return f'{self.employee} – {self.get_leave_type_display()} ({self.start_date} to {self.end_date})'

    @property
    def duration_days(self):
        if self.start_date and self.end_date:
            return (self.end_date - self.start_date).days + 1
        return 0


class LeavePolicy(SyncMixin, models.Model):
    """
    Configurable leave policies per account: define leave types, annual allocation, carry-over, etc.
    """
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='hr_leave_policies',
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hr_leave_policies_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    name = models.CharField(max_length=100)
    leave_type = models.CharField(
        max_length=20,
        choices=LeaveRequest.LEAVE_TYPE_CHOICES,
        default='vacation',
    )
    days_per_year = models.PositiveIntegerField(default=0, help_text='Days allocated per year')
    carry_over_allowed = models.BooleanField(default=False, help_text='Allow unused days to carry over to next year')
    max_carry_over = models.PositiveIntegerField(default=0, help_text='Maximum days that can be carried over')
    requires_approval = models.BooleanField(default=True)
    max_consecutive_days = models.PositiveIntegerField(default=0, help_text='0 = unlimited')
    is_active = models.BooleanField(default=True)

    objects = TenantOwnedManager()

    class Meta:
        ordering = ['name']
        verbose_name = 'Leave Policy'
        verbose_name_plural = 'Leave Policies'
        unique_together = ['account', 'leave_type']

    def __str__(self):
        return f"{self.name} ({self.get_leave_type_display()})"


class Attendance(SyncMixin, models.Model):
    """
    Daily attendance: check-in/check-out tracking per employee.
    """
    STATUS_CHOICES = [
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('late', 'Late'),
        ('on_leave', 'On Leave'),
        ('holiday', 'Holiday'),
    ]

    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='hr_attendance_records',
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hr_attendance_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='attendance_records',
    )
    date = models.DateField()
    check_in = models.TimeField(null=True, blank=True)
    check_out = models.TimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='present',
    )
    notes = models.TextField(blank=True, default='')
    is_manual = models.BooleanField(default=False, help_text='True if manually added by HR')

    objects = TenantOwnedManager()

    class Meta:
        ordering = ['-date', 'employee__first_name']
        verbose_name = 'Attendance'
        verbose_name_plural = 'Attendance Records'
        unique_together = ['employee', 'date']
        indexes = [
            models.Index(fields=['account', 'date']),
            models.Index(fields=['employee', 'date']),
        ]

    def __str__(self):
        return f"{self.employee} - {self.date} ({self.get_status_display()})"

    @property
    def work_hours(self):
        if self.check_in and self.check_out:
            from datetime import datetime, timedelta
            check_in_dt = datetime.combine(self.date, self.check_in)
            check_out_dt = datetime.combine(self.date, self.check_out)
            if check_out_dt < check_in_dt:
                check_out_dt += timedelta(days=1)
            duration = check_out_dt - check_in_dt
            hours = duration.total_seconds() / 3600
            return round(hours, 2)
        return None


class AttendanceSetting(SyncMixin, models.Model):
    """
    Attendance settings per account: work hours, late threshold, etc.
    """
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='hr_attendance_settings',
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hr_attendance_settings_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    work_start_time = models.TimeField(default='08:00')
    work_end_time = models.TimeField(default='17:00')
    late_threshold_minutes = models.PositiveIntegerField(default=15, help_text='Minutes after start time to mark as late')
    enable_check_in_out = models.BooleanField(default=True)
    allow_geo_location = models.BooleanField(default=False)

    objects = TenantOwnedManager()

    class Meta:
        verbose_name = 'Attendance Setting'
        verbose_name_plural = 'Attendance Settings'

    def __str__(self):
        return f"Attendance Settings - {self.account}" if self.account else "Default Settings"


class PerformanceReview(SyncMixin, models.Model):
    """
    Performance review cycles and evaluations.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='hr_performance_reviews',
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hr_performance_reviews_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default='')
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft',
    )
    review_type = models.CharField(
        max_length=50,
        choices=[
            ('annual', 'Annual'),
            ('quarterly', 'Quarterly'),
            ('probation', 'Probation'),
            ('mid_year', 'Mid-Year'),
            ('custom', 'Custom'),
        ],
        default='annual',
    )

    objects = TenantOwnedManager()

    class Meta:
        ordering = ['-start_date']
        verbose_name = 'Performance Review'
        verbose_name_plural = 'Performance Reviews'

    def __str__(self):
        return self.title


class PerformanceGoal(SyncMixin, models.Model):
    """
    Performance goals set for employees.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='hr_performance_goals',
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hr_performance_goals_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='performance_goals',
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default='')
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
    )
    progress = models.PositiveSmallIntegerField(default=0, help_text='Progress percentage 0-100')
    review = models.ForeignKey(
        PerformanceReview,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='goals',
    )

    objects = TenantOwnedManager()

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Performance Goal'
        verbose_name_plural = 'Performance Goals'

    def __str__(self):
        return f"{self.employee} - {self.title}"


class PerformanceEvaluation(SyncMixin, models.Model):
    """
    Performance evaluation for an employee in a review cycle.
    """
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='hr_performance_evaluations',
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hr_performance_evaluations_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='performance_evaluations',
    )
    review = models.ForeignKey(
        PerformanceReview,
        on_delete=models.CASCADE,
        related_name='evaluations',
    )
    evaluator = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hr_evaluations_given',
    )
    overall_rating = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text='Rating 1-5'
    )
    strengths = models.TextField(blank=True, default='')
    improvements = models.TextField(blank=True, default='')
    comments = models.TextField(blank=True, default='')
    is_completed = models.BooleanField(default=False)

    objects = TenantOwnedManager()

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Performance Evaluation'
        verbose_name_plural = 'Performance Evaluations'
        unique_together = ['employee', 'review']

    def __str__(self):
        return f"{self.employee} - {self.review}"


class TrainingCourse(SyncMixin, models.Model):
    """
    Training courses available for employees.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('archived', 'Archived'),
    ]

    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='hr_training_courses',
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hr_training_courses_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default='')
    category = models.CharField(max_length=100, blank=True, default='')
    duration_hours = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text='Course duration in hours'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='active',
    )
    is_required = models.BooleanField(default=False, help_text='Mandatory training for all employees')

    objects = TenantOwnedManager()

    class Meta:
        ordering = ['title']
        verbose_name = 'Training Course'
        verbose_name_plural = 'Training Courses'

    def __str__(self):
        return self.title


class TrainingEnrollment(SyncMixin, models.Model):
    """
    Employee enrollment in training courses.
    """
    STATUS_CHOICES = [
        ('enrolled', 'Enrolled'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('dropped', 'Dropped'),
    ]

    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='hr_training_enrollments',
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hr_training_enrollments_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='training_enrollments',
    )
    course = models.ForeignKey(
        TrainingCourse,
        on_delete=models.CASCADE,
        related_name='enrollments',
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='enrolled',
    )
    enrolled_date = models.DateField(auto_now_add=True)
    completed_date = models.DateField(null=True, blank=True)
    certificate = models.FileField(
        upload_to='hr_staff/training/certificates/',
        blank=True,
        null=True,
    )

    objects = TenantOwnedManager()

    class Meta:
        ordering = ['-enrolled_date']
        verbose_name = 'Training Enrollment'
        verbose_name_plural = 'Training Enrollments'
        unique_together = ['employee', 'course']

    def __str__(self):
        return f"{self.employee} - {self.course}"


class EmployeeDocument(SyncMixin, models.Model):
    """
    Employee documents: contracts, certificates, policies, etc.
    Now with smart extraction support for CVs/resumes
    """
    DOCUMENT_TYPE_CHOICES = [
        ('contract', 'Employment Contract'),
        ('id_card', 'ID Card'),
        ('certificate', 'Certificate'),
        ('policy', 'Policy Signed'),
        ('cv', 'CV / Resume'),
        ('other', 'Other'),
    ]

    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='hr_employee_documents',
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hr_employee_documents_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='documents',
    )
    document_type = models.CharField(
        max_length=50,
        choices=DOCUMENT_TYPE_CHOICES,
        default='other',
    )
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to='hr_staff/documents/%Y/%m/')
    expiry_date = models.DateField(null=True, blank=True, help_text='For documents that expire')
    notes = models.TextField(blank=True, default='')
    
    # Extracted data from CV/resume
    extracted_data_json = models.TextField(blank=True, default='', help_text='JSON data extracted from CV/resume')
    extracted_at = models.DateTimeField(null=True, blank=True)

    objects = TenantOwnedManager()

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Employee Document'
        verbose_name_plural = 'Employee Documents'

    def __str__(self):
        return f"{self.employee} - {self.title}"


def job_seeker_cv_upload_path(instance, filename):
    """Upload path for job seeker CV documents."""
    return f'hr_staff/job_seekers/{instance.account_id}/{instance.pk or "new"}/cv/{filename}'


class JobSeeker(models.Model):
    """JobSeeker: Stores candidate information extracted from uploaded CV."""
    STATUS_CHOICES = [
        ('new', 'New'),
        ('reviewing', 'Under Review'),
        ('shortlisted', 'Shortlisted'),
        ('rejected', 'Rejected'),
        ('hired', 'Hired'),
    ]
    
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='hr_job_seekers',
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hr_job_seekers',
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hr_job_seekers_created',
    )
    
    first_name = models.CharField(max_length=100, blank=True, default='')
    last_name = models.CharField(max_length=100, blank=True, default='')
    full_name = models.CharField(max_length=200, blank=True, default='')
    email = models.EmailField(blank=True, default='')
    phone = models.TextField(blank=True, default='')
    address = models.TextField(blank=True, default='')
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=20, blank=True, default='')
    
    position_applied = models.CharField(max_length=200, blank=True, default='')
    years_of_experience = models.CharField(max_length=100, blank=True, default='')
    skills = models.TextField(blank=True, default='')
    education = models.TextField(blank=True, default='')
    work_experience = models.TextField(blank=True, default='')
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    notes = models.TextField(blank=True, default='')
    
    cv_file = models.FileField(upload_to=job_seeker_cv_upload_path, blank=True, null=True)
    cv_file_name = models.CharField(max_length=255, blank=True, default='')
    cv_uploaded_at = models.DateTimeField(null=True, blank=True)
    
    extracted_text = models.TextField(blank=True, default='')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantOwnedManager()

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Job Seeker'
        verbose_name_plural = 'Job Seekers'

    def __str__(self):
        return self.full_name or f"JobSeeker {self.pk}"

    @property
    def name(self):
        return self.full_name or f"{self.first_name} {self.last_name}".strip()


def job_seeker_document_upload_path(instance, filename):
    """Upload path for job seeker documents."""
    return f'hr_staff/job_seekers/{instance.job_seeker.account_id}/{instance.job_seeker.pk}/documents/{filename}'


class JobSeekerDocument(models.Model):
    """Additional documents for Job Seeker (multiple CVs, certificates, etc.)"""
    DOCUMENT_TYPES = [
        ('cv', 'CV/Resume'),
        ('certificate', 'Certificate'),
        ('transcript', 'Transcript'),
        ('id', 'ID Document'),
        ('other', 'Other'),
    ]
    
    job_seeker = models.ForeignKey(
        JobSeeker,
        on_delete=models.CASCADE,
        related_name='documents',
    )
    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPES, default='cv')
    file = models.FileField(upload_to=job_seeker_document_upload_path, blank=True, null=True)
    file_name = models.CharField(max_length=255, blank=True, default='')
    file_size = models.PositiveIntegerField(default=0)
    
    # Extracted data from this document
    extracted_text = models.TextField(blank=True, default='')
    extracted_email = models.EmailField(blank=True, default='')
    extracted_phone = models.CharField(max_length=50, blank=True, default='')
    extracted_name = models.CharField(max_length=200, blank=True, default='')
    extracted_skills = models.TextField(blank=True, default='')
    extracted_education = models.TextField(blank=True, default='')
    extracted_experience = models.TextField(blank=True, default='')
    
    extraction_success = models.BooleanField(default=False)
    extraction_error = models.TextField(blank=True, default='')
    
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    objects = TenantOwnedManager()
    
    class Meta:
        ordering = ['-uploaded_at']
        verbose_name = 'Job Seeker Document'
        verbose_name_plural = 'Job Seeker Documents'
    
    def __str__(self):
        return f"{self.job_seeker.name} - {self.file_name}"
