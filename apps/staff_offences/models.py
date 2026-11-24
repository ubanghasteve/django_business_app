# -*- coding: utf-8 -*-
from django.db import models, IntegrityError
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models import Sum
from decimal import Decimal
import time
import random

from apps.core.ownership import TenantOwnedManager
from apps.core.sync_mixin import SyncMixin


def staff_offence_signature_upload_path(instance, filename):
    """Store each register's authorized signature under its own media folder."""
    import os
    ext = os.path.splitext(filename)[1].lower() or '.png'
    ref = (instance.reference_number or f'reg-{instance.pk or "new"}').replace('/', '-')
    return f'staff_offences/signatures/{ref}/{instance.pk or "new"}{ext}'


class StaffOffenceRegister(SyncMixin, models.Model):
    """
    Monthly offence register for one staff member (name typed manually).
    Same tenant visibility pattern as Requisition: account + created_by.
    """
    PAYMENT_UNPAID = 'unpaid'
    PAYMENT_PARTIALLY_PAID = 'partially_paid'
    PAYMENT_PAID = 'paid'
    PAYMENT_WAIVED = 'waived'
    PAYMENT_PENDING_APPROVAL = 'pending_approval'
    PAYMENT_STATUS_CHOICES = [
        (PAYMENT_UNPAID, 'Unpaid'),
        (PAYMENT_PARTIALLY_PAID, 'Partially Paid'),
        (PAYMENT_PAID, 'Paid'),
        (PAYMENT_WAIVED, 'Waived'),
        (PAYMENT_PENDING_APPROVAL, 'Pending Approval'),
    ]
    PAYMENT_STATUS_HELP = {
        PAYMENT_UNPAID: 'No payment has been recorded against the approved amount.',
        PAYMENT_PARTIALLY_PAID: 'The staff member has paid some, but not all, of the amount due.',
        PAYMENT_PAID: 'The full approved amount has been paid or settled.',
        PAYMENT_WAIVED: 'The authorized officer has formally cancelled the amount due.',
        PAYMENT_PENDING_APPROVAL: 'The offence or proposed penalty has not yet been approved. It should not be treated as an amount due.',
    }

    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='staff_offence_registers',
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='staff_offence_registers_created',
    )
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='staff_offence_registers',
        null=True,
        blank=True,
    )
    staff_name = models.CharField(
        max_length=255,
        help_text='Staff member name typed by HR (not linked to HR employee records).',
    )
    department_name = models.CharField(
        max_length=200,
        blank=True,
        default='',
        help_text='Department name typed manually.',
    )
    year = models.PositiveIntegerField()
    month = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(12)],
    )
    reference_number = models.CharField(max_length=50, unique=True, editable=False)
    authorized_signature = models.ImageField(
        upload_to=staff_offence_signature_upload_path,
        blank=True,
        null=True,
        help_text='Authorized signature for this monthly register only (not shared across registers).',
    )
    authorized_signatory_name = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='Name of the person who authorized/signed this register.',
    )
    payment_status = models.CharField(
        max_length=32,
        choices=PAYMENT_STATUS_CHOICES,
        default=PAYMENT_PENDING_APPROVAL,
        db_index=True,
        help_text='Payment / settlement status for this monthly register.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = models.Manager()
    visible_objects = TenantOwnedManager()

    class Meta:
        ordering = ['year', 'month', 'created_at', 'id']
        indexes = [
            models.Index(fields=['account', 'year', 'month']),
            models.Index(fields=['reference_number']),
            models.Index(fields=['year', 'month']),
            models.Index(fields=['staff_name']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['account', 'staff_name', 'year', 'month'],
                name='unique_staff_offence_register_per_month',
            ),
        ]
        permissions = [
            ('print_staffoffenceregister', 'Can print staff offence register'),
            ('download_staffoffenceregister', 'Can download staff offence register'),
        ]
        verbose_name = 'Staff Offence Register'
        verbose_name_plural = 'Staff Offence Registers'

    def __str__(self):
        return f'{self.reference_number} — {self.staff_name} ({self.month_label})'

    @property
    def month_label(self):
        from calendar import month_name
        try:
            return f'{month_name[self.month]} {self.year}'
        except (IndexError, TypeError):
            return f'{self.month}/{self.year}'

    @property
    def payment_status_label(self):
        return dict(self.PAYMENT_STATUS_CHOICES).get(self.payment_status, self.payment_status)

    @property
    def payment_status_help(self):
        return self.PAYMENT_STATUS_HELP.get(self.payment_status, '')

    def offence_count(self):
        return self.entries.filter(is_deleted=False).count()

    def monthly_total(self):
        total = (
            self.entries.filter(is_deleted=False)
            .aggregate(s=Sum('amount'))
            .get('s')
        )
        return total if total is not None else Decimal('0.00')

    def save(self, *args, **kwargs):
        if self.staff_name:
            self.staff_name = self.staff_name.strip()
        if self.department_name:
            self.department_name = self.department_name.strip()
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
                err = str(e)
                if 'reference_number' in err and retry < max_retries - 1:
                    self.reference_number = self.generate_reference_number()
                    continue
                raise

    def generate_reference_number(self):
        """Generate unique reference OFF-YYYY-XXXX."""
        from datetime import datetime
        year = self.year or datetime.now().year
        used_refs = set(
            StaffOffenceRegister.objects.values_list('reference_number', flat=True)
        )
        for _ in range(200):
            suffix = random.randint(1, 9999)
            ref = f'OFF-{year}-{suffix:04d}'
            if ref not in used_refs:
                return ref
        suffix = (int(time.time() * 1000) % 9000) + 1000
        return f'OFF-{year}-{suffix:04d}'


class StaffOffenceEntry(SyncMixin, models.Model):
    """Single offence line on a monthly register."""
    register = models.ForeignKey(
        StaffOffenceRegister,
        on_delete=models.CASCADE,
        related_name='entries',
    )
    date = models.DateField()
    description = models.CharField(max_length=500)
    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='staff_offence_entries_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = models.Manager()

    class Meta:
        ordering = ['date', 'id']
        verbose_name = 'Staff Offence Entry'
        verbose_name_plural = 'Staff Offence Entries'
        indexes = [
            models.Index(fields=['register', 'date']),
        ]

    def __str__(self):
        return f'{self.date} — {self.description} ({self.amount})'
