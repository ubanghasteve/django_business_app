"""
Minimal model so Django creates a ContentType and permissions for the mailing app.
Used for: database permissions table, Company Admin sync, and role/permission UI.
Bulk mailing feature is gated by permission mailing.use_bulk_mailing.
"""
from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class BulkSendLog(models.Model):
    """
    Optional log of bulk send operations. Exists primarily so the mailing app
    has a ContentType and permissions in the database (e.g. use_bulk_mailing).
    Company Admin and role sync (post_migrate / approval) will include these permissions.
    """
    SEND_TYPE_EMAIL = 'email'
    SEND_TYPE_SMS = 'sms'
    SEND_TYPE_CHOICES = [
        (SEND_TYPE_EMAIL, 'Email'),
        (SEND_TYPE_SMS, 'SMS'),
    ]

    sent_at = models.DateTimeField(auto_now_add=True)
    send_type = models.CharField(max_length=10, choices=SEND_TYPE_CHOICES)
    recipient_count = models.PositiveIntegerField(default=0)
    initiated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bulk_send_logs',
    )

    class Meta:
        app_label = 'mailing'
        verbose_name = 'Bulk send log'
        verbose_name_plural = 'Bulk send logs'
        default_permissions = ()  # No add/change/delete/view; we only use custom permission
        permissions = [
            ('use_bulk_mailing', 'Use bulk mailing'),
        ]
