from django.db import models, IntegrityError
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator
from decimal import Decimal
from apps.core.models import CompanyProfile
from apps.clients.models import Client
from apps.core.ownership import TenantOwnedManager
import re
import uuid

User = get_user_model()


class QuotationTemplate(models.Model):
    """User-defined quotation templates with custom styling and colors"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='quotation_templates')
    name = models.CharField(max_length=200, default='Default Quotation', help_text="Template name (e.g., 'Professional Quotation', 'Service Quote')")
    description = models.TextField(blank=True, help_text="Description of this template")
    
    # Color customization
    primary_color = models.CharField(max_length=7, default='#1976d2', help_text="Primary color (hex code)")
    secondary_color = models.CharField(max_length=7, default='#f8f9fa', help_text="Secondary color (hex code)")
    text_color = models.CharField(max_length=7, default='#333333', help_text="Text color (hex code)")
    accent_color = models.CharField(max_length=7, default='#e9ecef', help_text="Accent color for borders and highlights (hex code)")
    
    # Display options
    show_company_logo = models.BooleanField(default=True)
    show_company_details = models.BooleanField(default=True)
    show_bank_details = models.BooleanField(default=True)
    show_signature = models.BooleanField(default=True)
    
    # Document settings
    document_title = models.CharField(max_length=100, default='QUOTATION', help_text="Document title to display")
    number_prefix = models.CharField(max_length=10, default='QT', help_text="Quotation number prefix")
    
    # Terms and notes
    default_terms = models.TextField(blank=True, default='This quotation is valid for 30 days from the date of issue', help_text="Default terms for new quotations")
    footer_text = models.TextField(blank=True, help_text="Footer text to display on quotations")
    
    is_default = models.BooleanField(default=False, help_text="Use as default template")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        unique_together = ['user', 'name']
    
    def __str__(self):
        try:
            if self.user and self.user.is_authenticated:
                return f"{self.name} - {self.user.get_full_name()}"
        except:
            pass
        return f"{self.name} - Anonymous"
    
    def save(self, *args, **kwargs):
        # Ensure only one default template per user (or globally if no user)
        if self.is_default:
            try:
                if self.user and self.user.is_authenticated:
                    QuotationTemplate.objects.filter(user=self.user, is_default=True).update(is_default=False)
            except:
                # User field not set yet, will be set after super().save()
                pass
        super().save(*args, **kwargs)


class Quotation(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('accepted', 'Accepted'),
        ('declined', 'Declined'),
        ('expired', 'Expired'),
    ]
    
    DISCOUNT_TYPE_CHOICES = [
        ('percentage', 'Percentage (%)'),
        ('fixed', 'Fixed Amount (₦)'),
    ]
    
    TAX_TYPE_CHOICES = [
        ('percentage', 'Percentage (%)'),
        ('fixed', 'Fixed Amount (₦)'),
    ]
    
    quotation_number = models.CharField(max_length=50, editable=False)
    quotation_date = models.DateField(auto_now_add=True)
    valid_until = models.DateField(null=True, blank=True, help_text="Quotation validity period")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='quotations', null=True, blank=True)
    template = models.ForeignKey(QuotationTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name='quotations')
    # Tenant and creator for per-team-member isolation (backfilled from user in migration)
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='quotations',
        null=True,
        blank=True,
        help_text='Tenant account; set from user.account on save if missing.',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quotations_created',
        help_text='User who created this quotation; set from user on save if missing.',
    )
    # Client Information
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True, related_name='quotations')
    
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
    
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='draft')
    terms = models.TextField(blank=True, help_text="Terms and conditions")
    notes = models.TextField(blank=True, help_text="Additional notes")
    
    # Professional conversion tracking
    converted_invoice = models.ForeignKey('invoices.Invoice', on_delete=models.SET_NULL, null=True, blank=True, related_name='source_quotation')
    conversion_date = models.DateTimeField(null=True, blank=True, help_text="Date when quotation was converted to invoice")
    
    # Custom fields for flexibility
    custom_fields = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    is_deleted = models.BooleanField(default=False)

    objects = models.Manager()  # Default manager for admin and internal operations
    visible_objects = TenantOwnedManager()

    class Meta:
        ordering = ['-created_at']
        unique_together = [['user', 'quotation_number']]
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['account', '-created_at']),
            models.Index(fields=['quotation_number']),
            models.Index(fields=['status']),
            models.Index(fields=['quotation_date']),
            models.Index(fields=['valid_until']),
            models.Index(fields=['client']),
        ]
        # Custom action-level permissions so viewing, printing, approving,
        # and downloading quotations can be controlled independently.
        permissions = [
            ("print_quotation", "Can print quotation"),
            ("download_quotation", "Can download or export quotation data"),
            ("can_approve_quotation", "Can approve quotations"),
        ]
    
    def __str__(self):
        client_name = self.client.name if self.client else "No Client"
        return f"Quotation {self.quotation_number} - {client_name}"
    
    def save(self, *args, **kwargs):
        # Per-team-member isolation: set tenant and creator from user when missing
        if self.user_id and (not self.account_id or not self.created_by_id):
            if not self.account_id and getattr(self.user, 'account_id', None):
                self.account_id = self.user.account_id
            if not self.created_by_id:
                self.created_by_id = self.user_id
        # Only generate quotation number for new quotations
        if not self.pk and not self.quotation_number:
            self.quotation_number = self.generate_quotation_number()

        # Set default values from company profile if not set
        if not self.pk:  # Only for new quotations
            try:
                if self.user and self.user.is_authenticated:
                    company_profile = self.user.company_profile
                    if company_profile:
                        if not self.total_tax:
                            self.total_tax = company_profile.default_tax
                        if not self.total_discount:
                            self.total_discount = company_profile.default_discount
                        if not self.shipping_fee:
                            self.shipping_fee = company_profile.default_shipping_fee
            except Exception:
                pass

        # Handle duplicate quotation_number (unique_together with user) with retry
        max_retries = 3
        for retry in range(max_retries):
            try:
                super().save(*args, **kwargs)
                self.calculate_totals()
                break
            except IntegrityError as e:
                if retry < max_retries - 1 and ('unique' in str(e).lower() or 'quotation_number' in str(e) or 'Duplicate' in str(e)):
                    self.quotation_number = self.generate_quotation_number()
                    continue
                raise
    
    def generate_quotation_number(self):
        """Generate unique quotation number based on user and sequence (unique per user)."""
        import random
        prefix = "QT"
        if self.template and self.template.number_prefix:
            prefix = self.template.number_prefix

        base_filter = Quotation.objects.filter(user=self.user) if (self.user and getattr(self.user, 'is_authenticated', True)) else Quotation.objects.all()
        prefix_filter = base_filter.filter(quotation_number__startswith=prefix)
        last_quotation = prefix_filter.order_by('-quotation_number').first()

        if last_quotation and last_quotation.quotation_number:
            try:
                number_part = last_quotation.quotation_number[len(prefix):].lstrip('-')
                next_number = int(number_part) + 1
            except (ValueError, IndexError):
                next_number = 1
        else:
            next_number = 1

        for attempt in range(15):
            if attempt > 0:
                next_number += 1
                if attempt >= 5:
                    next_number = (next_number + random.randint(1, 999)) % 999999 or 1
            quotation_number = f"{prefix}-{next_number:06d}"
            if not base_filter.filter(quotation_number=quotation_number).exists():
                return quotation_number

        # Fallback: prefix + timestamp
        from time import time
        return f"{prefix}-{int(time() * 1000) % 1000000:06d}"
    
    def calculate_totals(self):
        """Calculate all totals based on line items with flexible discount and tax types"""
        # Calculate subtotal from line items
        subtotal = sum(item.line_total for item in self.items.all())
        
        # Calculate tax based on type
        if self.tax_value:
            if self.tax_type == 'percentage':
                tax_amount = subtotal * (self.tax_value / 100)
            else:  # fixed
                tax_amount = self.tax_value
        else:
            tax_amount = self.total_tax
        
        # Calculate discount based on type
        if self.discount_value:
            if self.discount_type == 'percentage':
                discount_amount = subtotal * (self.discount_value / 100)
            else:  # fixed
                discount_amount = self.discount_value
        else:
            discount_amount = self.total_discount
        
        # Calculate grand total
        grand_total = (
            subtotal +
            tax_amount +
            self.shipping_fee +
            self.other_charges -
            discount_amount
        )
        
        # Update the instance fields
        self.subtotal = subtotal
        self.total_tax = tax_amount
        self.total_discount = discount_amount
        self.grand_total = grand_total
        
        # Use update to avoid recursion and ensure database is updated
        Quotation.objects.filter(pk=self.pk).update(
            subtotal=subtotal,
            total_tax=tax_amount,
            total_discount=discount_amount,
            grand_total=grand_total
        )
        
        # Refresh the instance from database to ensure consistency
        self.refresh_from_db()
    
    def calculate_tax_amount(self, subtotal):
        """Calculate the actual tax amount based on subtotal"""
        if not self.total_tax or subtotal == 0:
            return Decimal('0.00')
        
        # For percentage-based calculation, tax field now stores the calculated amount
        # This method is kept for backward compatibility but should not be used
        return self.total_tax
    
    def calculate_discount_amount(self, subtotal):
        """Calculate the actual discount amount based on subtotal"""
        if not self.total_discount or subtotal == 0:
            return Decimal('0.00')
        
        # For percentage-based calculation, discount field now stores the calculated amount
        # This method is kept for backward compatibility but should not be used
        return self.total_discount
    
    @staticmethod
    def parse_number(value):
        """Parse number from string, handling percentage and currency formats"""
        if not value:
            return Decimal('0.00')
        
        if isinstance(value, (int, float, Decimal)):
            return Decimal(str(value))
        
        # Convert to string and clean
        value_str = str(value).strip().replace(',', '')
        
        # Handle percentage
        if '%' in value_str:
            try:
                percentage = Decimal(value_str.replace('%', ''))
                return percentage / 100
            except:
                return Decimal('0.00')
        
        # Handle currency symbols
        value_str = re.sub(r'[^\d.-]', '', value_str)
        
        try:
            return Decimal(value_str)
        except:
            return Decimal('0.00')
    
    @staticmethod
    def parse_number_with_type(value):
        """
        Parse number inputs and detect the type (percentage or fixed).
        Returns: tuple (value: Decimal, type: str, raw_value: Decimal)
        - value: The calculated value (for percentage, this is the percentage as decimal)
        - type: 'percentage' or 'fixed'
        - raw_value: The raw number entered (e.g., 10 for 10%, 5000 for ₦5000)
        """
        if not value:
            return Decimal('0'), 'fixed', Decimal('0')
        
        if isinstance(value, (int, float, Decimal)):
            return Decimal(str(value)), 'fixed', Decimal(str(value))
        
        value_str = str(value).strip()
        
        # Detect percentage
        if '%' in value_str:
            # Remove % and currency symbols
            cleaned = re.sub(r'[₦$€£,%\s]', '', value_str)
            try:
                raw_val = Decimal(cleaned) if cleaned else Decimal('0')
                return raw_val / 100, 'percentage', raw_val
            except:
                return Decimal('0'), 'percentage', Decimal('0')
        
        # Otherwise it's a fixed amount - handle 'k' and 'm' suffixes
        cleaned = re.sub(r'[₦$€£,\s]', '', value_str)
        
        # Handle 'k' suffix (thousands)
        if cleaned.lower().endswith('k'):
            try:
                raw_val = Decimal(cleaned[:-1]) * 1000
                return raw_val, 'fixed', raw_val
            except:
                return Decimal('0'), 'fixed', Decimal('0')
        
        # Handle 'm' suffix (millions)
        if cleaned.lower().endswith('m'):
            try:
                raw_val = Decimal(cleaned[:-1]) * 1000000
                return raw_val, 'fixed', raw_val
            except:
                return Decimal('0'), 'fixed', Decimal('0')
        
        # Extract numeric value
        cleaned = re.sub(r'[^\d.-]', '', cleaned)
        try:
            raw_val = Decimal(cleaned) if cleaned else Decimal('0')
            return raw_val, 'fixed', raw_val
        except:
            return Decimal('0'), 'fixed', Decimal('0')


class QuotationItem(models.Model):
    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name='items')
    product_service = models.CharField(max_length=250, blank=True, help_text="Product or service name")
    description = models.CharField(max_length=500, blank=True, help_text="Detailed description")
    quantity = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)], blank=True, default=0)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)], blank=True, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Custom fields for flexibility
    custom_fields = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['id']
    
    def __str__(self):
        return f"{self.product_service or self.description} - {self.quotation.quotation_number}"
    
    def save(self, *args, **kwargs):
        # Calculate line total
        self.line_total = self.quantity * self.unit_price
        super().save(*args, **kwargs)
        
        # Recalculate quotation totals without triggering save again
        if self.quotation:
            self.quotation.calculate_totals()
