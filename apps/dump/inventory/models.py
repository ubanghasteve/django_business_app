# -*- coding: utf-8 -*-
"""
Inventory app - single Inventory model with company isolation, backend calculations,
workflow and approval status, and strict column order per specification.

Status determination: see STATUS_TRACKING.md for how each status (In Stock, Low Stock,
Out of Stock, Approved, etc.) is determined and persisted.
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
from apps.waybills.utils.quantity_parser import extract_numeric_value

User = get_user_model()


def _decimal_safe(value, default=Decimal('0')):
    if value is None:
        return default
    try:
        d = Decimal(str(value))
        return d if not (d.is_nan() or d.is_infinite()) else default
    except Exception:
        return default


class Inventory(models.Model):
    """
    Single inventory record per transaction/row. Company-scoped; all calculations
    in save(). Column order: Product Name, Category, Company, Vendor, Stock Location,
    Phone Number, Quantity In, Quantity Out, Rem. qqt, Balance, Balance Quantity,
    Approval Status, Remark, Created By, Created At, Action.
    """
    APPROVAL_STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    WORKFLOW_STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending_approval', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('posted', 'Posted'),
    ]
    # Stock status: COMPUTED in save() from balance_quantity vs low_stock_threshold (see _compute_stock_status).
    STOCK_STATUS_CHOICES = [
        ('out_of_stock', 'Out of Stock'),   # balance_quantity <= 0
        ('low_stock', 'Low Stock'),         # 0 < balance_quantity <= low_stock_threshold
        ('in_stock', 'In Stock'),           # balance_quantity > low_stock_threshold
    ]

    # ----- Tenant & creator (company isolation) -----
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='inventory_records',
        null=True,
        blank=True,
        help_text='Tenant account; set from user.account on save if missing.',
    )
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='inventory_records',
        null=True,
        blank=True,
        help_text='Company profile; set from user company on save if missing.',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventory_records_created',
        help_text='User who created this record.',
    )

    # ----- Identifiers -----
    transaction_id = models.CharField(
        max_length=64,
        editable=False,
        help_text='INV- + 4 unique digits per company (e.g. INV-3847).',
    )
    sn = models.PositiveIntegerField(
        default=0,
        editable=False,
        help_text='Auto-increment per company (S/N).',
    )

    # ----- Table columns (exact order per spec) -----
    product_name = models.CharField(max_length=255)
    category = models.CharField(max_length=100, blank=True)
    company_name = models.CharField(
        max_length=255,
        blank=True,
        help_text='Company name (e.g. manufacturer/supplier); fillable. When empty, display uses company FK.',
    )
    vendor = models.CharField(max_length=255, blank=True)
    stock_location = models.CharField(max_length=255, blank=True)
    phone_number = models.CharField(max_length=50, blank=True)

    # Raw user input strings for quantity/price/threshold.
    # These allow entries like "500bags", "7.5 kg", "-10pcs" while backend
    # computations use the parsed numeric values on the DecimalFields.
    quantity_in_input = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='Original user input for Quantity In (e.g. "500bags").',
    )
    quantity_out_input = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='Original user input for Quantity Out (e.g. "50bags").',
    )
    unit_price_input = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='Original user input for Unit Price (e.g. "₦45000 per bag").',
    )
    low_stock_threshold_input = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='Original user input for Low stock threshold (e.g. "10bags").',
    )

    quantity_in = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    quantity_out = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    unit_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
    )

    # ----- Computed (persisted for display/indexing; also available as property) -----
    # total_amount = quantity_in * unit_price (stored as balance/total for "Balance" column)
    total_amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal('0'),
        editable=False,
    )
    # stock_balance_remaining = (quantity_in - quantity_out) * unit_price; computed in save()
    stock_balance_remaining = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal('0'),
        editable=False,
    )
    # balance_quantity = previous_balance_quantity + quantity_in - quantity_out (running balance)
    balance_quantity = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        editable=False,
    )
    low_stock_threshold = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('10'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    # Computed in save() from balance_quantity and low_stock_threshold; not user-editable.
    stock_status = models.CharField(
        max_length=20,
        choices=STOCK_STATUS_CHOICES,
        default='in_stock',
        editable=False,
    )
    # User-set; updated via list dropdown (ajax_status_update) or form save.
    approval_status = models.CharField(
        max_length=20,
        choices=APPROVAL_STATUS_CHOICES,
        default='draft',
    )
    workflow_status = models.CharField(
        max_length=20,
        choices=WORKFLOW_STATUS_CHOICES,
        default='draft',
    )
    remark = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    is_deleted = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventory_records_approved',
        help_text='User who set approval status to Approved.',
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    objects = models.Manager()
    visible_objects = TenantOwnedManager()

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Inventory'
        verbose_name_plural = 'Inventory'
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'transaction_id'],
                condition=Q(company_id__isnull=False),
                name='inventory_company_txn_id_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['company', '-created_at']),
            models.Index(fields=['transaction_id']),
            models.Index(fields=['approval_status']),
            models.Index(fields=['stock_status']),
            models.Index(fields=['workflow_status']),
            models.Index(fields=['product_name']),
            models.Index(fields=['vendor']),
            models.Index(fields=['stock_location']),
        ]
        permissions = [
            ('print_inventory', 'Can print inventory'),
            ('download_inventory', 'Can download or export inventory data'),
            ('can_approve_inventory', 'Can approve inventory records'),
        ]

    def __str__(self):
        return f"{self.transaction_id} - {self.product_name}"

    # ----- Backend authority: calculations in save() -----

    @property
    def remaining_quantity(self):
        """Rem. qqt = Quantity In − Quantity Out."""
        return self.quantity_in - self.quantity_out

    @property
    def unit_label(self) -> str:
        """
        Best-effort unit text extracted from any of the mixed inputs.

        Examples:
            "500bags"   -> "bags"
            "7.5 kg"    -> "kg"
            "100 pieces"-> "pieces"
        """
        for raw in (
            getattr(self, 'quantity_in_input', '') or '',
            getattr(self, 'quantity_out_input', '') or '',
            getattr(self, 'low_stock_threshold_input', '') or '',
        ):
            if not raw:
                continue
            s = str(raw)
            # Strip the first numeric segment (with optional decimal / sign) and return the rest.
            unit = re.sub(r'-?\d+(\.\d+)?', '', s, count=1).strip()
            if not unit:
                continue
            # Clean up common numeric suffix fragments accidentally left in the text
            # e.g. "kg.00" -> "kg", "bags 0.00" -> "bags"
            unit = re.sub(r'\b0+(\.0+)?\b', '', unit).strip()
            unit = re.sub(r'\.0+$', '', unit).strip()
            if unit:
                return unit
        return ''

    def _compute_stock_balance_remaining(self):
        """Stock balance remaining = Rem. qqt × Unit Price (value of remaining quantity)."""
        return _decimal_safe(self.remaining_quantity) * _decimal_safe(self.unit_price)

    def _compute_total_amount(self):
        return _decimal_safe(self.quantity_in) * _decimal_safe(self.unit_price)

    def _get_previous_balance_quantity(self):
        """Return the balance_quantity of the record immediately before this one in (created_at, pk) order.
        For a new record (pk is None), returns the newest existing record's balance (we append to the chain).
        For an existing record, returns the predecessor's balance so the running balance chain stays correct.
        """
        if not self.company_id:
            return Decimal('0')
        if self.pk is None:
            # New record: previous = current "head" of the chain (newest by created_at, pk)
            prev = (
                Inventory.objects.filter(company_id=self.company_id)
                .order_by('-created_at', '-pk')
                .values_list('balance_quantity', flat=True)
                .first()
            )
        else:
            # Existing record: previous = immediate predecessor in chronological order
            prev = (
                Inventory.objects.filter(company_id=self.company_id)
                .filter(
                    Q(created_at__lt=self.created_at)
                    | Q(created_at=self.created_at, pk__lt=self.pk)
                )
                .order_by('-created_at', '-pk')
                .values_list('balance_quantity', flat=True)
                .first()
            )
        return _decimal_safe(prev)

    def _compute_balance_quantity(self):
        prev = self._get_previous_balance_quantity()
        return prev + _decimal_safe(self.quantity_in) - _decimal_safe(self.quantity_out)

    def _compute_stock_status(self):
        """Compute stock status from balance_quantity and low_stock_threshold. Persisted in save().
        Rules (strict, no gaps):
        - out_of_stock: balance_quantity <= 0
        - low_stock: 0 < balance_quantity <= low_stock_threshold
        - in_stock: balance_quantity > low_stock_threshold
        """
        bq = self.balance_quantity
        thr = _decimal_safe(self.low_stock_threshold)
        if bq <= 0:
            return 'out_of_stock'
        if bq <= thr:
            return 'low_stock'
        return 'in_stock'

    def _ensure_remark(self):
        if not (self.remark or '').strip():
            self.remark = (
                f"Stock updated: +{self.quantity_in} / -{self.quantity_out}"
            )

    def _ensure_transaction_id(self):
        if self.transaction_id:
            return self.transaction_id
        # INV- + 4 random digits, unique within the same company
        rng = random.SystemRandom() if hasattr(random, 'SystemRandom') else random
        max_attempts = 50
        company_id = self.company_id
        for _ in range(max_attempts):
            candidate = f"INV-{rng.randint(1000, 9999)}"
            exists = Inventory.objects.filter(company_id=company_id, transaction_id=candidate).exists()
            if not exists:
                self.transaction_id = candidate
                return self.transaction_id
        # Fallback: use UUID suffix to guarantee uniqueness (should never happen)
        self.transaction_id = f"INV-{rng.randint(1000, 9999)}-{uuid.uuid4().hex[:6]}"
        return self.transaction_id

    def _ensure_sn(self):
        if self.sn and self.sn > 0:
            return
        if not self.company_id:
            self.sn = 0
            return
        max_sn = (
            Inventory.objects.filter(company_id=self.company_id)
            .aggregate(m=Max('sn'))
            .get('m')
        )
        self.sn = (max_sn or 0) + 1

    @classmethod
    def renumber_sn_for_company(cls, company_id):
        """
        Reassign S/N to 1, 2, 3, ... for all records in the company (by created_at, pk order).
        Call after a record is deleted so numbering has no gaps.
        """
        if not company_id:
            return
        records = list(
            cls.objects.filter(company_id=company_id).order_by('created_at', 'pk')
        )
        if not records:
            return
        for sn, obj in enumerate(records, start=1):
            obj.sn = sn
        cls.objects.bulk_update(records, ['sn'])

    def save(self, *args, **kwargs):
        # If raw mixed inputs are present, parse them into numeric values so all
        # downstream calculations (remaining qty, balances, status) stay accurate.
        # This allows entries like "500bags" or "45,000 per bag" while preserving
        # the original text in the *_input fields.
        def _apply_mixed_input(raw_value, current_decimal):
            if raw_value is None or str(raw_value).strip() == '':
                return current_decimal
            try:
                numeric = extract_numeric_value(raw_value)
                return _decimal_safe(Decimal(str(numeric)))
            except Exception:
                return current_decimal

        # Quantity in/out and low stock threshold
        self.quantity_in = _apply_mixed_input(
            getattr(self, 'quantity_in_input', ''), self.quantity_in
        )
        self.quantity_out = _apply_mixed_input(
            getattr(self, 'quantity_out_input', ''), self.quantity_out
        )
        self.low_stock_threshold = _apply_mixed_input(
            getattr(self, 'low_stock_threshold_input', ''), self.low_stock_threshold
        )
        # Unit price: always non-negative in this model
        unit_price_numeric = _apply_mixed_input(
            getattr(self, 'unit_price_input', ''), self.unit_price
        )
        if unit_price_numeric is not None and unit_price_numeric >= 0:
            self.unit_price = unit_price_numeric

        # Tenant/company from created_by
        if self.created_by_id and (not self.account_id or not self.company_id):
            if not self.account_id and getattr(self.created_by, 'account_id', None):
                self.account_id = self.created_by.account_id
            if not self.company_id:
                from apps.core.utils import get_company_profile_for_user
                company = get_company_profile_for_user(self.created_by)
                if company:
                    self.company_id = company.pk
        self._ensure_transaction_id()
        self._ensure_sn()
        self._ensure_remark()
        # Balance (total amount) = quantity_in * unit_price
        self.total_amount = self._compute_total_amount()
        # Stock balance remaining = (quantity_in - quantity_out) * unit_price
        self.stock_balance_remaining = self._compute_stock_balance_remaining()
        # Balance quantity = previous + quantity_in - quantity_out
        self.balance_quantity = self._compute_balance_quantity()
        self.stock_status = self._compute_stock_status()
        max_retries = 3
        for attempt in range(max_retries):
            try:
                super().save(*args, **kwargs)
                break
            except IntegrityError as e:
                if 'transaction_id' in str(e) and attempt < max_retries - 1:
                    self.transaction_id = None  # force regenerate in next _ensure_transaction_id
                    self._ensure_transaction_id()
                    continue
                raise
        # Keep the running-balance chain correct: recompute any records after this one (chronological order)
        if self.company_id and self.pk:
            later = (
                Inventory.objects.filter(company_id=self.company_id)
                .filter(
                    Q(created_at__gt=self.created_at)
                    | Q(created_at=self.created_at, pk__gt=self.pk)
                )
                .order_by('created_at', 'pk')
            )
            for obj in later:
                obj.save()


class InventoryMovement(models.Model):
    """
    Immutable ledger row capturing quantity movements for a single inventory record.
    Created automatically whenever an inventory row's remaining quantity changes.
    """

    product = models.ForeignKey(
        Inventory,
        on_delete=models.PROTECT,
        related_name="movements",
        help_text="Inventory row this movement belongs to.",
    )
    quantity_in = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
    )
    quantity_out = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
    )
    quantity_before = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text="Remaining quantity before this movement.",
    )
    quantity_after = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text="Remaining quantity after this movement.",
    )
    unit_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
    )
    balance = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Movement value = (quantity_in - quantity_out) × unit_price.",
    )
    stock_balance_remaining = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Quantity_after × unit_price.",
    )
    approval_status = models.CharField(
        max_length=20,
        choices=Inventory.APPROVAL_STATUS_CHOICES,
        default='draft',
        help_text="Approval status of the inventory row at the time of movement.",
    )
    stock_status = models.CharField(
        max_length=20,
        choices=Inventory.STOCK_STATUS_CHOICES,
        help_text="Stock status snapshot (in_stock, low_stock, out_of_stock) at the time of movement.",
    )
    remark = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_movements_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Oldest movement first so the history reads top‑to‑bottom.
        ordering = ["created_at"]
        verbose_name = "Inventory Movement"
        verbose_name_plural = "Inventory Movements"
        indexes = [
            models.Index(fields=["product", "-created_at"]),
        ]

    def __str__(self):
        return f"Movement for {self.product_id} at {self.created_at}"

    def save(self, *args, **kwargs):
        # Immutable: allow only insert, never updates.
        if self.pk is not None:
            raise IntegrityError("InventoryMovement records are immutable and cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # Immutable: prevent deletion entirely.
        raise IntegrityError("InventoryMovement records are immutable and cannot be deleted.")

