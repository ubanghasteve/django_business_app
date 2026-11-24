# -*- coding: utf-8 -*-
from django.db import models, IntegrityError
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re


def safe_decimal_for_db(value, decimal_places=2):
    """Return a Decimal safe for DB storage: not NaN/Infinity, quantized to decimal_places."""
    if value is None:
        return Decimal('0')
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal('0')
    if d.is_nan() or d.is_infinite():
        return Decimal('0')
    quantizer = Decimal('0.01') if decimal_places == 2 else Decimal(10) ** -decimal_places
    try:
        return d.quantize(quantizer, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return Decimal('0')

from apps.core.ownership import TenantOwnedManager, get_account_for_user
from apps.core.sync_mixin import SyncMixin

User = get_user_model()


class InvoiceTemplate(models.Model):
    """User-defined invoice templates with custom styling and colors"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='invoice_templates')
    name = models.CharField(max_length=200, default='Default Invoice', help_text="Template name (e.g., 'Professional Invoice', 'Service Invoice')")
    description = models.TextField(blank=True, help_text="Description of this template")
    
    # Color customization
    primary_color = models.CharField(max_length=7, default='#FF5900', help_text="Primary color (hex code)")
    secondary_color = models.CharField(max_length=7, default='#f8f9fa', help_text="Secondary color (hex code)")
    text_color = models.CharField(max_length=7, default='#333333', help_text="Text color (hex code)")
    accent_color = models.CharField(max_length=7, default='#e9ecef', help_text="Accent color for borders and highlights (hex code)")
    
    # Display options
    show_company_logo = models.BooleanField(default=True)
    show_company_details = models.BooleanField(default=True)
    show_bank_details = models.BooleanField(default=True)
    show_signature = models.BooleanField(default=True)
    
    # Document settings
    document_title = models.CharField(max_length=100, default='INVOICE', help_text="Document title to display")
    number_prefix = models.CharField(max_length=10, default='INV', help_text="Invoice number prefix")
    
    # Payment terms and notes
    default_payment_terms = models.TextField(blank=True, default='Payment due within 30 days', help_text="Default payment terms for new invoices")
    footer_text = models.TextField(blank=True, help_text="Footer text to display on invoices")
    
    is_default = models.BooleanField(default=False, help_text="Use as default template")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        unique_together = ['user', 'name']
    
    def __str__(self):
        return f"{self.name} - {self.user.get_full_name()}"
    
    def save(self, *args, **kwargs):
        # Ensure only one default template per user
        if self.is_default:
            InvoiceTemplate.objects.filter(user=self.user, is_default=True).update(is_default=False)
        super().save(*args, **kwargs)


class Invoice(SyncMixin, models.Model):
    STATUS_CHOICES = [
        ('unpaid', 'Unpaid'),
        ('partial', 'Partially Paid'),
        ('paid', 'Paid'),
        ('delivered', 'Delivered'),
    ]
    
    DISCOUNT_TYPE_CHOICES = [
        ('percentage', 'Percentage (%)'),
        ('fixed', 'Fixed Amount (₦)'),
    ]
    
    TAX_TYPE_CHOICES = [
        ('percentage', 'Percentage (%)'),
        ('fixed', 'Fixed Amount (₦)'),
    ]
    
    invoice_number = models.CharField(max_length=50, unique=True, editable=False)
    invoice_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='invoices')
    template = models.ForeignKey(InvoiceTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices')
    # Tenant and creator for per-team-member isolation (backfilled from user in migration)
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='invoices',
        null=True,
        blank=True,
        help_text='Tenant account; set from user.account on save if missing.',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoices_created',
        help_text='User who created this invoice; set from user on save if missing.',
    )
    # Client Information
    client_name = models.CharField(max_length=200)
    client_phone = models.CharField(max_length=20, blank=True)
    client_email = models.EmailField(blank=True)
    client_address = models.TextField(blank=True)
    
    # Financial Fields
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0, blank=True)
    total_tax = models.DecimalField(max_digits=12, decimal_places=2, default=0, blank=True)
    tax_type = models.CharField(max_length=15, choices=TAX_TYPE_CHOICES, default='percentage', help_text="Tax calculation type")
    tax_value = models.DecimalField(max_digits=10, decimal_places=2, default=0, blank=True, help_text="Tax rate (%) or fixed amount")
    total_discount = models.DecimalField(max_digits=12, decimal_places=2, default=0, blank=True)
    discount_type = models.CharField(max_length=15, choices=DISCOUNT_TYPE_CHOICES, default='percentage', help_text="Discount calculation type")
    discount_value = models.DecimalField(max_digits=10, decimal_places=2, default=0, blank=True, help_text="Discount rate (%) or fixed amount")
    shipping_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0, blank=True)
    other_charges = models.DecimalField(max_digits=12, decimal_places=2, default=0, blank=True)
    grand_total = models.DecimalField(max_digits=12, decimal_places=2, default=0, blank=True)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0, blank=True)
    balance_due = models.DecimalField(max_digits=12, decimal_places=2, default=0, blank=True)
    # How metrics use this invoice:
    # - Unpaid (amount_paid=0): status='unpaid'; revenue = 0; outstanding = grand_total.
    # - Part payment (0 < amount_paid < grand_total): status='partial'; revenue = amount_paid only; outstanding = grand_total - amount_paid.
    # - Paid (amount_paid >= grand_total): status='paid'; revenue = grand_total (capped); outstanding = 0. Overpayment goes to refund_due.
    status = models.CharField(
        max_length=15,
        choices=STATUS_CHOICES,
        default='unpaid',
        help_text='Derived from amount_paid vs grand_total in calculate_totals(). To change, use set_payment_status() or set amount_paid and save().'
    )
    notes = models.TextField(blank=True)
    
    # Per-invoice display settings (overrides company profile defaults)
    show_bank_details = models.BooleanField(default=True, help_text="Show bank details on this invoice")
    show_signature = models.BooleanField(default=True, help_text="Show signature on this invoice")
    
    created_at = models.DateTimeField(auto_now_add=True)
    # updated_at from SyncMixin (for conflict resolution)

    # Per-team-member visibility: use visible_objects.for_user(user, request) or core.ownership.for_user_queryset
    objects = models.Manager()  # Default manager for admin and internal operations
    visible_objects = TenantOwnedManager()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['account', '-created_at']),
            models.Index(fields=['invoice_number']),
            models.Index(fields=['status']),
            models.Index(fields=['invoice_date']),
            models.Index(fields=['due_date']),
        ]
        # Custom action-level permissions so viewing, printing, approving,
        # and downloading invoices can be controlled independently.
        permissions = [
            ("print_invoice", "Can print invoice"),
            ("download_invoice", "Can download or export invoice data"),
            ("can_approve_invoice", "Can approve invoices"),
        ]
        
    def __str__(self):
        return f"Invoice {self.invoice_number}"
    
    def save(self, *args, **kwargs):
        # Per-team-member isolation: set tenant and creator from user when missing
        if self.user_id and (not self.account_id or not self.created_by_id):
            if not self.account_id:
                if getattr(self.user, 'account_id', None):
                    self.account_id = self.user.account_id
                else:
                    acc = get_account_for_user(self.user)
                    if acc:
                        self.account_id = acc.id
            if not self.created_by_id:
                self.created_by_id = self.user_id
        if not self.invoice_number:
            self.invoice_number = self.generate_invoice_number()
        
        # Handle potential duplicate invoice numbers with retry mechanism
        max_retries = 3
        for retry in range(max_retries):
            try:
                # Only calculate totals if the invoice already exists (has a primary key)
                # This prevents errors when creating new invoices
                if self.pk:
                    self.calculate_totals()
                
                super().save(*args, **kwargs)
                break  # Success, exit retry loop
                
            except IntegrityError as e:
                if retry < max_retries - 1 and 'invoice_number' in str(e):
                    self.invoice_number = self.generate_invoice_number()
                    continue
                raise
    
    def generate_invoice_number(self):
        """Generate unique invoice number with collision handling"""
        from datetime import datetime
        import random
        year = datetime.now().year
        
        # Try multiple attempts to generate a unique number
        for attempt in range(10):
            if attempt == 0:
                # First try: use count-based approach
                count = Invoice.objects.filter(
                    user=self.user,
                    created_at__year=year
                ).count() + 1
                invoice_number = f"INV-{year}-{count:04d}"
            else:
                # Subsequent tries: add random component to avoid collisions
                count = Invoice.objects.filter(
                    user=self.user,
                    created_at__year=year
                ).count() + 1
                random_suffix = random.randint(1000, 9999)
                invoice_number = f"INV-{year}-{count:04d}-{random_suffix}"
            
            # Check if this number already exists
            if not Invoice.objects.filter(invoice_number=invoice_number).exists():
                return invoice_number
        
        # Final fallback: timestamp + random, ensure unique
        import time
        for _ in range(5):
            timestamp = int(time.time() * 1000) % 100000
            suffix = random.randint(1000, 9999)
            invoice_number = f"INV-{year}-{timestamp}-{suffix}"
            if not Invoice.objects.filter(invoice_number=invoice_number).exists():
                return invoice_number
        # Last resort: full timestamp (very unlikely to collide)
        return f"INV-{year}-{int(time.time() * 1000)}"
    
    def calculate_totals(self):
        """Calculate all totals with flexible discount and tax types"""
        self.subtotal = safe_decimal_for_db(
            sum((item.line_total or Decimal('0')) for item in self.items.all()),
            2,
        )
        
        # Handle tax calculation based on type
        if hasattr(self, '_tax_rate') and self._tax_rate:
            # Legacy support for percentage-based tax via _tax_rate attribute
            self.total_tax = self.subtotal * (self._tax_rate / 100)
            self.tax_type = 'percentage'
            self.tax_value = self._tax_rate
        elif self.tax_value:
            # Use stored tax_value with type
            if self.tax_type == 'percentage':
                self.total_tax = self.subtotal * (self.tax_value / 100)
            else:  # fixed
                self.total_tax = self.tax_value
        
        # Handle discount calculation based on type
        if hasattr(self, '_discount_rate') and self._discount_rate:
            # Legacy support for percentage-based discount via _discount_rate attribute
            self.total_discount = self.subtotal * (self._discount_rate / 100)
            self.discount_type = 'percentage'
            self.discount_value = self._discount_rate
        elif hasattr(self, '_discount_fixed') and self._discount_fixed:
            # Fixed amount discount via attribute
            self.total_discount = self._discount_fixed
            self.discount_type = 'fixed'
            self.discount_value = self._discount_fixed
        elif self.discount_value:
            # Use stored discount_value with type
            if self.discount_type == 'percentage':
                self.total_discount = self.subtotal * (self.discount_value / 100)
            else:  # fixed
                self.total_discount = self.discount_value
        
        self.total_tax = safe_decimal_for_db(self.total_tax, 2)
        self.total_discount = safe_decimal_for_db(self.total_discount, 2)
        self.grand_total = safe_decimal_for_db(
            (self.subtotal or Decimal('0'))
            + (self.total_tax or Decimal('0'))
            + (self.shipping_fee or Decimal('0'))
            + (self.other_charges or Decimal('0'))
            - (self.total_discount or Decimal('0')),
            2,
        )
        self.balance_due = safe_decimal_for_db(
            self.grand_total - (self.amount_paid or Decimal('0')),
            2,
        )

        # Status: derive from amount_paid vs a positive amount due.
        # A negative other_charges (or discount) can make grand_total <= 0;
        # that is not a payment, so do not mark the invoice paid.
        amount_paid = self.amount_paid or Decimal('0')
        if amount_paid == 0 or self.grand_total <= 0:
            self.status = 'unpaid'
        elif amount_paid >= self.grand_total:
            if self.status == 'delivered':
                pass
            else:
                self.status = 'paid'
        else:
            self.status = 'partial'

    def set_payment_status(self, status):
        """
        Set payment state by updating amount_paid (and status for 'delivered').
        Status is derived on save() via calculate_totals(): unpaid/partial/paid from amount_paid;
        'delivered' is preserved only when amount_paid >= grand_total (so setting to unpaid/partial overwrites delivered).
        - 'paid': set amount_paid to at least grand_total (preserves overpayment)
        - 'unpaid': set amount_paid to 0
        - 'partial': set amount_paid so status becomes partial (e.g. half of grand_total if currently 0 or full)
        - 'delivered': set status to 'delivered' (kept only if invoice is fully paid)
        """
        if status == 'paid':
            self.amount_paid = max(self.amount_paid, self.grand_total)
        elif status == 'unpaid':
            self.amount_paid = Decimal('0')
        elif status == 'partial':
            if self.amount_paid >= self.grand_total:
                self.amount_paid = Decimal('0')
            if self.amount_paid == 0 and self.grand_total and self.grand_total > 0:
                # Unpaid -> partial: set a partial amount so derived status is 'partial'
                self.amount_paid = (self.grand_total / 2).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        elif status == 'delivered':
            self.status = 'delivered'
        # else: leave amount_paid and status unchanged

    @property
    def balance_to_customer(self):
        """When customer overpays (amount_paid > grand_total), amount we owe back. Otherwise 0."""
        if self.amount_paid > self.grand_total:
            return self.amount_paid - self.grand_total
        return Decimal('0')

    @property
    def revenue_contribution(self):
        """Revenue from this invoice (capped at grand_total; overpayment does not inflate revenue)."""
        return min(self.amount_paid, self.grand_total)

    @staticmethod
    def _decimal_safe_result(d):
        """Return d or Decimal('0') if d is NaN/Infinite (so we never return invalid Decimals)."""
        if d is None:
            return Decimal('0')
        try:
            if d.is_nan() or d.is_infinite():
                return Decimal('0')
        except (AttributeError, InvalidOperation):
            return Decimal('0')
        return d

    @staticmethod
    def parse_number(value):
        """Parse smart number inputs like ₦3k, 7.5%, -500, '80 nires', '45n', 'N 20', 'na', 'N/A'."""
        if value is None:
            return Decimal('0')
        value = str(value).strip()
        if not value:
            return Decimal('0')
        # Treat na/n/a/N/A/nan/NaN/inf etc. as zero (allow decimals and "numbers na" combination)
        lower = value.lower()
        if lower in ('na', 'n/a', 'n.a.', 'nan', 'none', '-', '—', ''):
            return Decimal('0')
        if lower in ('inf', 'infinity', '-inf', '-infinity'):
            return Decimal('0')

        original_value = value
        # Remove currency symbols first
        value = re.sub(r'[₦$€£,]', '', value)
        value = value.strip()
        if not value:
            return Decimal('0')
        
        # Handle percentage
        if '%' in value:
            numbers = re.findall(r'-?\d+\.?\d*', value.replace('%', ''))
            if numbers:
                return Invoice._decimal_safe_result(Decimal(numbers[0]) / 100)
            return Decimal('0')

        # Handle 'k' suffix (thousands)
        if value.lower().endswith('k'):
            numbers = re.findall(r'-?\d+\.?\d*', value[:-1])
            if numbers:
                return Invoice._decimal_safe_result(Decimal(numbers[0]) * 1000)
            return Decimal('0')

        # Handle 'm' suffix (millions)
        if value.lower().endswith('m'):
            numbers = re.findall(r'-?\d+\.?\d*', value[:-1])
            if numbers:
                return Invoice._decimal_safe_result(Decimal(numbers[0]) * 1000000)
            return Decimal('0')

        # Extract numbers (handles "80 nires", "45n", "N 20")
        numbers = re.findall(r'-?\d+\.?\d*', value)
        if numbers:
            try:
                return Invoice._decimal_safe_result(Decimal(numbers[0]))
            except (InvalidOperation, ValueError, TypeError):
                return Decimal('0')

        # Fallback: parse whole string (e.g. "123.45"); never return NaN/Inf
        try:
            d = Decimal(value)
            return Invoice._decimal_safe_result(d)
        except (InvalidOperation, ValueError, TypeError):
            return Decimal('0')
    
    @staticmethod
    def parse_number_with_type(value):
        """
        Parse smart number inputs and detect the type (percentage or fixed).
        Returns: tuple (value: Decimal, type: str, raw_value: Decimal)
        - value: The calculated value (for percentage, this is the percentage as decimal, e.g., 10% = 0.1)
        - type: 'percentage' or 'fixed'
        - raw_value: The raw number entered (e.g., 10 for 10%, 5000 for ₦5000)
        """
        if value is None:
            return Decimal('0'), 'fixed', Decimal('0')
        value_str = str(value).strip()
        if not value_str:
            return Decimal('0'), 'fixed', Decimal('0')
        lower = value_str.lower()
        if lower in ('na', 'n/a', 'n.a.', 'nan', 'none', '-', '—'):
            return Decimal('0'), 'fixed', Decimal('0')
        if lower in ('inf', 'infinity', '-inf', '-infinity'):
            return Decimal('0'), 'fixed', Decimal('0')
        
        # Detect percentage
        if '%' in value_str:
            cleaned = re.sub(r'[₦$€£,%\s]', '', value_str)
            numbers = re.findall(r'-?\d+\.?\d*', cleaned)
            if numbers:
                raw_val = Invoice._decimal_safe_result(Decimal(numbers[0]))
                return Invoice._decimal_safe_result(raw_val / 100), 'percentage', raw_val
            return Decimal('0'), 'percentage', Decimal('0')

        # Otherwise it's a fixed amount
        cleaned = re.sub(r'[₦$€£,\s]', '', value_str)
        if not cleaned:
            return Decimal('0'), 'fixed', Decimal('0')

        if cleaned.lower().endswith('k'):
            numbers = re.findall(r'-?\d+\.?\d*', cleaned[:-1])
            if numbers:
                raw_val = Invoice._decimal_safe_result(Decimal(numbers[0]) * 1000)
                return raw_val, 'fixed', raw_val
            return Decimal('0'), 'fixed', Decimal('0')

        if cleaned.lower().endswith('m'):
            numbers = re.findall(r'-?\d+\.?\d*', cleaned[:-1])
            if numbers:
                raw_val = Invoice._decimal_safe_result(Decimal(numbers[0]) * 1000000)
                return raw_val, 'fixed', raw_val
            return Decimal('0'), 'fixed', Decimal('0')

        numbers = re.findall(r'-?\d+\.?\d*', cleaned)
        if numbers:
            try:
                raw_val = Invoice._decimal_safe_result(Decimal(numbers[0]))
                return raw_val, 'fixed', raw_val
            except (InvalidOperation, ValueError, TypeError):
                return Decimal('0'), 'fixed', Decimal('0')

        return Decimal('0'), 'fixed', Decimal('0')


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='items')
    product_service = models.CharField(max_length=250, blank=True)
    description = models.CharField(max_length=500, blank=True)
    # Allow both positive and negative values (e.g. for adjustments/credits),
    # so we intentionally do NOT enforce a minimum value here.
    quantity = models.DecimalField(max_digits=10, decimal_places=2, blank=True, default=0)
    # Stores the original text the user typed for quantity (e.g. "345 bags")
    quantity_display = models.CharField(max_length=100, blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    class Meta:
        ordering = ['id']
    
    def __str__(self):
        display_text = self.product_service or self.description or "Item"
        return f"{display_text} - {self.invoice.invoice_number}"
    
    def save(self, *args, **kwargs):
        # Coerce quantity and unit_price to valid decimals before any use or DB write
        # (handles "na", NaN, Infinity, and mixed decimal/text input)
        self.quantity = safe_decimal_for_db(self.quantity, 2)
        self.unit_price = safe_decimal_for_db(self.unit_price, 2)
        try:
            total = self.quantity * self.unit_price
            self.line_total = safe_decimal_for_db(total, 2)
        except (InvalidOperation, TypeError, ValueError):
            self.line_total = Decimal('0')
        super().save(*args, **kwargs)
        # Don't automatically recalculate here to avoid conflicts during bulk saves
        # Let the view handle the recalculation after all items are processed


# Ensure at runtime that quantity and unit_price NEVER enforce a minimum of 0.
# This is a final safeguard in case any MinValueValidator(0) validators are still
# attached via old migrations or cached model state.
from django.core.validators import MinValueValidator  # noqa: E402
for _field_name in ("quantity", "unit_price"):
    try:
        _field = InvoiceItem._meta.get_field(_field_name)
        _field.validators = [
            v for v in _field.validators
            if not isinstance(v, MinValueValidator)
        ]
    except Exception:
        # If anything goes wrong here we silently ignore it so the app still loads
        pass


class InvoiceMovement(models.Model):
    """
    Immutable ledger row capturing all changes to an invoice.
    Created automatically whenever an invoice record is modified.
    Each movement stores a SNAPSHOT of the invoice at that moment.
    """

    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="movements",
        help_text="Invoice this movement belongs to.",
    )

    client_name = models.CharField(
        max_length=200,
        blank=True,
        default='',
        help_text="Client name at time of movement.",
    )
    client_phone = models.CharField(
        max_length=20,
        blank=True,
        default='',
        help_text="Client phone at time of movement.",
    )
    client_email = models.EmailField(
        blank=True,
        default='',
        help_text="Client email at time of movement.",
    )
    client_address = models.TextField(
        blank=True,
        default='',
        help_text="Client address at time of movement.",
    )

    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        help_text="Subtotal at time of movement.",
    )
    total_tax = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        help_text="Total tax at time of movement.",
    )
    tax_type = models.CharField(
        max_length=15,
        choices=Invoice.TAX_TYPE_CHOICES,
        default='percentage',
    )
    tax_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0'),
    )
    total_discount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        help_text="Total discount at time of movement.",
    )
    discount_type = models.CharField(
        max_length=15,
        choices=Invoice.DISCOUNT_TYPE_CHOICES,
        default='percentage',
    )
    discount_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0'),
    )
    shipping_fee = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
    )
    other_charges = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
    )
    grand_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        help_text="Grand total at time of movement.",
    )
    amount_paid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        help_text="Amount paid at time of movement.",
    )
    balance_due = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0'),
        help_text="Balance due at time of movement.",
    )
    status = models.CharField(
        max_length=15,
        choices=Invoice.STATUS_CHOICES,
        default='unpaid',
        help_text="Status at time of movement.",
    )
    notes = models.TextField(
        blank=True,
        default='',
        help_text="Notes at time of movement.",
    )
    show_bank_details = models.BooleanField(
        default=True,
        help_text="Show bank details at time of movement.",
    )
    show_signature = models.BooleanField(
        default=True,
        help_text="Show signature at time of movement.",
    )
    items_snapshot = models.JSONField(
        default=list,
        help_text="Snapshot of invoice items at time of movement.",
    )

    created_by_id = models.IntegerField(
        null=True,
        blank=True,
        help_text="ID of the user who created this movement.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Invoice Movement"
        verbose_name_plural = "Invoice Movements"
        default_permissions = ()
        indexes = [
            models.Index(fields=["invoice", "-created_at"]),
        ]

    def __str__(self):
        return f"Movement for {self.invoice_id} at {self.created_at}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise IntegrityError("InvoiceMovement records are immutable and cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise IntegrityError("InvoiceMovement records are immutable and cannot be deleted.")