# -*- coding: utf-8 -*-
"""
Expense app - Expense model with company isolation.
Columns: Expense ID, Expense Date, Expense Category, Department, Vendor, PO Number,
Description, Product ID, Product Name, Product Category, Product Description,
Unit of Measurement, Quantity Purchased, Quantity Out, Remaining Quantity (computed),
Unit Price, Total Purchase Value (computed), Stock Value Remaining (computed),
Quantity Threshold, Low Stock Alert (computed), Subtotal, Tax, Discount, Total Amount,
Payment Method, Payment Date, Receipt Upload, Status, Approved By, Created By,
Created Date, Last Updated, Action (UI only).
"""
from django.db import models, IntegrityError
from django.db.models import Max, Q
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator
from django.utils import timezone
from decimal import Decimal
import re
import random
import uuid

from apps.core.ownership import TenantOwnedManager
from apps.core.sync_mixin import SyncMixin

User = get_user_model()


def _decimal_safe(value, default=Decimal('0')):
    if value is None:
        return default
    try:
        d = Decimal(str(value))
        return d if not (d.is_nan() or d.is_infinite()) else default
    except Exception:
        return default


def expense_receipt_upload_path(instance, filename):
    """Upload path for expense receipts: expense/receipts/<company_id>/<year>/<month>/<filename>."""
    y = instance.expense_date.year if instance.expense_date else timezone.now().year
    m = instance.expense_date.month if instance.expense_date else timezone.now().month
    company = getattr(instance, 'company_id', None) or 0
    return f'expense/receipts/{company}/{y}/{m}/{filename}'


class Expense(SyncMixin, models.Model):
    """
    Expense record. Company-scoped; totals computed in save().
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    PAYMENT_METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('card', 'Card'),
        ('transfer', 'Bank Transfer'),
        ('cheque', 'Cheque'),
        ('mobile', 'Mobile Money'),
        ('other', 'Other'),
    ]

    # ----- Tenant & audit -----
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='expense_records',
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='expense_records',
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='expense_records_created',
        verbose_name='Created By',
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='expense_records_approved',
        verbose_name='Approved By',
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    # ----- Expense ID (transaction_id) -----
    transaction_id = models.CharField(
        max_length=64,
        editable=False,
        verbose_name='Expense ID',
        help_text='Expense ID e.g. EXP-3847.',
    )
    sn = models.PositiveIntegerField(default=0, editable=False)

    # ----- Header -----
    expense_date = models.DateField(
        default=timezone.now,
        verbose_name='Expense Date',
        help_text='Expense Date',
    )
    expense_category = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='Expense Category',
        help_text='Expense Category',
    )
    department = models.CharField(max_length=100, blank=True, verbose_name='Department')
    vendor = models.CharField(max_length=255, blank=True, verbose_name='Vendor')
    po_number = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='PO Number',
    )
    description = models.TextField(blank=True, verbose_name='Description')

    # ----- Product -----
    product_id = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='Product ID',
    )
    product_name = models.CharField(max_length=255, blank=True, verbose_name='Product Name')
    product_category = models.CharField(max_length=100, blank=True, verbose_name='Product Category')
    product_description = models.TextField(blank=True, verbose_name='Product Description')
    unit_of_measurement = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='Unit of Measurement',
        help_text='e.g. pieces, kg, litres',
    )

    # ----- Quantities & price -----
    # Raw user input (e.g. "500bags", "7.5 kg") for display; parsed to Decimal in save()
    quantity_purchased_input = models.CharField(
        max_length=255, blank=True, default='',
        help_text='Original user input for Quantity Purchased (e.g. "500bags").',
    )
    quantity_out_input = models.CharField(
        max_length=255, blank=True, default='',
        help_text='Original user input for Quantity Out (e.g. "50bags").',
    )
    unit_price_input = models.CharField(
        max_length=255, blank=True, default='',
        help_text='Original user input for Unit Price (e.g. "₦45000 per bag").',
    )
    quantity_threshold_input = models.CharField(
        max_length=255, blank=True, default='',
        help_text='Original user input for Quantity Threshold (e.g. "10bags").',
    )
    quantity_purchased = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Quantity Purchased',
    )
    quantity_out = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Quantity Out',
    )
    unit_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Unit Price',
    )
    quantity_threshold = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Quantity Threshold',
        help_text='Quantity Threshold for low stock alert.',
    )

    # ----- Amounts (stored) -----
    subtotal = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Subtotal',
    )
    tax = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Tax',
    )
    discount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        verbose_name='Discount',
    )
    total_amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal('0'),
        verbose_name='Total Amount',
    )

    # ----- Payment -----
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        default='other',
        blank=True,
        verbose_name='Payment Method',
    )
    payment_date = models.DateField(null=True, blank=True, verbose_name='Payment Date')
    receipt_upload = models.FileField(
        upload_to=expense_receipt_upload_path,
        blank=True,
        null=True,
        verbose_name='Receipt Upload',
    )

    # ----- Status -----
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft',
        verbose_name='Status',
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Created Date')
    # updated_at from SyncMixin (for conflict resolution)

    objects = models.Manager()
    visible_objects = TenantOwnedManager()

    class Meta:
        ordering = ['-expense_date', '-created_at']
        verbose_name = 'Expense'
        verbose_name_plural = 'Expenses'
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'transaction_id'],
                condition=Q(company_id__isnull=False),
                name='expense_company_txn_id_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['company', '-expense_date']),
            models.Index(fields=['company', '-created_at']),
            models.Index(fields=['transaction_id']),
            models.Index(fields=['status']),
            models.Index(fields=['expense_category']),
            models.Index(fields=['vendor']),
            models.Index(fields=['product_name']),
        ]
        permissions = [
            ('print_expense', 'Can print expense'),
            ('download_expense', 'Can download or export expense data'),
            ('can_approve_expense', 'Can approve expense records'),
        ]

    def __str__(self):
        return f"{self.transaction_id} - {self.product_name or self.description or 'Expense'}"

    # ----- Computed (no DB column) -----
    @property
    def remaining_quantity(self):
        """Remaining Quantity = Quantity Purchased - Quantity Out."""
        return _decimal_safe(self.quantity_purchased) - _decimal_safe(self.quantity_out)

    @property
    def total_purchase_value(self):
        """Total Purchase Value = Quantity Purchased × Unit Price."""
        return _decimal_safe(self.quantity_purchased) * _decimal_safe(self.unit_price)

    @property
    def stock_value_remaining(self):
        """Stock Value Remaining = Remaining Quantity × Unit Price."""
        return self.remaining_quantity * _decimal_safe(self.unit_price)

    @property
    def low_stock_alert(self):
        """True when Remaining Quantity ≤ Quantity Threshold."""
        return self.remaining_quantity <= _decimal_safe(self.quantity_threshold)

    @property
    def unit_label(self):
        """Best-effort unit text from mixed inputs (e.g. "500bags" -> "bags")."""
        for raw in (
            getattr(self, 'quantity_purchased_input', '') or '',
            getattr(self, 'quantity_out_input', '') or '',
            getattr(self, 'quantity_threshold_input', '') or '',
        ):
            if not raw:
                continue
            s = str(raw)
            unit = re.sub(r'-?\d+(\.\d+)?', '', s, count=1).strip()
            if not unit:
                continue
            unit = re.sub(r'\b0+(\.0+)?\b', '', unit).strip()
            unit = re.sub(r'\.0+$', '', unit).strip()
            if unit:
                return unit
        return ''

    def _ensure_transaction_id(self):
        if self.transaction_id:
            return self.transaction_id
        rng = random.SystemRandom() if hasattr(random, 'SystemRandom') else random
        company_id = self.company_id
        for _ in range(50):
            candidate = f"EXP-{rng.randint(1000, 9999)}"
            if not Expense.objects.filter(company_id=company_id, transaction_id=candidate).exists():
                self.transaction_id = candidate
                return self.transaction_id
        self.transaction_id = f"EXP-{rng.randint(1000, 9999)}-{uuid.uuid4().hex[:6]}"
        return self.transaction_id

    def _ensure_sn(self):
        if self.sn and self.sn > 0:
            return
        if not self.company_id:
            self.sn = 0
            return
        max_sn = Expense.objects.filter(company_id=self.company_id).aggregate(m=Max('sn')).get('m')
        self.sn = (max_sn or 0) + 1

    def _compute_totals(self):
        """
        Subtotal: use stored value if non-zero; otherwise set to quantity_purchased × unit_price.
        Total Amount: subtotal - discount + tax (always).
        """
        sub = _decimal_safe(self.subtotal)
        qty = _decimal_safe(self.quantity_purchased)
        price = _decimal_safe(self.unit_price)
        if sub == 0 and (qty or price):
            sub = qty * price
        self.subtotal = sub
        self.total_amount = sub - _decimal_safe(self.discount) + _decimal_safe(self.tax)

    @classmethod
    def renumber_sn_for_company(cls, company_id):
        if not company_id:
            return
        records = list(cls.objects.filter(company_id=company_id).order_by('expense_date', 'created_at', 'pk'))
        for sn, obj in enumerate(records, start=1):
            obj.sn = sn
        if records:
            cls.objects.bulk_update(records, ['sn'])

    def save(self, *args, **kwargs):
        # Parse mixed input (e.g. "500bags", "₦5,492") into Decimal fields before totals
        from apps.waybills.utils.quantity_parser import extract_numeric_value
        def _apply_mixed(raw_value, current_decimal):
            if raw_value is None or str(raw_value).strip() == '':
                return current_decimal
            try:
                numeric = extract_numeric_value(raw_value)
                return _decimal_safe(Decimal(str(numeric)))
            except Exception:
                return current_decimal
        self.quantity_purchased = _apply_mixed(
            getattr(self, 'quantity_purchased_input', ''), self.quantity_purchased
        )
        self.quantity_out = _apply_mixed(
            getattr(self, 'quantity_out_input', ''), self.quantity_out
        )
        self.unit_price = max(Decimal('0'), _apply_mixed(
            getattr(self, 'unit_price_input', ''), self.unit_price
        ))
        self.quantity_threshold = max(Decimal('0'), _apply_mixed(
            getattr(self, 'quantity_threshold_input', ''), self.quantity_threshold
        ))
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
        self._ensure_transaction_id()
        self._ensure_sn()
        self._compute_totals()
        max_retries = 3
        for attempt in range(max_retries):
            try:
                super().save(*args, **kwargs)
                break
            except IntegrityError as e:
                if 'transaction_id' in str(e) and attempt < max_retries - 1:
                    self.transaction_id = None
                    self._ensure_transaction_id()
                    continue
                raise


class ExpenseMovement(models.Model):
    """
    Immutable ledger row capturing quantity/price changes for a single expense record.
    Created automatically whenever an expense row's remaining quantity or related fields change.
    Report table uses: balance = (quantity_purchased - quantity_out) × unit_price,
    stock_value_remaining = quantity_after × unit_price.
    """
    expense = models.ForeignKey(
        Expense,
        on_delete=models.CASCADE,
        related_name='movements',
        help_text='Expense record this movement belongs to.',
    )
    quantity_purchased = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0'),
        verbose_name='Quantity Purchased',
    )
    quantity_out = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0'),
        verbose_name='Quantity Out',
    )
    quantity_before = models.DecimalField(
        max_digits=14, decimal_places=2,
        help_text='Remaining quantity before this movement.',
    )
    quantity_after = models.DecimalField(
        max_digits=14, decimal_places=2,
        help_text='Remaining quantity after this movement.',
    )
    unit_price = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0'),
        verbose_name='Unit Price',
    )
    balance = models.DecimalField(
        max_digits=16, decimal_places=2, default=Decimal('0'),
        help_text='Movement value = (quantity_purchased - quantity_out) × unit_price.',
    )
    stock_value_remaining = models.DecimalField(
        max_digits=16, decimal_places=2, default=Decimal('0'),
        help_text='Quantity_after × unit_price.',
    )
    status = models.CharField(
        max_length=20,
        choices=Expense.STATUS_CHOICES,
        default='draft',
        help_text='Status of the expense row at the time of movement.',
    )
    low_stock_alert = models.BooleanField(
        default=False,
        help_text='True when remaining_quantity ≤ quantity_threshold at time of movement.',
    )
    remark = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='expense_movements_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Expense Movement'
        verbose_name_plural = 'Expense Movements'
        indexes = [
            models.Index(fields=['expense', '-created_at']),
        ]

    def __str__(self):
        return f"Movement for expense {self.expense_id} at {self.created_at}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise IntegrityError("ExpenseMovement records are immutable and cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise IntegrityError("ExpenseMovement records are immutable and cannot be deleted.")
