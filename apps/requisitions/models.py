# -*- coding: utf-8 -*-
from django.db import models, IntegrityError
from django.conf import settings
from django.contrib.auth import get_user_model
import time
import random

from apps.core.ownership import TenantOwnedManager
from apps.core.sync_mixin import SyncMixin

User = get_user_model()


def requisition_signature_upload_path(instance, filename):
    """Generate upload path for requisition signatures"""
    return f'requisitions/signatures/{instance.id or "temp"}/{filename}'


class Requisition(SyncMixin, models.Model):
    """
    Requisition model with company-level isolation via account + created_by.
    Same visibility pattern as Invoice/Waybill: Company Admin sees all, team members see own.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('completed', 'Completed'),
    ]

    # Tenant and creator for per-team-member isolation (same pattern as Invoice/Waybill)
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='requisitions',
        null=True,
        blank=True,
        help_text='Tenant account; set from user.account on save if missing.',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='requisitions_created',
        help_text='User who created this requisition.',
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='requisitions_approved',
        help_text='User who approved this requisition (set when status becomes Approved).',
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    # Required for isolation: company (CompanyProfile) - used for display/filter; account is source of truth
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='requisitions',
        null=True,
        blank=True,
        help_text='Company profile; set from user company on save if missing.',
    )

    organization_name = models.CharField(max_length=255)
    address = models.TextField(blank=True)
    contact_number = models.CharField(max_length=50, blank=True)
    date = models.DateField(null=True, blank=True)
    job_type = models.CharField(max_length=100, blank=True)
    print_product = models.CharField(max_length=255, blank=True)
    quantity = models.CharField(max_length=100, blank=True)
    colors = models.CharField(max_length=255, blank=True)
    size = models.CharField(max_length=100, blank=True)
    micron = models.CharField(max_length=100, blank=True)
    other_info = models.TextField(blank=True)
    signature = models.ImageField(upload_to=requisition_signature_upload_path, blank=True, null=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft',
    )
    reference_number = models.CharField(max_length=50, unique=True, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)
    # updated_at from SyncMixin (for conflict resolution)

    objects = models.Manager()
    visible_objects = TenantOwnedManager()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['account', '-created_at']),
            models.Index(fields=['reference_number']),
            models.Index(fields=['status']),
            models.Index(fields=['date']),
            models.Index(fields=['organization_name']),
        ]
        permissions = [
            ("print_requisition", "Can print requisition"),
            ("download_requisition", "Can download or export requisition data"),
            ("can_approve_requisition", "Can approve requisitions"),
        ]

    def __str__(self):
        return f"{self.reference_number} - {self.organization_name}"

    def save(self, *args, **kwargs):
        # Per-team-member isolation: set tenant and company from created_by when missing
        if self.created_by_id and (not self.account_id or not self.company_id):
            if not self.account_id:
                if getattr(self.created_by, 'account_id', None):
                    self.account_id = self.created_by.account_id
                else:
                    from apps.core.ownership import get_account_for_user
                    acc = get_account_for_user(self.created_by)
                    if acc:
                        self.account_id = acc.id
            if not self.company_id:
                from apps.core.utils import get_company_profile_for_user
                company = get_company_profile_for_user(self.created_by)
                if company:
                    self.company_id = company.pk
        if not self.reference_number:
            self.reference_number = self.generate_reference_number()

        max_retries = 3
        for retry in range(max_retries):
            try:
                super().save(*args, **kwargs)
                break
            except IntegrityError as e:
                if 'reference_number' in str(e) and retry < max_retries - 1:
                    self.reference_number = self.generate_reference_number()
                    continue
                raise

    def generate_reference_number(self):
        """Generate unique reference REQ-YYYY-XXX (XXX = random 3 digits, unique across DB)."""
        from datetime import datetime
        year = datetime.now().year
        used_refs = set(Requisition.objects.values_list('reference_number', flat=True))
        for _ in range(100):
            suffix = random.randint(100, 999)
            ref = f"REQ-{year}-{suffix}"
            if ref not in used_refs:
                return ref
        suffix = (int(time.time() * 1000) % 900) + 100
        return f"REQ-{year}-{suffix}"
