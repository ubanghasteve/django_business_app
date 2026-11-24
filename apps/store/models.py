# -*- coding: utf-8 -*-
"""
Store app - single Store model with company isolation, backend calculations,
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


class Store(models.Model):
    """
    Single store record per transaction/row. Company-scoped; all calculations
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
        related_name='store_records',
        null=True,
        blank=True,
        help_text='Tenant account; set from user.account on save if missing.',
    )
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='store_records',
        null=True,
        blank=True,
        help_text='Company profile; set from user company on save if missing.',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='store_records_created',
        help_text='User who created this record.',
    )

    # ----- Identifiers -----
    transaction_id = models.CharField(
        max_length=64,
        editable=False,
        help_text='STR- + 4 unique digits per company (e.g. STR-3847).',
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
    waste = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        help_text='Total waste quantity recorded for this store item.',
    )
    waste_input = models.CharField(
        max_length=255,
        default='',
        blank=True,
        help_text='Stores the original raw text the user typed for waste (e.g. "5bags damaged").',
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
    date = models.DateField(null=True, blank=True, help_text='User-editable date for backdating records.')
    opening_stock = models.DecimalField(
        max_digits=20, decimal_places=2, default=Decimal('0'),
        help_text='Opening stock / initial quantity before any movement (auto-set from previous record on create).',
    )
    opening_stock_input = models.CharField(
        max_length=50, default='', blank=True,
        help_text='Stores the original raw text the user typed (e.g. "50bags", "100 crates").',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    is_deleted = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='store_records_approved',
        help_text='User who set approval status to Approved.',
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    objects = models.Manager()
    visible_objects = TenantOwnedManager()

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Store'
        verbose_name_plural = 'Store'
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'transaction_id'],
                condition=Q(company_id__isnull=False),
                name='store_company_txn_id_uniq',
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
            ('print_store', 'Can print store'),
            ('download_store', 'Can download or export store data'),
            ('can_approve_store', 'Can approve store records'),
        ]

    def __str__(self):
        return f"{self.transaction_id} - {self.product_name}"

    # ----- Backend authority: calculations in save() -----

    @property
    def remaining_quantity(self):
        """Rem. qqt = Quantity In − Quantity Out."""
        return self.quantity_in - self.quantity_out

    @property
    def actual_quantity(self):
        """Actual usable quantity = Quantity In − Waste."""
        return self.quantity_in - self.waste

    @property
    def net_quantity(self):
        """Net quantity after waste and sales = Actual Usable Qty − Quantity Out."""
        return self.actual_quantity - self.quantity_out

    @property
    def waste_value(self):
        """Value of wasted items = Waste × Unit Price."""
        return self.waste * self.unit_price

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
        """Stock balance remaining = Net qty × Unit Price (value of remaining quantity after waste)."""
        return _decimal_safe(self.net_quantity) * _decimal_safe(self.unit_price)

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
                Store.objects.filter(company_id=self.company_id)
                .order_by('-created_at', '-pk')
                .values_list('balance_quantity', flat=True)
                .first()
            )
        else:
            # Existing record: previous = immediate predecessor in chronological order
            prev = (
                Store.objects.filter(company_id=self.company_id)
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
        return _decimal_safe(self.opening_stock) + _decimal_safe(self.quantity_in) - _decimal_safe(self.quantity_out)

    def _compute_stock_status(self):
        """Compute stock status from Net qty and low_stock_threshold. Persisted in save().
        Net qty = Qty In - Waste - Qty Out (what's actually available after waste and sales).
        - out_of_stock: net_quantity <= 0
        - low_stock: 0 < net_quantity <= low_stock_threshold  (when threshold > Net qty → Low Stock)
        - in_stock: net_quantity > low_stock_threshold
        """
        from decimal import ROUND_HALF_UP
        two_places = Decimal('0.01')
        # Use net_quantity so status reflects actual available after waste and sales
        net_qty = _decimal_safe(self.quantity_in) - _decimal_safe(self.waste) - _decimal_safe(self.quantity_out)
        net_qty = net_qty.quantize(two_places, rounding=ROUND_HALF_UP)
        thr = _decimal_safe(self.low_stock_threshold).quantize(two_places, rounding=ROUND_HALF_UP)
        if thr < 0:
            thr = Decimal('0')
        if net_qty <= 0:
            return 'out_of_stock'
        if net_qty <= thr:
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
        # STR- + 4 random digits, unique within the same company
        rng = random.SystemRandom() if hasattr(random, 'SystemRandom') else random
        max_attempts = 50
        company_id = self.company_id
        for _ in range(max_attempts):
            candidate = f"STR-{rng.randint(1000, 9999)}"
            exists = Store.objects.filter(company_id=company_id, transaction_id=candidate).exists()
            if not exists:
                self.transaction_id = candidate
                return self.transaction_id
        # Fallback: use UUID suffix to guarantee uniqueness (should never happen)
        self.transaction_id = f"STR-{rng.randint(1000, 9999)}-{uuid.uuid4().hex[:6]}"
        return self.transaction_id

    def _ensure_sn(self):
        if self.sn and self.sn > 0:
            return
        if not self.company_id:
            self.sn = 0
            return
        max_sn = (
            Store.objects.filter(company_id=self.company_id)
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
        self.waste = _apply_mixed_input(
            getattr(self, 'waste_input', ''), self.waste
        )
        self.low_stock_threshold = _apply_mixed_input(
            getattr(self, 'low_stock_threshold_input', ''), self.low_stock_threshold
        )
        # Keep threshold non-negative so stock status stays consistent
        if self.low_stock_threshold is not None and self.low_stock_threshold < 0:
            self.low_stock_threshold = Decimal('0')
        # Unit price: always non-negative in this model
        unit_price_numeric = _apply_mixed_input(
            getattr(self, 'unit_price_input', ''), self.unit_price
        )
        if unit_price_numeric is not None and unit_price_numeric >= 0:
            self.unit_price = unit_price_numeric

        # Tenant/company from created_by
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
                Store.objects.filter(company_id=self.company_id)
                .filter(
                    Q(created_at__gt=self.created_at)
                    | Q(created_at=self.created_at, pk__gt=self.pk)
                )
                .order_by('created_at', 'pk')
            )
            for obj in later:
                obj.save()


class StoreMovement(models.Model):
    """
    Immutable ledger row capturing quantity movements for a single store record.
    Created automatically whenever a store row's remaining quantity changes.
    """

    product = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="movements",
        help_text="Store row this movement belongs to.",
    )
    opening_stock = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Opening stock snapshot at the time of this movement.",
    )
    opening_stock_input = models.CharField(
        max_length=50, default='', blank=True,
        help_text='Raw opening stock input text (e.g. "50bags") at the time of movement.',
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
    waste = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Waste quantity at the time of movement.",
    )
    waste_input = models.CharField(
        max_length=255, default='', blank=True,
        help_text='Raw waste input text (e.g. "5bags damaged") at the time of movement.',
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
    waste_value = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Value of waste = waste × unit_price.",
    )
    approval_status = models.CharField(
        max_length=20,
        choices=Store.APPROVAL_STATUS_CHOICES,
        default='draft',
        help_text="Approval status of the store row at the time of movement.",
    )
    stock_status = models.CharField(
        max_length=20,
        choices=Store.STOCK_STATUS_CHOICES,
        help_text="Stock status snapshot (in_stock, low_stock, out_of_stock) at the time of movement.",
    )
    remark = models.TextField(null=True, blank=True)
    date = models.DateField(
        null=True, blank=True,
        help_text="User-set date from the product at time of movement (for backdated records).",
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="store_movements_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Store Movement"
        verbose_name_plural = "Store Movements"
        indexes = [
            models.Index(fields=["product", "-created_at"]),
        ]

    def __str__(self):
        return f"Movement for {self.product_id} at {self.created_at}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise IntegrityError("StoreMovement records are immutable and cannot be updated.")
        super().save(*args, **kwargs)


class WasteLog(models.Model):
    """
    Tracks individual waste incidents for store items.
    Waste can be recorded separately with reason, date, and notes.
    """
    WASTE_REASON_CHOICES = [
        ('damaged', 'Damaged'),
        ('expired', 'Expired'),
        ('shrinkage', 'Shrinkage'),
        ('spoilage', 'Spoilage'),
        ('contamination', 'Contamination'),
        ('quality_issue', 'Quality Issue'),
        ('handling', 'Handling Loss'),
        ('other', 'Other'),
    ]

    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name='waste_logs',
        help_text='The store item this waste log belongs to.',
    )
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='store_waste_logs',
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='store_waste_logs',
        null=True,
        blank=True,
    )
    quantity = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        help_text='Quantity wasted in this incident.',
    )
    unit_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        help_text='Unit price at time of waste recording.',
    )
    total_value = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal('0'),
        help_text='Total value of wasted items = quantity × unit_price.',
    )
    reason = models.CharField(
        max_length=50,
        choices=WASTE_REASON_CHOICES,
        default='other',
    )
    description = models.TextField(
        blank=True,
        help_text='Additional details about the waste incident.',
    )
    waste_date = models.DateField(
        default=timezone.now,
        help_text='Date when the waste occurred.',
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='store_waste_logs_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = models.Manager()
    visible_objects = TenantOwnedManager()

    class Meta:
        ordering = ['-waste_date', '-created_at']
        verbose_name = 'Waste Log'
        verbose_name_plural = 'Waste Logs'
        indexes = [
            models.Index(fields=['store', '-created_at']),
            models.Index(fields=['company', '-waste_date']),
            models.Index(fields=['reason']),
        ]

    def __str__(self):
        return f"Waste {self.quantity} of {self.store.product_name} on {self.waste_date}"

    def save(self, *args, **kwargs):
        self.total_value = _decimal_safe(self.quantity) * _decimal_safe(self.unit_price)
        if self.created_by_id and not self.company_id:
            from apps.core.utils import get_company_profile_for_user
            company = get_company_profile_for_user(self.created_by)
            if company:
                self.company_id = company.pk
            from apps.core.ownership import get_account_for_user
            acc = get_account_for_user(self.created_by)
            if acc:
                self.account_id = acc.id
        
        is_new = self.pk is None
        super().save(*args, **kwargs)
        
        if is_new:
            self._update_store_waste()

    def delete(self, *args, **kwargs):
        store = self.store
        super().delete(*args, **kwargs)
        self._update_store_waste_from_db(store)

    def _update_store_waste(self):
        """Recalculate total waste from all waste logs for this store."""
        total_waste = WasteLog.objects.filter(store=self.store).aggregate(
            total=models.Sum('quantity')
        )['total'] or Decimal('0')
        Store.objects.filter(pk=self.store.pk).update(waste=total_waste)

    @staticmethod
    def _update_store_waste_from_db(store):
        """Static method to recalculate waste from DB after delete."""
        total_waste = WasteLog.objects.filter(store=store).aggregate(
            total=models.Sum('quantity')
        )['total'] or Decimal('0')
        Store.objects.filter(pk=store.pk).update(waste=total_waste)


import json


class StoreCategory(models.Model):
    """
    Product categories for organizing store items.
    Simple name/description/color approach.
    """
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='store_categories',
        null=True,
        blank=True,
    )
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='store_categories',
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    color = models.CharField(
        max_length=20,
        default='#007bff',
        help_text='Hex color code, e.g. #007bff',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='store_categories_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = models.Manager()
    visible_objects = TenantOwnedManager()

    class Meta:
        ordering = ['name']
        verbose_name = 'Store Category'
        verbose_name_plural = 'Store Categories'
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'name'],
                condition=Q(company_id__isnull=False),
                name='store_category_company_name_uniq',
            ),
        ]
        permissions = [
            ('view_store_category', 'Can view store category'),
        ]

    def __str__(self):
        return self.name


class StoreCustomField(models.Model):
    """
    Dynamic custom fields that can be attached to Store records.
    Supports text, number, select, date field types.
    """
    FIELD_TYPE_CHOICES = [
        ('text', 'Text'),
        ('number', 'Number'),
        ('decimal', 'Decimal'),
        ('select', 'Select'),
        ('date', 'Date'),
        ('boolean', 'Yes/No'),
    ]

    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='store_custom_fields',
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=100)
    field_key = models.SlugField(
        max_length=50,
        help_text='Unique key used in templates, e.g. "serial_number"',
    )
    field_type = models.CharField(
        max_length=20,
        choices=FIELD_TYPE_CHOICES,
        default='text',
    )
    options = models.TextField(
        blank=True,
        help_text='JSON list of options for select fields, e.g. ["Option 1","Option 2"]',
    )
    required = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = models.Manager()
    visible_objects = TenantOwnedManager()

    class Meta:
        ordering = ['order', 'name']
        verbose_name = 'Store Custom Field'
        verbose_name_plural = 'Store Custom Fields'
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'field_key'],
                condition=Q(company_id__isnull=False),
                name='store_custom_field_company_key_uniq',
            ),
        ]
        permissions = [
            ('view_store_customfield', 'Can view store custom field'),
        ]

    def __str__(self):
        return f"{self.name} ({self.field_key})"

    def get_options(self):
        if not self.options:
            return []
        try:
            return json.loads(self.options)
        except (json.JSONDecodeError, TypeError):
            return []


class StoreCustomFieldValue(models.Model):
    """
    Stores the value of a custom field for a specific Store record.
    """
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name='custom_field_values',
    )
    field = models.ForeignKey(
        StoreCustomField,
        on_delete=models.CASCADE,
        related_name='values',
    )
    value = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['store', 'field']]
        verbose_name = 'Store Custom Field Value'
        verbose_name_plural = 'Store Custom Field Values'

    def __str__(self):
        return f"{self.field.name}: {self.value}"


class StoreCustomForm(models.Model):
    """
    Custom form definitions: a named collection of custom fields
    plus branding/layout preferences for store printouts.
    """
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='store_custom_forms',
        null=True,
        blank=True,
    )
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='store_custom_forms',
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    fields = models.TextField(
        blank=True,
        default='[]',
        help_text='JSON list of field keys to include, in order.',
    )
    primary_color = models.CharField(max_length=20, default='#1976d2')
    secondary_color = models.CharField(max_length=20, default='#f8f9fa')
    accent_color = models.CharField(max_length=20, default='#e9ecef')
    text_color = models.CharField(max_length=20, default='#333333')
    show_logo = models.BooleanField(default=True)
    show_company_name = models.BooleanField(default=True)
    show_currency = models.BooleanField(default=True)
    footer_text = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='store_custom_forms_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = models.Manager()
    visible_objects = TenantOwnedManager()

    class Meta:
        ordering = ['name']
        verbose_name = 'Store Custom Form'
        verbose_name_plural = 'Store Custom Forms'
        permissions = [
            ('view_store_customform', 'Can view store custom form'),
        ]

    def __str__(self):
        return self.name

    def get_field_keys(self):
        if not self.fields:
            return []
        try:
            return json.loads(self.fields)
        except (json.JSONDecodeError, TypeError):
            return []

    def set_field_keys(self, keys):
        self.fields = json.dumps(keys)


class StoreLayout(models.Model):
    """
    Store list layout: which columns to show, their order, width, label.
    Allows per-company customizable store table views.
    """
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='store_layouts',
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    columns = models.TextField(
        blank=True,
        default='[]',
        help_text='JSON list of column definitions: {"key","label","width","visible","order"}',
    )
    supports_calculations = models.BooleanField(default=True)
    show_totals = models.BooleanField(default=True)
    show_grand_total = models.BooleanField(default=True)
    primary_color = models.CharField(max_length=20, default='#007bff')
    secondary_color = models.CharField(max_length=20, default='#6c757d')
    accent_color = models.CharField(max_length=20, default='#e9ecef')
    text_color = models.CharField(max_length=20, default='#333333')
    is_default = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='store_layouts_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = models.Manager()
    visible_objects = TenantOwnedManager()

    class Meta:
        ordering = ['name']
        verbose_name = 'Store Layout'
        verbose_name_plural = 'Store Layouts'
        permissions = [
            ('view_store_layout', 'Can view store layout'),
        ]

    def __str__(self):
        return self.name

    def get_columns(self):
        if not self.columns:
            return self._default_columns()
        try:
            cols = json.loads(self.columns)
            if isinstance(cols, list):
                return cols
        except (json.JSONDecodeError, TypeError):
            pass
        return self._default_columns()

    def _default_columns(self):
        return [
            {'key': 'sn', 'label': 'S/N', 'width': '60px', 'visible': True, 'order': 0},
            {'key': 'product_name', 'label': 'Product Name', 'width': 'auto', 'visible': True, 'order': 1},
            {'key': 'category', 'label': 'Category', 'width': '120px', 'visible': True, 'order': 2},
            {'key': 'company_name', 'label': 'Company', 'width': '150px', 'visible': True, 'order': 3},
            {'key': 'quantity_in', 'label': 'Qty In', 'width': '80px', 'visible': True, 'order': 4},
            {'key': 'quantity_out', 'label': 'Qty Out', 'width': '80px', 'visible': True, 'order': 5},
            {'key': 'remaining_quantity', 'label': 'Rem. Qty', 'width': '80px', 'visible': True, 'order': 6},
            {'key': 'unit_price', 'label': 'Unit Price', 'width': '100px', 'visible': True, 'order': 7},
            {'key': 'total_amount', 'label': 'Total', 'width': '120px', 'visible': True, 'order': 8},
            {'key': 'stock_status', 'label': 'Status', 'width': '110px', 'visible': True, 'order': 9},
            {'key': 'approval_status', 'label': 'Approval', 'width': '100px', 'visible': True, 'order': 10},
            {'key': 'created_at', 'label': 'Date', 'width': '100px', 'visible': True, 'order': 11},
        ]

    def get_visible_columns(self):
        cols = self.get_columns()
        return sorted([c for c in cols if c.get('visible', True)], key=lambda x: x.get('order', 0))

    def save(self, *args, **kwargs):
        if self.is_default:
            StoreLayout.objects.filter(
                company=self.company, is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

    def get_calculation_fields(self):
        return json.dumps([
            {'key': 'total_amount', 'label': 'Total Amount', 'type': 'currency'},
        ])

