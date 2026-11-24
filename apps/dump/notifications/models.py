"""
Unified Notification model for all business app events.
Respects RBAC, data isolation, and multi-tenant permissions.
"""
from django.db import models
from django.conf import settings
from django.utils import timezone


class Notification(models.Model):
    """
    User notification for events across messaging, HR, inventory, expense,
    requisitions, and other apps. Tenant-scoped and permission-aware.
    """
    SOURCE_APP_CHOICES = [
        ('messaging', 'Messaging'),
        ('hr_staff', 'HR & Staff'),
        ('inventory', 'Inventory'),
        ('expense', 'Expense'),
        ('requisitions', 'Requisitions'),
        ('invoices', 'Invoices'),
        ('quotations', 'Quotations'),
        ('waybills', 'Waybills'),
        ('receipts', 'Receipts'),
        ('clients', 'Clients'),
        ('job_orders', 'Job Orders'),
        ('system', 'System'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
        help_text='Recipient of the notification',
    )
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='notifications',
        help_text='Tenant scope for multi-tenant isolation',
    )
    source_app = models.CharField(
        max_length=50,
        choices=SOURCE_APP_CHOICES,
        db_index=True,
        help_text='Which app this notification originated from',
    )
    title = models.CharField(max_length=255)
    message = models.TextField()
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications_triggered',
        help_text='User who triggered this notification (e.g. sender, approver)',
    )
    action_url = models.CharField(max_length=500, blank=True, help_text='Relative or absolute URL to the record')
    target_type = models.CharField(max_length=100, blank=True, db_index=True)
    target_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read', '-created_at'], name='notif_user_read_created'),
            models.Index(fields=['account', '-created_at'], name='notif_account_created'),
            models.Index(fields=['user', 'account', '-created_at'], name='notif_user_account_created'),
        ]
        verbose_name = 'Notification'
        verbose_name_plural = 'Notifications'

    def __str__(self):
        return f'{self.title} for {self.user} ({self.source_app})'
