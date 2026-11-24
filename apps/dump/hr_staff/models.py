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
