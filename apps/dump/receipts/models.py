from django.db import models
from django.contrib.auth import get_user_model
from decimal import Decimal
from django.utils import timezone
from apps.invoices.models import Invoice
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
import time
import random
from django.db.utils import IntegrityError
import uuid

from apps.core.ownership import TenantOwnedManager

User = get_user_model()

PAYMENT_CHOICES = [
    ("cash", "Cash"),
    ("bank_transfer", "Bank Transfer"),
    ("cheque", "Cheque"),
    ("card", "Card"),
    ("mobile_money", "Mobile Money"),
    ("other", "Other"),
]

class Receipt(models.Model):
    """
    Receipt model linked to Invoice. Tracks payments, supports custom color, and stores audit info.
    """
    receipt_no = models.CharField(max_length=20, unique=True)
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="receipts")
    client_name = models.CharField(max_length=255)
    client_phone = models.CharField(max_length=20, blank=True, null=True)
    client_address = models.CharField(max_length=500, blank=True, null=True)
    amount_received = models.DecimalField(max_digits=64, decimal_places=2)
    amount_in_words = models.CharField(max_length=500)
    payment_method = models.CharField(max_length=100, choices=PAYMENT_CHOICES)
    transaction_id = models.CharField(max_length=100, blank=True, null=True)
    received_by = models.CharField(max_length=255)
    date_received = models.DateField(auto_now_add=True)
    notes = models.TextField(blank=True, null=True)
    balance_after_payment = models.DecimalField(max_digits=64, decimal_places=2)
    custom_color = models.CharField(max_length=20, default="#000000")
    show_bank_details = models.BooleanField(default=True, help_text="Show bank details on this receipt")
    show_signature = models.BooleanField(default=True, help_text="Show signature on this receipt")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    is_deleted = models.BooleanField(default=False)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='receipts_created')
    # Tenant for per-team-member isolation (backfilled from invoice.user.account in migration)
    account = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        related_name='receipts',
        null=True,
        blank=True,
        help_text='Tenant account; set from invoice or created_by on save if missing.',
    )

    objects = models.Manager()  # Default manager for admin and internal operations
    visible_objects = TenantOwnedManager()

    class Meta:
        # Default view/add/change/delete permissions plus custom action-level ones.
        permissions = [
            ("print_receipt", "Can print receipt"),
            ("download_receipt", "Can download or export receipt data"),
        ]

    def save(self, *args, **kwargs):
        # Per-team-member isolation: set tenant from invoice or created_by when missing
        if not self.account_id:
            if getattr(self, 'invoice_id', None) and getattr(self.invoice, 'user_id', None) and getattr(self.invoice.user, 'account_id', None):
                self.account_id = self.invoice.user.account_id
            elif getattr(self, 'created_by_id', None) and getattr(self.created_by, 'account_id', None):
                self.account_id = self.created_by.account_id
        if not self.receipt_no:
            for _ in range(5):
                self.receipt_no = self.generate_receipt_no()
                try:
                    super().save(*args, **kwargs)
                    return
                except IntegrityError:
                    continue
            raise IntegrityError("Could not generate a unique receipt number after several attempts.")
        else:
            super().save(*args, **kwargs)

    def generate_receipt_no(self):
        """Generate a unique receipt number (REC-YYYYMMDD-NNN-RRR), max 20 chars."""
        from django.utils import timezone
        date_str = timezone.now().strftime("%Y%m%d")
        for attempt in range(10):
            count = Receipt.objects.filter(date_received=timezone.now().date()).count() + 1
            # Add timestamp component on later attempts to reduce collision chance
            random_part = random.randint(100, 999)
            if attempt >= 5:
                random_part = (random_part + int(time.time() * 1000) % 900) % 900 + 100  # stay 100-999
            receipt_no = f"REC-{date_str}-{count:03d}-{random_part}"
            if not Receipt.objects.filter(receipt_no=receipt_no).exists():
                return receipt_no
        # Fallback: timestamp-based, ensure unique (within 20 chars: REC-YYYYMMDD-NNNNN = 18)
        for _ in range(5):
            fallback_no = f"REC-{date_str}-{int(time.time() * 1000) % 100000}"
            if not Receipt.objects.filter(receipt_no=fallback_no).exists():
                return fallback_no
        return f"REC-{date_str}-{int(time.time() * 1000) % 100000}"

    def __str__(self):
        return f"Receipt {self.receipt_no} for {self.client_name}"


@receiver(post_save, sender=Receipt)
def update_invoice_on_receipt_save(sender, instance, created, **kwargs):
    invoice = instance.invoice
    # Recalculate all receipts for this invoice
    total_received = sum(r.amount_received for r in invoice.receipts.all())
    invoice.amount_paid = total_received
    invoice.balance_due = invoice.grand_total - total_received
    # Update status
    if invoice.amount_paid == 0:
        invoice.status = 'unpaid'
    elif invoice.amount_paid >= invoice.grand_total:
        invoice.status = 'paid'
    else:
        invoice.status = 'partial'
    invoice.save()

@receiver(post_delete, sender=Receipt)
def update_invoice_on_receipt_delete(sender, instance, **kwargs):
    invoice = instance.invoice
    total_received = sum(r.amount_received for r in invoice.receipts.all())
    invoice.amount_paid = total_received
    invoice.balance_due = invoice.grand_total - total_received
    # Update status
    if invoice.amount_paid == 0:
        invoice.status = 'unpaid'
    elif invoice.amount_paid >= invoice.grand_total:
        invoice.status = 'paid'
    else:
        invoice.status = 'partial'
    invoice.save()


def _receipt_account(receipt):
    from apps.core.models import Account

    if getattr(receipt, 'account_id', None):
        try:
            return receipt.account
        except Account.DoesNotExist:
            pass
    if getattr(receipt, 'invoice_id', None) and getattr(receipt.invoice, 'user_id', None):
        if getattr(receipt.invoice.user, 'account_id', None):
            try:
                return receipt.invoice.user.account
            except Account.DoesNotExist:
                pass
    if getattr(receipt, 'created_by_id', None) and getattr(receipt.created_by, 'account_id', None):
        try:
            return receipt.created_by.account
        except Account.DoesNotExist:
            pass
    return None


def _log_receipt_activity(instance, activity_type, created=None):
    from apps.accounts.models import UserActivity
    from apps.accounts.activity_tracking import get_current_request
    account = _receipt_account(instance)
    if not account:
        return
    request = get_current_request()
    user = getattr(request, 'user', None) if request else None
    if not user or not user.is_authenticated:
        user = getattr(instance, 'created_by', None) or (instance.invoice.user if getattr(instance, 'invoice_id', None) else None)
    if activity_type == 'CREATE':
        desc = f"Receipt {instance.receipt_no} created for {instance.client_name}"
    elif activity_type == 'UPDATE':
        desc = f"Receipt {instance.receipt_no} updated"
    else:
        desc = f"Receipt {instance.receipt_no} deleted"
    UserActivity.log_activity(
        user=user,
        account=account,
        activity_type=activity_type,
        description=desc,
        app_name='receipts',
        model_name='Receipt',
        object_id=str(instance.pk),
        object_repr=instance.receipt_no or str(instance),
    )


@receiver(post_save, sender=Receipt)
def log_receipt_activity_on_save(sender, instance, created, **kwargs):
    _log_receipt_activity(instance, 'CREATE' if created else 'UPDATE')


@receiver(post_delete, sender=Receipt)
def log_receipt_activity_on_delete(sender, instance, **kwargs):
    _log_receipt_activity(instance, 'DELETE')
