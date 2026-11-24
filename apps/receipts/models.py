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
    refund_due = models.DecimalField(max_digits=64, decimal_places=2, default=0, help_text="Amount to be refunded to customer if overpayment")
    payment_type = models.CharField(max_length=20, default='full', choices=[
        ('full', 'Full Payment'),
        ('partial', 'Partial Payment'),
        ('over', 'Over Payment'),
    ])
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

    def prior_amount_received(self):
        """
        Sum of non-deleted receipts recorded before this one on the same invoice.
        Used so each receipt keeps a historical 'balance after' (later payments
        do not rewrite earlier receipts).
        """
        if not getattr(self, 'invoice_id', None):
            return Decimal('0')
        qs = self.invoice.receipts.filter(is_deleted=False)
        if self.pk:
            if self.created_at:
                qs = qs.filter(
                    models.Q(created_at__lt=self.created_at)
                    | models.Q(created_at=self.created_at, pk__lt=self.pk)
                )
            else:
                qs = qs.filter(pk__lt=self.pk)
        total = qs.aggregate(total=models.Sum('amount_received'))['total']
        return Decimal(str(total or 0))

    def apply_payment_calculations(self):
        """
        Keep balance_after_payment, payment_type, and refund_due in sync.

        Balance after = invoice total - (prior receipts + this receipt).
        That is what the customer still owes after this payment is applied.
        """
        if not getattr(self, 'invoice_id', None) or self.amount_received is None:
            if self.balance_after_payment is None:
                self.balance_after_payment = Decimal('0')
            return

        invoice_total = Decimal(str(self.invoice.grand_total or 0))
        amount = Decimal(str(self.amount_received or 0))
        remaining_balance = invoice_total - self.prior_amount_received() - amount
        self.balance_after_payment = remaining_balance

        if remaining_balance < 0:
            self.payment_type = 'over'
            self.refund_due = abs(remaining_balance)
        elif remaining_balance > 0:
            self.payment_type = 'partial'
            self.refund_due = Decimal('0')
        else:
            self.payment_type = 'full'
            self.refund_due = Decimal('0')

    def payment_fields_out_of_sync(self):
        """True when stored balance/type disagree with current invoice + receipts."""
        if not getattr(self, 'invoice_id', None) or self.amount_received is None:
            return False
        invoice_total = Decimal(str(self.invoice.grand_total or 0))
        amount = Decimal(str(self.amount_received or 0))
        expected_balance = invoice_total - self.prior_amount_received() - amount
        if expected_balance < 0:
            expected_type = 'over'
            expected_refund = abs(expected_balance)
        elif expected_balance > 0:
            expected_type = 'partial'
            expected_refund = Decimal('0')
        else:
            expected_type = 'full'
            expected_refund = Decimal('0')
        stored_balance = Decimal(str(self.balance_after_payment or 0))
        stored_refund = Decimal(str(self.refund_due or 0))
        return (
            stored_balance != expected_balance
            or self.payment_type != expected_type
            or stored_refund != expected_refund
        )

    def save(self, *args, **kwargs):
        # Per-team-member isolation: set tenant from invoice or created_by when missing
        if not self.account_id:
            if getattr(self, 'invoice_id', None) and getattr(self.invoice, 'user_id', None) and getattr(self.invoice.user, 'account_id', None):
                self.account_id = self.invoice.user.account_id
            elif getattr(self, 'created_by_id', None) and getattr(self.created_by, 'account_id', None):
                self.account_id = self.created_by.account_id
            else:
                from apps.core.ownership import get_account_for_user
                user = getattr(self, 'created_by', None) or (getattr(self.invoice, 'user', None) if getattr(self, 'invoice_id', None) else None)
                if user:
                    acc = get_account_for_user(user)
                    if acc:
                        self.account_id = acc.id
        self.apply_payment_calculations()
        if not self.receipt_no:
            for _ in range(5):
                self.receipt_no = self.generate_receipt_no()
                try:
                    super().save(*args, **kwargs)
                    return
                except IntegrityError:
                    continue
            raise IntegrityError("Could not generate a unique receipt number after several attempts.")
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


def _payment_fields_for_remaining(remaining_balance):
    """Map remaining balance to payment_type + refund_due."""
    remaining_balance = Decimal(str(remaining_balance))
    if remaining_balance < 0:
        return remaining_balance, 'over', abs(remaining_balance)
    if remaining_balance > 0:
        return remaining_balance, 'partial', Decimal('0')
    return remaining_balance, 'full', Decimal('0')


def resync_invoice_and_receipts(invoice, refresh_invoice_totals=False):
    """
    Single source of truth for invoice ↔ receipt payment sync.

    - Walks non-deleted receipts in chronological order
    - Sets each receipt's balance_after_payment / payment_type / refund_due
    - Sets invoice amount_paid / balance_due / status from the total received
    """
    if not invoice or not getattr(invoice, 'pk', None):
        return

    if refresh_invoice_totals:
        try:
            invoice.calculate_totals()
        except Exception:
            pass

    invoice_total = Decimal(str(invoice.grand_total or 0))
    receipts = list(
        invoice.receipts.filter(is_deleted=False).order_by('created_at', 'pk')
    )
    running = Decimal('0')
    for receipt in receipts:
        amount = Decimal(str(receipt.amount_received or 0))
        running += amount
        remaining, payment_type, refund_due = _payment_fields_for_remaining(invoice_total - running)
        stored_balance = Decimal(str(receipt.balance_after_payment or 0))
        stored_refund = Decimal(str(receipt.refund_due or 0))
        if (
            stored_balance != remaining
            or receipt.payment_type != payment_type
            or stored_refund != refund_due
        ):
            Receipt.objects.filter(pk=receipt.pk).update(
                balance_after_payment=remaining,
                payment_type=payment_type,
                refund_due=refund_due,
            )
            receipt.balance_after_payment = remaining
            receipt.payment_type = payment_type
            receipt.refund_due = refund_due

    total_received = running
    balance_due = invoice_total - total_received
    if total_received == 0 or invoice_total <= 0:
        status = 'unpaid'
    elif total_received >= invoice_total:
        status = 'delivered' if invoice.status == 'delivered' else 'paid'
    else:
        status = 'partial'

    if (
        Decimal(str(invoice.amount_paid or 0)) != total_received
        or Decimal(str(invoice.balance_due or 0)) != balance_due
        or invoice.status != status
    ):
        invoice.amount_paid = total_received
        invoice.balance_due = balance_due
        invoice.status = status
        # Avoid full save()/calculate_totals() here: it can zero grand_total when
        # called mid-edit without items loaded, and would recurse through signals.
        Invoice.objects.filter(pk=invoice.pk).update(
            amount_paid=total_received,
            balance_due=balance_due,
            status=status,
        )


_resync_guard = False


def _sync_invoice_from_receipts(invoice):
    """Recalculate invoice + all receipt payment fields from non-deleted receipts."""
    global _resync_guard
    if not invoice or _resync_guard:
        return
    _resync_guard = True
    try:
        resync_invoice_and_receipts(invoice)
    finally:
        _resync_guard = False


@receiver(post_save, sender=Receipt)
def update_invoice_on_receipt_save(sender, instance, created, **kwargs):
    _sync_invoice_from_receipts(instance.invoice)


@receiver(post_delete, sender=Receipt)
def update_invoice_on_receipt_delete(sender, instance, **kwargs):
    _sync_invoice_from_receipts(instance.invoice)


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
