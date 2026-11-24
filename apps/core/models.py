from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import datetime, timedelta

User = get_user_model()


class Account(models.Model):
    """
    Tenant / account model.
    Every business object and user is ultimately scoped to an Account to ensure
    strict multi-tenant isolation.
    """
    owner = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='owned_accounts',
        help_text='Primary owner of this account (usually the first user who registered). SET_NULL on delete to avoid circular FK with User.account.'
    )
    # Human-friendly name for the account/company. This will typically mirror
    # CompanyProfile.company_name but is stored here to keep the tenant concept
    # independent from presentation.
    name = models.CharField(max_length=255, blank=True, default='')
    is_active = models.BooleanField(default=True)
    is_approved = models.BooleanField(
        default=False,
        help_text='When False, account has profile-only access. Super admin approves to unlock full access.'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Account'
        verbose_name_plural = 'Accounts'

    def __str__(self):
        return self.name or f'Account #{self.pk}'


def company_logo_upload_path(instance, filename):
    """Generate upload path for company logos"""
    return f'company/logos/{instance.user.id}/{filename}'


def company_signature_upload_path(instance, filename):
    """Generate upload path for company signatures"""
    return f'company/signatures/{instance.user.id}/{filename}'


class CompanyProfile(models.Model):
    """Company profile model for business information"""
    # Primary tenant scoping - one profile per account.
    # We keep the existing user field for backward compatibility and to avoid
    # breaking templates that still reference request.user.company_profile.
    account = models.OneToOneField(
        Account,
        on_delete=models.CASCADE,
        related_name='company_profile',
        null=True,
        blank=True,
        help_text='Owning account for this company profile'
    )
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='company_profile')
    
    # Basic Information
    company_name = models.CharField(max_length=200, blank=True, default='')
    email = models.EmailField(blank=True, default='')
    phone = models.CharField(max_length=500, blank=True, default='')
    website = models.CharField(max_length=500, blank=True, default='')
    
    # Address Information
    address_line_1 = models.CharField(max_length=200, blank=True)
    address_line_2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=100, blank=True)
    
    # Business Information
    business_type = models.CharField(max_length=100, blank=True)
    tax_id = models.CharField(max_length=50, blank=True)
    registration_number = models.CharField(max_length=50, blank=True)
    
    # Financial Settings
    currency_code = models.CharField(max_length=3, default='NGN')
    currency_symbol = models.CharField(max_length=5, default='₦')
    default_tax = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    
    # Branding
    logo = models.ImageField(upload_to=company_logo_upload_path, blank=True, null=True)
    signature = models.ImageField(upload_to=company_signature_upload_path, blank=True, null=True)
    
    # Display Settings
    show_bank_details = models.BooleanField(default=True, help_text="Show bank details on invoices and other documents")
    show_signature = models.BooleanField(default=True, help_text="Show signature on invoices and other documents")
    
    # Colors and Styling
    primary_color = models.CharField(max_length=7, default='#1976d2', help_text='Main brand color for headers, buttons, and accents')
    secondary_color = models.CharField(max_length=7, default='#f8f9fa', help_text='Background color for sections and cards')
    accent_color = models.CharField(max_length=7, default='#e9ecef', help_text='Border and divider color')
    text_color = models.CharField(max_length=7, default='#333333', help_text='Main text color for documents')
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Company Profile'
        verbose_name_plural = 'Company Profiles'
    
    def __str__(self):
        return f"{self.company_name} - {self.user.get_full_name()}"
    
    @property
    def address(self):
        """Backward compatibility property for old templates"""
        parts = []
        if self.address_line_1:
            parts.append(self.address_line_1)
        if self.address_line_2:
            parts.append(self.address_line_2)
        if self.city:
            parts.append(self.city)
        if self.state:
            parts.append(self.state)
        if self.postal_code:
            parts.append(self.postal_code)
        if self.country:
            parts.append(self.country)
        return ', '.join(parts) if parts else ''
    
    def delete_old_logo(self):
        """Delete old logo file when new one is uploaded"""
        if self.logo and hasattr(self.logo, 'path'):
            try:
                import os
                if os.path.isfile(self.logo.path):
                    os.remove(self.logo.path)
            except (ValueError, OSError):
                pass
    
    def delete_old_signature(self):
        """Delete old signature file when new one is uploaded"""
        if self.signature and hasattr(self.signature, 'path'):
            try:
                import os
                if os.path.isfile(self.signature.path):
                    os.remove(self.signature.path)
            except (ValueError, OSError):
                pass


class BankAccount(models.Model):
    """Bank account model for company banking information"""
    company = models.ForeignKey(CompanyProfile, on_delete=models.CASCADE, related_name='bank_accounts')
    
    # Bank Information
    bank_name = models.CharField(max_length=200)
    account_name = models.CharField(max_length=200)
    account_number = models.CharField(max_length=50)
    account_type = models.CharField(max_length=50, choices=[
        ('savings', 'Savings'),
        ('current', 'Current'),
        ('checking', 'Checking'),
    ], default='current')
    
    # Additional Information
    routing_number = models.CharField(max_length=50, blank=True)
    swift_code = models.CharField(max_length=20, blank=True)
    iban = models.CharField(max_length=50, blank=True)
    
    # Settings
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Bank Account'
        verbose_name_plural = 'Bank Accounts'
        unique_together = ['company', 'account_number']
    
    def __str__(self):
        return f"{self.bank_name} - {self.account_number}"
    
    def save(self, *args, **kwargs):
        # Ensure only one default account per company
        if self.is_default:
            BankAccount.objects.filter(company=self.company).update(is_default=False)
        super().save(*args, **kwargs)


class UserActivity(models.Model):
    """Track user activity for streak calculation and analytics"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='activities')
    activity_type = models.CharField(max_length=50, choices=[
        ('login', 'Login'),
        ('dashboard_view', 'Dashboard View'),
        ('invoice_created', 'Invoice Created'),
        ('quotation_created', 'Quotation Created'),
        ('waybill_created', 'Waybill Created'),
        ('client_added', 'Client Added'),
        ('payment_received', 'Payment Received'),
    ])
    
    # Activity details
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'User Activity'
        verbose_name_plural = 'User Activities'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['activity_type', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.user.get_full_name()} - {self.activity_type} - {self.created_at.date()}"
    
    @classmethod
    def record_activity(cls, user, activity_type, description='', metadata=None):
        """Record a new user activity"""
        return cls.objects.create(
            user=user,
            activity_type=activity_type,
            description=description,
            metadata=metadata or {}
        )
    
    @classmethod
    def get_user_streak(cls, user):
        """Calculate user's current login streak"""
        today = timezone.now().date()
        streak = 0
        
        # Get all login activities for this user
        login_activities = cls.objects.filter(
            user=user,
            activity_type='login'
        ).order_by('-created_at')
        
        if not login_activities.exists():
            return 0
        
        # Check consecutive days
        current_date = today
        for activity in login_activities:
            activity_date = activity.created_at.date()
            
            if activity_date == current_date:
                streak += 1
                current_date = current_date - timedelta(days=1)
            elif activity_date < current_date:
                # Gap found, streak broken
                break
            # If activity_date > current_date, it's a future date, skip
        
        return streak
    
    @classmethod
    def get_user_stats(cls, user, days=30):
        """Get user activity statistics for the last N days"""
        start_date = timezone.now().date() - timedelta(days=days)
        
        activities = cls.objects.filter(
            user=user,
            created_at__gte=start_date
        )
        
        stats = {
            'total_activities': activities.count(),
            'login_count': activities.filter(activity_type='login').count(),
            'dashboard_views': activities.filter(activity_type='dashboard_view').count(),
            'invoices_created': activities.filter(activity_type='invoice_created').count(),
            'quotations_created': activities.filter(activity_type='quotation_created').count(),
            'waybills_created': activities.filter(activity_type='waybill_created').count(),
            'clients_added': activities.filter(activity_type='client_added').count(),
            'payments_received': activities.filter(activity_type='payment_received').count(),
        }
        
        # Daily activity breakdown
        daily_stats = {}
        for i in range(days):
            date = start_date + timedelta(days=i)
            daily_activities = activities.filter(created_at__date=date)
            daily_stats[date.strftime('%Y-%m-%d')] = daily_activities.count()
        
        stats['daily_breakdown'] = daily_stats
        return stats


class DashboardSettings(models.Model):
    """User dashboard customization settings"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='dashboard_settings')
    
    # Display preferences
    show_revenue_chart = models.BooleanField(default=True)
    show_invoice_stats = models.BooleanField(default=True)
    show_quotation_stats = models.BooleanField(default=True)
    show_waybill_stats = models.BooleanField(default=True)
    show_client_stats = models.BooleanField(default=True)
    show_inventory_stats = models.BooleanField(default=True)
    
    # Auto-refresh settings
    auto_refresh_enabled = models.BooleanField(default=True)
    refresh_interval = models.IntegerField(default=30, help_text="Refresh interval in seconds")
    
    # Goal settings
    monthly_revenue_goal = models.DecimalField(max_digits=12, decimal_places=2, default=100000.00)
    monthly_invoice_goal = models.IntegerField(default=50)
    monthly_client_goal = models.IntegerField(default=10)
    
    # Notification preferences
    show_low_stock_alerts = models.BooleanField(default=True)
    show_overdue_invoice_alerts = models.BooleanField(default=True)
    show_quotation_followup_alerts = models.BooleanField(default=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Dashboard Settings'
        verbose_name_plural = 'Dashboard Settings'
    
    def __str__(self):
        return f"Dashboard Settings - {self.user.get_full_name()}"
    
    @classmethod
    def get_or_create_settings(cls, user):
        """Get or create dashboard settings for a user"""
        settings, created = cls.objects.get_or_create(user=user)
        return settings