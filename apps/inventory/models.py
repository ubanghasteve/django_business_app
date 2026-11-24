# -*- coding: utf-8 -*-
"""
Inventory app - single Inventory model with company isolation, backend calculations,
workflow and approval status, and strict column order per specification.

Status determination: see STATUS_TRACKING.md for how each status (In Stock, Low Stock,
Out of Stock, Approved, etc.) is determined and persisted.
"""
from django.db import models, IntegrityError, transaction
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


def _extract_unit_from_mixed_input(raw):
    """Unit text from values like '5000kg', '10 Rolls', '7.5 kg', '45,678 kg'."""
    if not raw:
        return ''
    s = str(raw).strip().replace(',', '')
    if not s:
        return ''
    unit = re.sub(r'-?\d+(\.\d+)?', '', s, count=1)
    unit = unit.strip()
    unit = re.sub(r'\b0+(\.0+)?\b', '', unit).strip()
    unit = re.sub(r'\.0+$', '', unit).strip()
    return unit


def format_quantity_number(value):
    """Format a quantity with thousands separators (no currency symbol)."""
    d = _decimal_safe(value)
    if d == d.to_integral_value():
        return f'{int(d):,}'
    text = f'{float(d):,.2f}'
    return text.rstrip('0').rstrip('.') or '0'


def _floor_zero(value):
    """Never show or persist a negative remaining stock figure."""
    d = _decimal_safe(value)
    return d if d > 0 else Decimal('0')


def net_remaining_quantity(qty_in, waste=None, qty_out=None):
    """Available stock = Qty In − Waste − Qty Out (never below zero)."""
    return _floor_zero(
        _decimal_safe(qty_in) - _decimal_safe(waste) - _decimal_safe(qty_out)
    )


def over_issue_message(quantity, available, qty_in, waste=None):
    """User-facing error when a withdrawal would exceed remaining stock."""
    available = _floor_zero(available)
    qty_in_s = format_quantity_number(qty_in)
    qty_s = format_quantity_number(quantity)
    avail_s = format_quantity_number(available)
    waste = _decimal_safe(waste)
    waste_bit = f' minus waste {format_quantity_number(waste)}' if waste > 0 else ''
    if available <= 0:
        return (
            f'No stock remaining to take out. Quantity in is {qty_in_s}{waste_bit}. '
            'Add stock first, or delete extra withdrawals.'
        )
    return (
        f'Cannot take out {qty_s}: only {avail_s} remaining in stock '
        f'(Quantity in {qty_in_s}{waste_bit}).'
    )


def over_waste_message(quantity, available, qty_in):
    available = _floor_zero(available)
    if available <= 0:
        return (
            f'No stock remaining to record as waste. Quantity in is {format_quantity_number(qty_in)} '
            '(after quantity already taken out).'
        )
    return (
        f'Cannot record waste {format_quantity_number(quantity)}: only '
        f'{format_quantity_number(available)} remaining in stock.'
    )


def normalize_quantity_input(raw):
    """
    Parse mixed quantity text (commas, units) into a canonical display string.
    Examples: '45,678 kg' -> '45,678 kg', '5000kg' -> '5,000kg'
    """
    if raw is None:
        return ''
    text = str(raw).strip()
    if not text:
        return ''
    numeric = extract_numeric_value(text)
    if numeric <= 0 and not re.search(r'\d', text.replace(',', '')):
        return text
    unit = _extract_unit_from_mixed_input(text)
    num_str = format_quantity_number(numeric)
    if not unit:
        return num_str
    plain = text.replace(',', '')
    if re.search(r'\d\s+' + re.escape(unit), plain, re.IGNORECASE):
        return f'{num_str} {unit}'
    if re.search(r'\d' + re.escape(unit), plain, re.IGNORECASE):
        return f'{num_str}{unit}'
    return f'{num_str} {unit}'


def normalize_unit_price_input(raw):
    """
    Parse unit price text (commas, decimals, optional £ $ ₦ N typed by user).
    Returns digits with thousands separators only; currency comes from company profile in the UI.
    """
    if raw is None:
        return ''
    text = str(raw).strip()
    if not text:
        return ''
    if not re.search(r'\d', text.replace(',', '')):
        return text
    numeric = extract_numeric_value(text)
    return format_quantity_number(numeric)


def compose_total_quantity_input(total, sample_inputs):
    """
    Build a header total that keeps the storekeeper's unit (kg, Rolls, etc.)
    using the same style as the underlying log lines when possible.
    """
    total = _decimal_safe(total)
    num = format_quantity_number(total)
    samples = [str(s).strip() for s in (sample_inputs or []) if s and str(s).strip()]
    unit = ''
    for s in samples:
        u = _extract_unit_from_mixed_input(s)
        if u:
            unit = u
            break
    if not unit:
        return num
    spaced = False
    for s in samples:
        u = _extract_unit_from_mixed_input(s)
        if u and re.search(r'\d\s+' + re.escape(u), s, re.IGNORECASE):
            spaced = True
            break
    if spaced:
        return f'{num} {unit}'
    return f'{num}{unit}'


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
    waste = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        help_text='Total waste quantity recorded for this inventory item.',
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
        """Rem. qqt = Quantity In − Quantity Out (never below zero)."""
        return _floor_zero(_decimal_safe(self.quantity_in) - _decimal_safe(self.quantity_out))

    @property
    def actual_quantity(self):
        """Actual usable quantity = Quantity In − Waste (never below zero)."""
        return _floor_zero(_decimal_safe(self.quantity_in) - _decimal_safe(self.waste))

    @property
    def net_quantity(self):
        """Net remaining stock = Qty In − Waste − Qty Out (never below zero)."""
        return net_remaining_quantity(self.quantity_in, self.waste, self.quantity_out)

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
            unit = _extract_unit_from_mixed_input(raw)
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
        """
        Balance qty shown on the Inventory table.

        The business expectation on the list screen is that "Balance qty" represents the
        remaining stock for that product row (after waste and issues), not a running
        company-wide chain across unrelated products.
        """
        return _floor_zero(self.net_quantity)

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
        # Note: we intentionally do NOT cascade-save later rows. Each row is treated
        # as its own product stock card on the UI, so saving one row should not
        # mutate other rows' "Balance qty".


class InventoryMovement(models.Model):
    """
    Immutable ledger row capturing quantity movements for a single inventory record.
    Created automatically whenever an inventory row's remaining quantity changes.
    """

    product = models.ForeignKey(
        Inventory,
        on_delete=models.CASCADE,
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
    waste = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Waste quantity at the time of movement.",
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
        ordering = ["created_at"]
        verbose_name = "Inventory Movement"
        verbose_name_plural = "Inventory Movements"
        indexes = [
            models.Index(fields=["product", "-created_at"]),
        ]

    def __str__(self):
        return f"Movement for {self.product_id} at {self.created_at}"

    @property
    def remaining_after_display(self):
        """Net remaining at this snapshot (In − Waste − Out, never below zero)."""
        qty_in = _decimal_safe(self.quantity_in)
        qty_out = _decimal_safe(self.quantity_out)
        if qty_in == 0 and qty_out == 0:
            return _floor_zero(self.quantity_after)
        return net_remaining_quantity(qty_in, self.waste, qty_out)

    @property
    def stock_remaining_display(self):
        """Stock value left = net remaining × unit price."""
        return _decimal_safe(self.remaining_after_display) * _decimal_safe(self.unit_price)

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise IntegrityError("InventoryMovement records are immutable and cannot be updated.")
        super().save(*args, **kwargs)


class WasteLog(models.Model):
    """
    Tracks individual waste incidents for inventory items.
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

    inventory = models.ForeignKey(
        Inventory,
        on_delete=models.CASCADE,
        related_name='waste_logs',
        help_text='The inventory item this waste log belongs to.',
    )
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='waste_logs',
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='waste_logs',
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
    quantity_input = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='Original user input (e.g. "2 Rolls").',
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
        related_name='waste_logs_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = models.Manager()
    visible_objects = TenantOwnedManager()

    class Meta:
        ordering = ['-waste_date', '-created_at']
        verbose_name = 'Waste Log'
        verbose_name_plural = 'Waste Logs'
        indexes = [
            models.Index(fields=['inventory', '-created_at']),
            models.Index(fields=['company', '-waste_date']),
            models.Index(fields=['reason']),
        ]

    def __str__(self):
        return f"Waste {self.quantity} of {self.inventory.product_name} on {self.waste_date}"

    def save(self, *args, **kwargs):
        if self.quantity_input:
            self.quantity_input = normalize_quantity_input(self.quantity_input)
            self.quantity = _decimal_safe(extract_numeric_value(self.quantity_input))
        elif self.quantity:
            self.quantity = _decimal_safe(self.quantity)
        if self.quantity <= 0:
            raise ValueError('Waste quantity must be greater than zero.')
        inv = self.inventory
        is_new = self.pk is None
        if is_new and (not self.unit_price or self.unit_price == 0):
            self.unit_price = _decimal_safe(inv.unit_price)
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
        if (
            is_new
            and (self.description or '') != LEGACY_WASTE_REMARK
            and not WasteLog.objects.filter(inventory_id=inv.pk).exists()
        ):
            legacy_waste = _decimal_safe(inv.waste)
            if legacy_waste > 0:
                WasteLog.objects.create(
                    inventory=inv,
                    quantity=legacy_waste,
                    quantity_input=str(legacy_waste),
                    unit_price=_decimal_safe(inv.unit_price),
                    reason='other',
                    description=LEGACY_WASTE_REMARK,
                    waste_date=inv.updated_at.date() if inv.updated_at else timezone.now().date(),
                    created_by=self.created_by or inv.created_by,
                    company_id=inv.company_id,
                    account_id=inv.account_id,
                )
        other_total = (
            WasteLog.objects.filter(inventory_id=inv.pk)
            .exclude(pk=self.pk)
            .aggregate(total=models.Sum('quantity'))['total']
            or Decimal('0')
        )
        new_total_waste = other_total + self.quantity
        # Waste cannot consume stock that has already been taken out.
        max_waste = _decimal_safe(inv.quantity_in) - _decimal_safe(inv.quantity_out)
        if new_total_waste > max_waste:
            available = max_waste - other_total
            raise ValueError(over_waste_message(self.quantity, available, inv.quantity_in))
        super().save(*args, **kwargs)
        self._sync_inventory_waste()

    def delete(self, *args, **kwargs):
        inventory = self.inventory
        pk = inventory.pk
        super().delete(*args, **kwargs)
        from apps.inventory.ledger_sync import sync_inventory_from_ledgers
        sync_inventory_from_ledgers(pk, skip_repair=True)

    def _sync_inventory_waste(self):
        from apps.inventory.ledger_sync import sync_inventory_from_ledgers
        sync_inventory_from_ledgers(self.inventory_id, skip_repair=True)

    @staticmethod
    def _repair_legacy_waste(inventory):
        """Create opening waste log when header/movements show waste but no logs yet."""
        if WasteLog.objects.filter(inventory=inventory).exists():
            return
        stored = _decimal_safe(inventory.waste)
        max_snap = _decimal_safe(
            inventory.movements.aggregate(m=models.Max('waste'))['m']
        )
        candidate = max(stored, max_snap)
        if candidate <= 0:
            return
        WasteLog.objects.create(
            inventory=inventory,
            quantity=candidate,
            quantity_input=str(candidate),
            unit_price=_decimal_safe(inventory.unit_price),
            reason='other',
            description=LEGACY_WASTE_REMARK,
            waste_date=inventory.updated_at.date() if inventory.updated_at else timezone.now().date(),
            created_by=inventory.created_by,
            company_id=inventory.company_id,
            account_id=inventory.account_id,
        )

    @staticmethod
    def _sync_inventory_waste_from_db(inventory, *, skip_repair=False):
        """Recalculate waste from logs and refresh net qty / balance via full save."""
        inventory = Inventory.objects.get(pk=inventory.pk)
        if not skip_repair:
            WasteLog._repair_legacy_waste(inventory)
            inventory = Inventory.objects.get(pk=inventory.pk)
        if not WasteLog.objects.filter(inventory=inventory).exists():
            inventory.waste = Decimal('0')
            inventory.save()
            return
        total_waste = (
            WasteLog.objects.filter(inventory=inventory)
            .aggregate(total=models.Sum('quantity'))['total']
            or Decimal('0')
        )
        inventory.waste = total_waste
        inventory.save()


LEGACY_ISSUE_REMARK = 'LEGACY_QTY_OUT_IMPORT'
LEGACY_RECEIPT_REMARK = 'LEGACY_QTY_IN_IMPORT'
LEGACY_WASTE_REMARK = 'LEGACY_WASTE_IMPORT'


class InventoryIssue(models.Model):
    """
    Individual stock withdrawal (quantity out) for an inventory row.
    Store keepers record each issue separately; quantity_out on Inventory is
    the sum of all issues so they never manually add 5 + 17.
    """
    inventory = models.ForeignKey(
        Inventory,
        on_delete=models.CASCADE,
        related_name='issues',
        help_text='Inventory row this withdrawal belongs to.',
    )
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='inventory_issues',
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='inventory_issues',
        null=True,
        blank=True,
    )
    quantity = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text='Quantity issued in this withdrawal only.',
    )
    quantity_input = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='Original user input (e.g. "5 Rolls").',
    )
    unit_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        help_text='Unit price when this withdrawal was recorded.',
    )
    line_value = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal('0'),
        help_text='Value of this line = quantity × unit_price at recording time.',
    )
    recipient_name = models.CharField(
        max_length=255,
        blank=True,
        help_text='Customer or client who received this stock.',
    )
    issued_at = models.DateTimeField(
        default=timezone.now,
        help_text='Date and time when stock was given out.',
    )
    remark = models.TextField(blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventory_issues_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = models.Manager()
    visible_objects = TenantOwnedManager()

    class Meta:
        ordering = ['-issued_at', '-pk']
        verbose_name = 'Inventory Issue'
        verbose_name_plural = 'Inventory Issues'
        indexes = [
            models.Index(fields=['inventory', '-issued_at'], name='inventory_i_invento_c4e150_idx'),
            models.Index(fields=['company', '-issued_at'], name='inventory_i_company_d425e8_idx'),
            models.Index(fields=['recipient_name'], name='inventory_i_recipie_1d99ae_idx'),
        ]

    def __str__(self):
        who = self.recipient_name or '—'
        return f"Issue {self.quantity} to {who} ({self.issued_at})"

    def save(self, *args, **kwargs):
        if self.quantity_input:
            self.quantity_input = normalize_quantity_input(self.quantity_input)
            self.quantity = _decimal_safe(extract_numeric_value(self.quantity_input))
        elif self.quantity:
            self.quantity = _decimal_safe(self.quantity)
        if self.quantity <= 0:
            raise ValueError('Issue quantity must be greater than zero.')
        if self.created_by_id and not self.company_id:
            from apps.core.utils import get_company_profile_for_user
            company = get_company_profile_for_user(self.created_by)
            if company:
                self.company_id = company.pk
            from apps.core.ownership import get_account_for_user
            acc = get_account_for_user(self.created_by)
            if acc:
                self.account_id = acc.id
        if not self.inventory_id:
            raise ValueError('Inventory is required.')
        inv = Inventory.objects.filter(pk=self.inventory_id).first() or self.inventory
        self.inventory = inv
        is_new = self.pk is None
        if is_new and (not self.unit_price or self.unit_price == 0):
            self.unit_price = _decimal_safe(inv.unit_price)
        self.line_value = _decimal_safe(self.quantity) * _decimal_safe(self.unit_price)
        # If the row already had a manual/cumulative Quantity Out before Issue tracking,
        # preserve it as a one-off "Earlier withdrawals" line the first time issues are used.
        # Skip this when saving the legacy line itself.
        with transaction.atomic():
            if (
                is_new
                and (self.remark or '') != LEGACY_ISSUE_REMARK
                and not InventoryIssue.objects.filter(inventory_id=inv.pk).exists()
            ):
                legacy_out = _decimal_safe(inv.quantity_out)
                if legacy_out > 0:
                    max_out = _decimal_safe(inv.quantity_in) - _decimal_safe(inv.waste)
                    available_after_legacy = max_out - legacy_out
                    if self.quantity > available_after_legacy:
                        raise ValueError(
                            over_issue_message(
                                self.quantity,
                                available_after_legacy,
                                inv.quantity_in,
                                inv.waste,
                            )
                        )
                    InventoryIssue.objects.create(
                        inventory=inv,
                        quantity=legacy_out,
                        quantity_input=inv.quantity_out_input or str(legacy_out),
                        recipient_name='(Earlier withdrawals)',
                        remark=LEGACY_ISSUE_REMARK,
                        issued_at=inv.updated_at or inv.created_at or timezone.now(),
                        created_by=self.created_by or inv.created_by,
                        company_id=inv.company_id,
                        account_id=inv.account_id,
                    )
            other_total = (
                InventoryIssue.objects.filter(inventory_id=inv.pk)
                .exclude(pk=self.pk)
                .aggregate(total=models.Sum('quantity'))['total']
                or Decimal('0')
            )
            new_total_out = other_total + self.quantity
            max_out = _decimal_safe(inv.quantity_in) - _decimal_safe(inv.waste)
            is_legacy_create = is_new and (self.remark or '') == LEGACY_ISSUE_REMARK
            if not is_legacy_create and new_total_out > max_out:
                prev_qty = Decimal('0')
                if self.pk:
                    prev_qty = _decimal_safe(
                        InventoryIssue.objects.filter(pk=self.pk).values_list('quantity', flat=True).first()
                    )
                if is_new or self.quantity > prev_qty:
                    available = max_out - other_total
                    raise ValueError(
                        over_issue_message(self.quantity, available, inv.quantity_in, inv.waste)
                    )
            super().save(*args, **kwargs)
            self._sync_inventory_quantity_out()

    def delete(self, *args, **kwargs):
        inventory = self.inventory
        pk = inventory.pk
        super().delete(*args, **kwargs)
        from apps.inventory.ledger_sync import sync_inventory_from_ledgers
        sync_inventory_from_ledgers(pk, skip_repair=True)

    def _sync_inventory_quantity_out(self):
        from apps.inventory.ledger_sync import sync_inventory_from_ledgers
        sync_inventory_from_ledgers(self.inventory_id, skip_repair=True)

    @staticmethod
    def _repair_legacy_from_movements(inventory):
        """Recover quantity that was in Quantity Out before issue tracking."""
        if InventoryIssue.objects.filter(
            inventory=inventory, remark=LEGACY_ISSUE_REMARK
        ).exists():
            return
        stored_out = _decimal_safe(inventory.quantity_out)
        if stored_out <= 0:
            return
        non_legacy_sum = (
            InventoryIssue.objects.filter(inventory=inventory)
            .exclude(remark=LEGACY_ISSUE_REMARK)
            .aggregate(total=models.Sum('quantity'))['total']
            or Decimal('0')
        )
        max_snap = (
            inventory.movements.aggregate(m=models.Max('quantity_out'))['m']
            or Decimal('0')
        )
        max_snap = _decimal_safe(max_snap)
        if max_snap > non_legacy_sum:
            try:
                InventoryIssue.objects.create(
                    inventory=inventory,
                    quantity=max_snap,
                    quantity_input=inventory.quantity_out_input or str(max_snap),
                    recipient_name='(Earlier withdrawals)',
                    remark=LEGACY_ISSUE_REMARK,
                    issued_at=inventory.updated_at or inventory.created_at or timezone.now(),
                    created_by=inventory.created_by,
                    company_id=inventory.company_id,
                    account_id=inventory.account_id,
                )
            except ValueError:
                return

    @staticmethod
    def _sync_inventory_quantity_out_from_db(inventory, *, skip_repair=False):
        inventory = Inventory.objects.get(pk=inventory.pk)
        if not skip_repair:
            InventoryIssue._repair_legacy_from_movements(inventory)
            inventory = Inventory.objects.get(pk=inventory.pk)
        if not InventoryIssue.objects.filter(inventory=inventory).exists():
            inventory.quantity_out = Decimal('0')
            inventory.quantity_out_input = ''
            inventory.save()
            return
        total_out = (
            InventoryIssue.objects.filter(inventory=inventory)
            .aggregate(total=models.Sum('quantity'))['total']
            or Decimal('0')
        )
        samples = list(
            InventoryIssue.objects.filter(inventory=inventory).values_list('quantity_input', flat=True)
        )
        inventory.quantity_out = total_out
        inventory.quantity_out_input = compose_total_quantity_input(total_out, samples)
        inventory.save()


class InventoryReceipt(models.Model):
    """
    Individual stock receipt (quantity in) for an inventory row.
    Store keepers record each delivery separately; quantity_in is the sum of receipts.
    """
    inventory = models.ForeignKey(
        Inventory,
        on_delete=models.CASCADE,
        related_name='receipts',
        help_text='Inventory row this receipt belongs to.',
    )
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='inventory_receipts',
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        'core.CompanyProfile',
        on_delete=models.CASCADE,
        related_name='inventory_receipts',
        null=True,
        blank=True,
    )
    quantity = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text='Quantity received in this delivery only.',
    )
    quantity_input = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='Original user input (e.g. "10 Rolls").',
    )
    unit_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0'),
        help_text='Unit price when this receipt was recorded.',
    )
    line_value = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal('0'),
        help_text='Value of this line = quantity × unit_price at recording time.',
    )
    supplier_name = models.CharField(
        max_length=255,
        blank=True,
        help_text='Supplier or source of this stock.',
    )
    received_at = models.DateTimeField(
        default=timezone.now,
        help_text='Date and time when stock was received.',
    )
    remark = models.TextField(blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventory_receipts_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = models.Manager()
    visible_objects = TenantOwnedManager()

    class Meta:
        ordering = ['-received_at', '-pk']
        verbose_name = 'Inventory Receipt'
        verbose_name_plural = 'Inventory Receipts'
        indexes = [
            models.Index(fields=['inventory', '-received_at'], name='inventory_i_invento_be8b04_idx'),
            models.Index(fields=['company', '-received_at'], name='inventory_i_company_984a57_idx'),
            models.Index(fields=['supplier_name'], name='inventory_i_supplie_57fce7_idx'),
        ]

    def __str__(self):
        who = self.supplier_name or '—'
        return f"Receipt {self.quantity} from {who} ({self.received_at})"

    def save(self, *args, **kwargs):
        if self.quantity_input:
            self.quantity_input = normalize_quantity_input(self.quantity_input)
            self.quantity = _decimal_safe(extract_numeric_value(self.quantity_input))
        elif self.quantity:
            self.quantity = _decimal_safe(self.quantity)
        if self.quantity <= 0:
            raise ValueError('Receipt quantity must be greater than zero.')
        if self.created_by_id and not self.company_id:
            from apps.core.utils import get_company_profile_for_user
            company = get_company_profile_for_user(self.created_by)
            if company:
                self.company_id = company.pk
            from apps.core.ownership import get_account_for_user
            acc = get_account_for_user(self.created_by)
            if acc:
                self.account_id = acc.id
        if not self.inventory_id:
            raise ValueError('Inventory is required.')
        inv = self.inventory
        is_new = self.pk is None
        if is_new and (not self.unit_price or self.unit_price == 0):
            self.unit_price = _decimal_safe(inv.unit_price)
        self.line_value = _decimal_safe(self.quantity) * _decimal_safe(self.unit_price)
        other_in = (
            InventoryReceipt.objects.filter(inventory_id=inv.pk)
            .exclude(pk=self.pk)
            .aggregate(total=models.Sum('quantity'))['total']
            or Decimal('0')
        )
        new_total_in = other_in + self.quantity
        committed = _decimal_safe(inv.quantity_out) + _decimal_safe(inv.waste)
        if not is_new and new_total_in < committed:
            prev_qty = _decimal_safe(
                InventoryReceipt.objects.filter(pk=self.pk).values_list('quantity', flat=True).first()
            )
            if self.quantity < prev_qty:
                raise ValueError(
                    f'Cannot reduce this receipt to {format_quantity_number(self.quantity)}: '
                    f'quantity out plus waste is already {format_quantity_number(committed)}. '
                    f'Add stock or reduce withdrawals first.'
                )
        if (
            is_new
            and (self.remark or '') != LEGACY_RECEIPT_REMARK
            and not InventoryReceipt.objects.filter(inventory_id=inv.pk).exists()
        ):
            legacy_in = _decimal_safe(inv.quantity_in)
            if legacy_in > 0:
                InventoryReceipt.objects.create(
                    inventory=inv,
                    quantity=legacy_in,
                    quantity_input=inv.quantity_in_input or str(legacy_in),
                    supplier_name='(Earlier stock in)',
                    remark=LEGACY_RECEIPT_REMARK,
                    received_at=inv.updated_at or inv.created_at or timezone.now(),
                    created_by=self.created_by or inv.created_by,
                    company_id=inv.company_id,
                    account_id=inv.account_id,
                )
        super().save(*args, **kwargs)
        self._sync_inventory_quantity_in()

    def delete(self, *args, **kwargs):
        inventory = self.inventory
        pk = inventory.pk
        super().delete(*args, **kwargs)
        from apps.inventory.ledger_sync import sync_inventory_from_ledgers
        sync_inventory_from_ledgers(pk, skip_repair=True)

    def _sync_inventory_quantity_in(self):
        from apps.inventory.ledger_sync import sync_inventory_from_ledgers
        sync_inventory_from_ledgers(self.inventory_id, skip_repair=True)

    @staticmethod
    def _repair_legacy_receipts(inventory):
        """
        Create opening receipt when stock was received (or must have been, given
        withdrawals) but no receipt log lines exist yet.
        """
        if InventoryReceipt.objects.filter(inventory=inventory).exists():
            return
        stored_in = _decimal_safe(inventory.quantity_in)
        if stored_in <= 0:
            return
        max_snap = _decimal_safe(
            inventory.movements.aggregate(m=models.Max('quantity_in'))['m']
        )
        total_out = _decimal_safe(
            InventoryIssue.objects.filter(inventory=inventory)
            .aggregate(total=models.Sum('quantity'))['total']
        )
        if total_out <= 0:
            total_out = _decimal_safe(inventory.quantity_out)
        total_waste = _decimal_safe(
            WasteLog.objects.filter(inventory=inventory)
            .aggregate(total=models.Sum('quantity'))['total']
        )
        if total_waste <= 0:
            total_waste = _decimal_safe(inventory.waste)
        min_required = total_out + total_waste
        candidate = max(stored_in, max_snap, min_required)
        if candidate <= 0:
            return
        unit = inventory.unit_label
        if unit:
            qty_input = f'{candidate.normalize()} {unit}'.replace('E', '')
            if '.' in qty_input:
                qty_input = qty_input.rstrip('0').rstrip('.')
        else:
            qty_input = str(candidate)
        InventoryReceipt.objects.create(
            inventory=inventory,
            quantity=candidate,
            quantity_input=qty_input,
            supplier_name='(Earlier stock in)',
            remark=LEGACY_RECEIPT_REMARK,
            received_at=inventory.updated_at or inventory.created_at or timezone.now(),
            created_by=inventory.created_by,
            company_id=inventory.company_id,
            account_id=inventory.account_id,
        )

    @staticmethod
    def _sync_inventory_quantity_in_from_db(inventory, *, skip_repair=False):
        inventory = Inventory.objects.get(pk=inventory.pk)
        if not skip_repair:
            InventoryReceipt._repair_legacy_receipts(inventory)
            inventory = Inventory.objects.get(pk=inventory.pk)
        if not InventoryReceipt.objects.filter(inventory=inventory).exists():
            inventory.quantity_in = Decimal('0')
            inventory.quantity_in_input = ''
            inventory.save()
            return
        total_in = (
            InventoryReceipt.objects.filter(inventory=inventory)
            .aggregate(total=models.Sum('quantity'))['total']
            or Decimal('0')
        )
        samples = list(
            InventoryReceipt.objects.filter(inventory=inventory).values_list('quantity_input', flat=True)
        )
        inventory.quantity_in = total_in
        inventory.quantity_in_input = compose_total_quantity_input(total_in, samples)
        inventory.save()


