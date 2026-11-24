from django.db import models, IntegrityError
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator
from django.utils import timezone
from decimal import Decimal
import re
import json
import uuid

from apps.core.ownership import TenantOwnedManager
from .utils.quantity_parser import extract_numeric_value

User = get_user_model()


class WaybillTemplate(models.Model):
    """User-defined waybill templates with custom fields and styling"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='waybill_templates')
    name = models.CharField(max_length=200, help_text="Template name (e.g., 'Shipping Waybill', 'Delivery Note')")
    description = models.TextField(blank=True, help_text="Description of this template")
    
    # Color customization
    primary_color = models.CharField(max_length=7, default='#FF5900', help_text="Primary color (hex code)")
    secondary_color = models.CharField(max_length=7, default='#f8f9fa', help_text="Secondary color (hex code)")
    text_color = models.CharField(max_length=7, default='#333333', help_text="Text color (hex code)")
    
    # Template structure
    custom_fields = models.JSONField(default=dict, help_text="Custom field definitions")
    table_columns = models.JSONField(default=list, help_text="Custom table column definitions")
    
    # Display options
    show_company_logo = models.BooleanField(default=True)
    show_company_details = models.BooleanField(default=True)
    show_bank_details = models.BooleanField(default=False)
    show_signature = models.BooleanField(default=True)
    
    # Document settings
    document_title = models.CharField(max_length=100, default='WAYBILL', help_text="Document title to display")
    number_prefix = models.CharField(max_length=10, default='WB', help_text="Document number prefix")
    
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
            WaybillTemplate.objects.filter(user=self.user, is_default=True).update(is_default=False)
        super().save(*args, **kwargs)
    
    def get_default_custom_fields(self):
        """Return default custom fields if none are set"""
        if not self.custom_fields:
            return {
                'sender_info': {
                    'label': 'Sender Information',
                    'type': 'section',
                    'fields': {
                        'sender_name': {'label': 'Sender Name', 'type': 'text', 'required': False},
                        'sender_phone': {'label': 'Sender Phone', 'type': 'text', 'required': False},
                        'sender_address': {'label': 'Sender Address', 'type': 'textarea', 'required': False},
                    }
                },
                'receiver_info': {
                    'label': 'Receiver Information',
                    'type': 'section',
                    'fields': {
                        'receiver_name': {'label': 'Receiver Name', 'type': 'text', 'required': False},
                        'receiver_phone': {'label': 'Receiver Phone', 'type': 'text', 'required': False},
                        'receiver_address': {'label': 'Receiver Address', 'type': 'textarea', 'required': False},
                    }
                },
                'shipment_info': {
                    'label': 'Shipment Details',
                    'type': 'section',
                    'fields': {
                        'destination': {'label': 'Destination', 'type': 'text', 'required': False},
                        'vehicle_number': {'label': 'Vehicle Number', 'type': 'text', 'required': False},
                        'driver_name': {'label': 'Driver Name', 'type': 'text', 'required': False},
                        'driver_phone': {'label': 'Driver Phone', 'type': 'text', 'required': False},
                        'remark': {'label': 'Remark', 'type': 'textarea', 'required': False},
                    }
                }
            }
        return self.custom_fields
    
    def get_default_table_columns(self):
        """Return default table columns if none are set"""
        if not self.table_columns:
            return [
                {'name': 'product_service', 'label': 'Product / Service', 'type': 'text', 'width': '25%'},
                {'name': 'description', 'label': 'Description', 'type': 'text', 'width': '35%'},
                {'name': 'quantity', 'label': 'Quantity', 'type': 'number', 'width': '12%'},
                {'name': 'weight', 'label': 'Weight (kg)', 'type': 'number', 'width': '10%'},
                {'name': 'condition', 'label': 'Condition', 'type': 'text', 'width': '10%'},
            ]
        return self.table_columns


class Waybill(models.Model):
    """Dynamic waybill with customizable fields and styling"""
    STATUS_CHOICES = [
        ('delivered', 'Delivered'),
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('dispatched', 'Dispatched / In Transit'),
        ('not_delivered', 'Not Delivered'),
        ('returned', 'Returned'),
        ('cancelled', 'Cancelled'),
        ('on_hold', 'On Hold'),
        ('awaiting_pickup', 'Awaiting Pickup'),
    ]
    
    waybill_number = models.CharField(max_length=50, unique=True, editable=False)
    waybill_date = models.DateField(auto_now_add=True)
    delivery_date = models.DateField(null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='waybills')
    template = models.ForeignKey(WaybillTemplate, on_delete=models.CASCADE, related_name='waybills')
    # Tenant and creator for per-team-member isolation (backfilled from user in migration)
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='waybills',
        null=True,
        blank=True,
        help_text='Tenant account; set from user.account on save if missing.',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='waybills_created',
        help_text='User who created this waybill; set from user on save if missing.',
    )
    # Dynamic custom field data
    custom_data = models.JSONField(default=dict, help_text="Custom field values based on template")

    # Delivery quantity tracking (stores both raw input and parsed numeric values)
    total_quantity_input = models.CharField(max_length=255, blank=True, null=True)
    delivered_quantity_input = models.CharField(max_length=255, blank=True, null=True)

    total_quantity_value = models.FloatField(default=0)
    delivered_quantity_value = models.FloatField(default=0)
    remaining_quantity_value = models.FloatField(default=0)

    is_approved = models.BooleanField(default=False)
    approved_at = models.DateTimeField(blank=True, null=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_waybills",
    )
    
    # Standard fields
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    is_deleted = models.BooleanField(default=False)

    objects = models.Manager()  # Default manager for admin and internal operations
    visible_objects = TenantOwnedManager()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['account', '-created_at']),
            models.Index(fields=['waybill_number']),
            models.Index(fields=['status']),
            models.Index(fields=['waybill_date']),
            models.Index(fields=['template', 'user']),
        ]
        # Custom action-level permissions so viewing, printing, approving,
        # and downloading waybills can be controlled independently.
        permissions = [
            ("print_waybill", "Can print waybill"),
            ("download_waybill", "Can download or export waybill data"),
            ("can_approve_waybill", "Can approve waybills"),
        ]
        
    def __str__(self):
        return f"Waybill {self.waybill_number}"
    
    def save(self, *args, **kwargs):
        # Per-team-member isolation: set tenant and creator from user when missing
        if self.user_id and (not self.account_id or not self.created_by_id):
            if not self.account_id and getattr(self.user, 'account_id', None):
                self.account_id = self.user.account_id
            if not self.created_by_id:
                self.created_by_id = self.user_id

        # Auto-generate waybill number when missing
        if not self.waybill_number:
            self.waybill_number = self.generate_waybill_number()

        # Delivery quantity tracking: parse numeric values and compute remaining / approval
        try:
            self.total_quantity_value = float(
                extract_numeric_value(self.total_quantity_input)
            ) if self.total_quantity_input else 0.0
        except Exception:
            self.total_quantity_value = 0.0

        try:
            self.delivered_quantity_value = float(
                extract_numeric_value(self.delivered_quantity_input)
            ) if self.delivered_quantity_input else 0.0
        except Exception:
            self.delivered_quantity_value = 0.0

        remaining = self.total_quantity_value - self.delivered_quantity_value
        if remaining < 0:
            remaining = 0.0
        self.remaining_quantity_value = remaining

        # Auto-approval when fully delivered
        if self.total_quantity_value > 0 and self.remaining_quantity_value <= 0:
            if not self.is_approved:
                self.is_approved = True
                if not self.approved_at:
                    self.approved_at = timezone.now()
        else:
            # Do not clear approved_by here to preserve manual approvals,
            # but reset is_approved/approved_at for automatic state.
            if self.is_approved and self.remaining_quantity_value > 0:
                self.is_approved = False
                # Only clear approved_at if this was an automatic approval.
                # Manual approvals will explicitly set approved_at again.
                if self.approved_at and not self.approved_by:
                    self.approved_at = None
        
        # Handle potential duplicate waybill numbers with retry mechanism
        max_retries = 3
        for retry in range(max_retries):
            try:
                super().save(*args, **kwargs)
                break  # Success, exit retry loop
                
            except IntegrityError as e:
                if 'UNIQUE constraint failed: waybills_waybill.waybill_number' in str(e) and retry < max_retries - 1:
                    # Generate a new waybill number and try again
                    self.waybill_number = self.generate_waybill_number()
                    continue
                else:
                    # Re-raise the error if it's not a duplicate waybill number or we've exhausted retries
                    raise
    
    def generate_waybill_number(self):
        """Generate unique waybill number with collision handling"""
        from datetime import datetime
        import random
        year = datetime.now().year
        prefix = self.template.number_prefix if self.template else 'WB'
        
        # Try multiple attempts to generate a unique number
        for attempt in range(10):
            if attempt == 0:
                # First try: use count-based approach
                count = Waybill.objects.filter(
                    user=self.user,
                    created_at__year=year
                ).count() + 1
                waybill_number = f"{prefix}-{year}-{count:04d}"
            else:
                # Subsequent tries: add random component to avoid collisions
                count = Waybill.objects.filter(
                    user=self.user,
                    created_at__year=year
                ).count() + 1
                random_suffix = random.randint(1000, 9999)
                waybill_number = f"{prefix}-{year}-{count:04d}-{random_suffix}"
            
            # Check if this number already exists
            if not Waybill.objects.filter(waybill_number=waybill_number).exists():
                return waybill_number
        
        # Final fallback: timestamp + random, ensure unique
        import time
        for _ in range(5):
            timestamp = int(time.time() * 1000) % 100000
            suffix = random.randint(1000, 9999)
            waybill_number = f"{prefix}-{year}-{timestamp}-{suffix}"
            if not Waybill.objects.filter(waybill_number=waybill_number).exists():
                return waybill_number
        # Last resort: full timestamp
        return f"{prefix}-{year}-{int(time.time() * 1000)}"
    
    def get_custom_field_value(self, section, field_name, default=''):
        """Get value for a custom field"""
        if section in self.custom_data and field_name in self.custom_data[section]:
            return self.custom_data[section][field_name]
        return default
    
    def set_custom_field_value(self, section, field_name, value):
        """Set value for a custom field"""
        if section not in self.custom_data:
            self.custom_data[section] = {}
        self.custom_data[section][field_name] = value
    
    @staticmethod
    def parse_number(value):
        """Parse smart number inputs like ₦3k, 7.5%, -500, '80 nires', '45n', 'N 20'"""
        if not value:
            return Decimal('0')
        
        value = str(value).strip()
        original_value = value
        
        # Remove currency symbols first
        value = re.sub(r'[₦$€£,]', '', value)
        
        # Handle percentage
        if '%' in value:
            # Extract number before %
            numbers = re.findall(r'-?\d+\.?\d*', value.replace('%', ''))
            if numbers:
                return Decimal(numbers[0]) / 100
            return Decimal('0')
        
        # Handle 'k' suffix (thousands) - extract number before k
        if value.lower().endswith('k'):
            numbers = re.findall(r'-?\d+\.?\d*', value[:-1])
            if numbers:
                return Decimal(numbers[0]) * 1000
            return Decimal('0')
        
        # Handle 'm' suffix (millions) - extract number before m
        if value.lower().endswith('m'):
            numbers = re.findall(r'-?\d+\.?\d*', value[:-1])
            if numbers:
                return Decimal(numbers[0]) * 1000000
            return Decimal('0')
        
        # Extract all numbers from the string (handles cases like "80 nires", "45n", "N 20")
        numbers = re.findall(r'-?\d+\.?\d*', value)
        if numbers:
            # Take the first number found
            try:
                return Decimal(numbers[0])
            except:
                return Decimal('0')
        
        # Try parsing the whole string as a number (fallback)
        try:
            return Decimal(value)
        except:
            return Decimal('0')


class WaybillItem(models.Model):
    """Dynamic waybill items based on template configuration"""
    waybill = models.ForeignKey(Waybill, on_delete=models.CASCADE, related_name='items')
    
    # Dynamic item data based on template columns
    item_data = models.JSONField(default=dict, help_text="Item field values based on template columns")
    
    # Standard fields
    row_order = models.PositiveIntegerField(default=0)
    
    class Meta:
        ordering = ['row_order', 'id']
    
    def __str__(self):
        # Try to get a meaningful description from item_data
        for field in ['item_description', 'description', 'product', 'item']:
            if field in self.item_data and self.item_data[field]:
                return f"{self.item_data[field]} - {self.waybill.waybill_number}"
        return f"Item - {self.waybill.waybill_number}"
    
    def get_column_value(self, column_name, default=''):
        """Get value for a specific column"""
        return self.item_data.get(column_name, default)
    
    def set_column_value(self, column_name, value):
        """Set value for a specific column"""
        self.item_data[column_name] = value
    
    def save(self, *args, **kwargs):
        # Auto-set row_order if not provided
        if not self.row_order:
            max_order = WaybillItem.objects.filter(waybill=self.waybill).aggregate(
                models.Max('row_order')
            )['row_order__max']
            self.row_order = (max_order or 0) + 1
        super().save(*args, **kwargs)


class WaybillFieldTemplate(models.Model):
    """Reusable field templates for waybill customization"""
    FIELD_TYPES = [
        ('text', 'Text Input'),
        ('textarea', 'Textarea'),
        ('number', 'Number'),
        ('date', 'Date'),
        ('email', 'Email'),
        ('phone', 'Phone'),
        ('select', 'Dropdown'),
        ('checkbox', 'Checkbox'),
        ('section', 'Section Header'),
    ]
    
    name = models.CharField(max_length=100, unique=True)
    label = models.CharField(max_length=200)
    field_type = models.CharField(max_length=20, choices=FIELD_TYPES)
    options = models.JSONField(default=dict, help_text="Field options (for select, etc.)")
    is_required = models.BooleanField(default=False)
    placeholder = models.CharField(max_length=200, blank=True)
    help_text = models.CharField(max_length=500, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return f"{self.label} ({self.field_type})"
