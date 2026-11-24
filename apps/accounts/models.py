from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager, Group
from django.contrib.auth.hashers import make_password, check_password
from django.db import models
from django.utils import timezone as django_timezone
from django.conf import settings
import uuid


class UserManager(BaseUserManager):
    """Custom user manager for email-based authentication"""
    
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Custom user model with email as username field"""
    
    email = models.EmailField(unique=True, verbose_name='Email Address')
    # Every user must belong to exactly one tenant account. This is now enforced
    # at the database level (see migrations). Application code may safely rely
    # on user.account always being set.
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='users',
        null=True,
        blank=True,
        help_text='Owning account / tenant for this user',
    )
    first_name = models.CharField(max_length=30, verbose_name='First Name')
    last_name = models.CharField(max_length=30, verbose_name='Last Name')
    phone = models.TextField(blank=True, verbose_name='Phone Number')
    profile_picture = models.ImageField(upload_to='profile_pictures/', blank=True, null=True, verbose_name='Profile Picture')
    bio = models.TextField(blank=True, verbose_name='Bio')
    location = models.TextField(blank=True, verbose_name='Location')
    website = models.TextField(blank=True, verbose_name='Website')
    birth_date = models.DateField(blank=True, null=True, verbose_name='Birth Date')
    is_active = models.BooleanField(default=True, verbose_name='Active')
    is_staff = models.BooleanField(default=False, verbose_name='Staff Status')
    date_joined = models.DateTimeField(default=django_timezone.now, verbose_name='Date Joined')
    # Force user to change password on next login (e.g. after HR creates portal account with temp password).
    force_password_change = models.BooleanField(default=False, verbose_name='Force password change on next login')

    objects = UserManager()
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']
    
    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        db_table = 'accounts_user'
    
    def __str__(self):
        return self.email
    
    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()
    
    def get_short_name(self):
        return self.first_name


class SubUser(models.Model):
    """
    Team member under an account owner. Shares access to the same data (invoices,
    receipts, etc.) but logs in with their own email and password.
    All activity is tracked to the specific SubUser for audit purposes.
    """
    account_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sub_users'
    )
    # Optional link to a first-class Django User record. This enables team
    # members to participate in Django's built-in group/permission system while
    # retaining the legacy SubUser model for audit history.
    linked_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='linked_subuser',
        null=True,
        blank=True,
        help_text='Django auth user that represents this team member for permissions'
    )
    email = models.EmailField(verbose_name='Login Email', unique=True)
    full_name = models.CharField(max_length=150, verbose_name='Full Name')
    password_hash = models.CharField(max_length=128)  # Django-style hashed password
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(
        default=False,
        verbose_name='Staff Role',
        help_text='Staff can edit, delete, and manage team members. Active users can only create and view.'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Team Member'
        verbose_name_plural = 'Team Members'
        db_table = 'accounts_subuser'
        ordering = ['full_name']

    def __str__(self):
        return f"{self.full_name} ({self.email})"

    def set_password(self, raw_password):
        self.password_hash = make_password(raw_password)
        self.save(update_fields=['password_hash', 'updated_at'])

    def check_password(self, raw_password):
        return check_password(raw_password, self.password_hash)


class AccountGroup(models.Model):
    """
    Wrapper that scopes Django's built-in Group model to a specific Account
    without modifying the Group model itself.

    Invariants enforced at the application level:
    - A Group used by the application must be linked to exactly one Account
      via AccountGroup.
    - Users may only be assigned to Groups that belong to their own account.
    """
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='account_groups'
    )
    group = models.OneToOneField(
        Group,
        on_delete=models.CASCADE,
        related_name='account_group'
    )
    # Human-readable role name without the account prefix used in Group.name
    role_name = models.CharField(max_length=150)
    # When True, users in this role see all company records (no data isolation), like Company Admin.
    # Role name can be anything (e.g. "Company Read Only 1", "Company Read Only 2", "Finance Viewer").
    # Permissions are exactly what the admin assigns; we do not add or remove any.
    full_company_visibility = models.BooleanField(
        default=False,
        help_text='Users in this role see all company records (no data isolation). Use for read-only style roles with any name. Permissions are exactly what you assign below.'
    )

    class Meta:
        verbose_name = 'Account Group'
        verbose_name_plural = 'Account Groups'
        unique_together = [('account', 'role_name')]

    def __str__(self):
        return f'{self.role_name} ({self.account_id})'


class UserSession(models.Model):
    """
    Tracks user login sessions with device info, IP address, and location.
    Used for security monitoring and audit purposes.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sessions'
    )
    sub_user = models.ForeignKey(
        SubUser,
        on_delete=models.SET_NULL,
        related_name='sessions',
        blank=True,
        null=True,
        help_text='Team member session (when logged in as SubUser)'
    )
    session_key = models.CharField(max_length=255, blank=True, null=True)
    
    # Device Information
    device_type = models.CharField(max_length=50, blank=True)  # Mobile, Tablet, Desktop
    device_brand = models.CharField(max_length=100, blank=True)  # Samsung, Apple, etc.
    device_model = models.CharField(max_length=100, blank=True)  # iPhone 14, Galaxy S23, etc.
    browser_name = models.CharField(max_length=100, blank=True)  # Chrome, Firefox, Safari
    browser_version = models.CharField(max_length=50, blank=True)
    os_name = models.CharField(max_length=100, blank=True)  # Windows, macOS, Android, iOS
    os_version = models.CharField(max_length=50, blank=True)
    user_agent = models.TextField(blank=True)  # Full user agent string
    
    # Network Information
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    
    # Location Information (based on IP)
    city = models.CharField(max_length=100, blank=True)
    region = models.CharField(max_length=100, blank=True)  # State/Province
    country = models.CharField(max_length=100, blank=True)
    country_code = models.CharField(max_length=10, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    tz_name = models.CharField(max_length=100, blank=True, verbose_name='Timezone')
    isp = models.CharField(max_length=200, blank=True)  # Internet Service Provider
    
    # Timestamps
    login_time = models.DateTimeField(auto_now_add=True)
    logout_time = models.DateTimeField(blank=True, null=True)
    last_activity = models.DateTimeField(auto_now=True)
    
    # Session Status
    is_active = models.BooleanField(default=True)
    is_suspicious = models.BooleanField(default=False)
    suspicious_reason = models.TextField(blank=True)
    
    class Meta:
        verbose_name = 'User Session'
        verbose_name_plural = 'User Sessions'
        ordering = ['-login_time']
        db_table = 'accounts_user_session'
    
    def __str__(self):
        return f"{self.user.email} - {self.device_type} ({self.ip_address}) - {self.login_time}"
    
    @property
    def device_info(self):
        """Returns formatted device information"""
        parts = []
        if self.device_brand:
            parts.append(self.device_brand)
        if self.device_model:
            parts.append(self.device_model)
        if not parts and self.device_type:
            parts.append(self.device_type)
        return ' '.join(parts) if parts else 'Unknown Device'
    
    @property
    def browser_info(self):
        """Returns formatted browser information"""
        if self.browser_name and self.browser_version:
            return f"{self.browser_name} {self.browser_version}"
        return self.browser_name or 'Unknown Browser'
    
    @property
    def os_info(self):
        """Returns formatted OS information"""
        if self.os_name and self.os_version:
            return f"{self.os_name} {self.os_version}"
        return self.os_name or 'Unknown OS'
    
    @property
    def actor_display(self):
        """Who logged in - team member name or account owner"""
        if self.sub_user:
            return f"{self.sub_user.full_name} (team member)"
        return self.user.get_full_name() or self.user.email

    @property
    def location_info(self):
        """Returns formatted location information"""
        parts = []
        if self.city:
            parts.append(self.city)
        if self.region:
            parts.append(self.region)
        if self.country:
            parts.append(self.country)
        return ', '.join(parts) if parts else 'Unknown Location'
    
    @property
    def session_duration(self):
        """Returns the duration of the session"""
        end_time = self.logout_time or django_timezone.now()
        duration = end_time - self.login_time
        return duration
    
    def mark_logged_out(self):
        """Marks the session as logged out"""
        self.logout_time = django_timezone.now()
        self.is_active = False
        self.save()


class UserActivity(models.Model):
    """
    Tracks detailed user activities within the application.
    Records every significant action for audit and security purposes.
    
    Enhanced Features:
    - Stores exact changes made (old vs new values)
    - Stores deleted record data for recovery/audit
    - Links to actual objects for direct navigation
    - Tracks field-level changes for updates
    """
    
    # Activity Types
    ACTIVITY_TYPES = [
        ('LOGIN', 'User Login'),
        ('LOGOUT', 'User Logout'),
        ('LOGIN_FAILED', 'Failed Login Attempt'),
        ('PASSWORD_CHANGE', 'Password Changed'),
        ('PASSWORD_RESET', 'Password Reset Requested'),
        ('PROFILE_UPDATE', 'Profile Updated'),
        ('PAGE_VIEW', 'Page View'),
        ('CREATE', 'Created Record'),
        ('UPDATE', 'Updated Record'),
        ('DELETE', 'Deleted Record'),
        ('EXPORT', 'Data Export'),
        ('IMPORT', 'Data Import'),
        ('API_ACCESS', 'API Access'),
        ('FILE_UPLOAD', 'File Upload'),
        ('FILE_DOWNLOAD', 'File Download'),
        ('PERMISSION_CHANGE', 'Permission Changed'),
        ('SETTINGS_CHANGE', 'Settings Changed'),
        ('OTHER', 'Other Activity'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Tenant: every log row is tied to exactly one account (multi-tenant safe).
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='security_activities',
        null=True,
        blank=True,
        help_text='Account/company this activity belongs to; always set for authenticated actions.',
        db_index=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='security_activities',
        blank=True,
        null=True  # Null for failed login attempts
    )
    sub_user = models.ForeignKey(
        SubUser,
        on_delete=models.SET_NULL,
        related_name='activities',
        blank=True,
        null=True,
        help_text='Team member who performed the action (when logged in as SubUser)'
    )
    session = models.ForeignKey(
        UserSession,
        on_delete=models.SET_NULL,
        related_name='session_activities',
        blank=True,
        null=True
    )
    
    # Activity Details
    activity_type = models.CharField(max_length=50, choices=ACTIVITY_TYPES)
    description = models.TextField(blank=True)
    
    # What was accessed/modified
    app_name = models.CharField(max_length=100, blank=True)  # e.g., invoices, expenses
    model_name = models.CharField(max_length=100, blank=True)  # e.g., Invoice, Expense
    object_id = models.CharField(max_length=255, blank=True)  # ID of the object
    object_repr = models.TextField(blank=True)  # String representation of the object
    
    # Request Details
    url_path = models.TextField(blank=True)
    http_method = models.CharField(max_length=10, blank=True)  # GET, POST, PUT, DELETE
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True)
    
    # ENHANCED: Change Tracking
    # Stores what fields were changed and their old/new values
    changes = models.JSONField(
        default=dict, 
        blank=True,
        help_text='Stores field changes: {"field_name": {"old": "value", "new": "value"}}'
    )
    
    # ENHANCED: Deleted Record Data
    # When a record is deleted, store all its data here for audit purposes
    deleted_data = models.JSONField(
        default=dict, 
        blank=True,
        help_text='Stores complete record data when deleted for audit trail'
    )
    
    # ENHANCED: Direct object link
    # Full URL path to the object (for direct navigation)
    object_url = models.TextField(blank=True, help_text='Direct URL to the object')
    
    # Additional Context
    extra_data = models.JSONField(default=dict, blank=True)
    
    # Timestamps
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    
    # Security Flags
    is_suspicious = models.BooleanField(default=False)
    risk_level = models.CharField(
        max_length=20,
        choices=[
            ('LOW', 'Low Risk'),
            ('MEDIUM', 'Medium Risk'),
            ('HIGH', 'High Risk'),
            ('CRITICAL', 'Critical'),
        ],
        default='LOW'
    )
    
    class Meta:
        verbose_name = 'User Activity'
        verbose_name_plural = 'User Activities'
        ordering = ['-timestamp']
        db_table = 'accounts_user_activity'
        permissions = [
            ('view_activity_log', 'View activity log'),
        ]
        indexes = [
            models.Index(fields=['account', '-timestamp']),
            models.Index(fields=['user', '-timestamp']),
            models.Index(fields=['activity_type', '-timestamp']),
            models.Index(fields=['app_name', '-timestamp']),
        ]
    
    def __str__(self):
        user_str = self.user.email if self.user else 'Anonymous'
        return f"{user_str} - {self.get_activity_type_display()} - {self.timestamp}"

    @property
    def actor_display(self):
        """Who performed the action - team member or account owner"""
        if self.sub_user:
            return f"{self.sub_user.full_name} (team member)"
        if self.user:
            return self.user.get_full_name() or self.user.email
        return 'Anonymous'
    
    @property
    def has_changes(self):
        """Check if this activity has tracked field changes."""
        return bool(self.changes)
    
    @property
    def has_deleted_data(self):
        """Check if this activity has stored deleted record data."""
        return bool(self.deleted_data)
    
    @property
    def changes_summary(self):
        """Returns a human-readable summary of changes."""
        if not self.changes:
            return None
        
        summary = []
        for field, values in self.changes.items():
            old_val = values.get('old', 'N/A')
            new_val = values.get('new', 'N/A')
            # Truncate long values
            if isinstance(old_val, str) and len(old_val) > 50:
                old_val = old_val[:50] + '...'
            if isinstance(new_val, str) and len(new_val) > 50:
                new_val = new_val[:50] + '...'
            summary.append(f"{field}: '{old_val}' → '{new_val}'")
        return summary
    
    def get_object_link(self):
        """
        Try to generate a URL to the actual object.
        Returns the stored object_url if available, otherwise tries to construct one.
        """
        if self.object_url:
            return self.object_url
        
        # If object was deleted, we can't link to it
        if self.activity_type == 'DELETE':
            return None
        
        # Try to use url_path if it looks like a detail page
        if self.url_path and self.object_id:
            return self.url_path
        
        return None
    
    @classmethod
    def log_activity(cls, user=None, session=None, sub_user=None, account=None, activity_type='OTHER', 
                     description='', app_name='', model_name='', object_id='',
                     object_repr='', url_path='', http_method='', ip_address=None,
                     user_agent='', extra_data=None, is_suspicious=False, risk_level='LOW',
                     changes=None, deleted_data=None, object_url=''):
        """
        Convenience method to log an activity. Every log row should be tied to one account when known.

        - account: Account/company this activity belongs to (use request.company.account or user.account).
        - sub_user: Team member who performed the action (when logged in as SubUser).
        - changes: Dict of field changes {"field": {"old": val, "new": val}}.
        - deleted_data: Dict containing the deleted record's data.
        - object_url: Direct URL to the affected object.
        """
        if account is None and user and getattr(user, 'account_id', None):
            account = user.account
        return cls.objects.create(
            account=account,
            user=user,
            session=session,
            sub_user=sub_user,
            activity_type=activity_type,
            description=description,
            app_name=app_name,
            model_name=model_name,
            object_id=str(object_id) if object_id else '',
            object_repr=object_repr,
            url_path=url_path,
            http_method=http_method,
            ip_address=ip_address,
            user_agent=user_agent,
            extra_data=extra_data or {},
            is_suspicious=is_suspicious,
            risk_level=risk_level,
            changes=changes or {},
            deleted_data=deleted_data or {},
            object_url=object_url,
        )
