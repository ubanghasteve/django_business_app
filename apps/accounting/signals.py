from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from django.utils import timezone
from .models import Transaction
from apps.invoices.models import Invoice
from apps.receipts.models import Receipt
from apps.job_orders.models import Product as JobOrder
from apps.waybills.models import Waybill
from apps.core.utils import get_company_profile_for_user
from decimal import Decimal
import logging

User = get_user_model()
logger = logging.getLogger(__name__)


def _sync_to_finance_engine(txn):
    """Push accounting Transaction to finance engine so tax/reports see it."""
    from apps.finance_engine.services import sync_app_transaction_to_finance
    if not txn.reference_id or not txn.company_id:
        return
    sync_app_transaction_to_finance(
        company=txn.company,
        source_app=txn.source_app,
        source_id=txn.reference_id,
        transaction_type='revenue' if txn.type == 'income' else 'expense',
        amount=txn.net_amount or txn.amount,
        transaction_date=txn.transaction_date,
        description=txn.title or txn.description or '',
        vat_amount=txn.tax if getattr(txn, 'tax', None) else None,
    )


@receiver(post_save, sender=Invoice)
def sync_invoice_to_accounting(sender, instance, created, **kwargs):
    """Sync invoice payments to accounting transactions
    
    Only create transaction from Invoice if there are no receipts linked to it.
    When receipts exist, they handle the accounting to avoid duplicates.
    """
    if instance.status != 'paid' or not instance.grand_total or instance.grand_total <= 0 or not getattr(instance, 'user_id', None):
        return
    from django.db import transaction as db_transaction
    try:
        with db_transaction.atomic():
            if instance.receipts.exists():
                return
            company = get_company_profile_for_user(instance.user)
            if not company:
                return
            existing_transaction = Transaction.objects.filter(
                source_app='invoice',
                reference_id=str(instance.id)
            ).first()

            if not existing_transaction:
                txn_date = instance.updated_at.date() if instance.updated_at else timezone.now().date()
                txn = Transaction.objects.create(
                    user=instance.user,
                    company=company,
                    type='income',
                    title=f"Invoice Payment - {instance.invoice_number}",
                    description=f"Payment for invoice {instance.invoice_number} from {instance.client_name}",
                    amount=instance.grand_total,
                    currency=company.currency_code,
                    tax=instance.total_tax,
                    discount=instance.total_discount,
                    source_app='invoice',
                    reference_id=str(instance.id),
                    reference_model='Invoice',
                    transaction_date=txn_date,
                    notes=f"Auto-synced from paid invoice {instance.invoice_number}"
                )
                _sync_to_finance_engine(txn)
    except Exception:
        logger.exception('Accounting sync failed for invoice_id=%s', instance.pk)


@receiver(post_save, sender=Receipt)
def sync_receipt_to_accounting(sender, instance, created, **kwargs):
    """Sync receipt payments to accounting transactions
    
    Check if transaction already exists from this receipt OR from the invoice
    to avoid duplicates when invoice was marked paid before receipts were created.
    """
    if created and instance.amount_received > 0 and instance.created_by_id:
        company = get_company_profile_for_user(instance.created_by)
        if not company:
            return
        # Check if transaction already exists from this receipt
        existing_transaction = Transaction.objects.filter(
            source_app='receipt',
            reference_id=str(instance.id)
        ).first()
        
        # Also check if transaction exists from the invoice (invoice was marked paid before receipt)
        if not existing_transaction and getattr(instance, 'invoice_id', None):
            existing_transaction = Transaction.objects.filter(
                source_app='invoice',
                reference_id=str(instance.invoice_id)
            ).first()
        
        if not existing_transaction:
            txn = Transaction.objects.create(
                user=instance.created_by,
                company=company,
                type='income',
                title=f"Receipt Payment - {instance.receipt_no}",
                description=f"Payment receipt {instance.receipt_no} from {instance.client_name}",
                amount=instance.amount_received,
                currency=company.currency_code,
                source_app='receipt',
                reference_id=str(instance.id),
                reference_model='Receipt',
                transaction_date=instance.date_received,
                notes=f"Auto-synced from receipt {instance.receipt_no}"
            )
            _sync_to_finance_engine(txn)


@receiver(post_save, sender=JobOrder)
def sync_job_order_to_accounting(sender, instance, created, **kwargs):
    """Sync job order costs to accounting transactions"""
    if instance.approval_status == 'approved' and instance.total and instance.total > 0 and getattr(instance, 'created_by_id', None):
        company = get_company_profile_for_user(instance.created_by)
        if not company:
            return
        # Check if transaction already exists
        existing_transaction = Transaction.objects.filter(
            source_app='job_order',
            reference_id=str(instance.id)
        ).first()
        
        if not existing_transaction:
            txn = Transaction.objects.create(
                user=instance.created_by,
                company=company,
                type='expense',
                title=f"Job Order Cost - {instance.job_order}",
                description=f"Cost for approved job order {instance.job_order}",
                amount=instance.total,
                currency=company.currency_code,
                source_app='job_order',
                reference_id=str(instance.id),
                reference_model='Product',
                transaction_date=instance.actual_delivery_date or instance.date_created.date(),
                notes=f"Auto-synced from approved job order {instance.job_order}"
            )
            _sync_to_finance_engine(txn)


@receiver(post_save, sender=Waybill)
def sync_waybill_to_accounting(sender, instance, created, **kwargs):
    """Sync waybill charges to accounting transactions (Waybill has no total_amount field; use getattr for safety)."""
    total_amount = getattr(instance, 'total_amount', 0) or 0
    if instance.status == 'delivered' and total_amount > 0 and getattr(instance, 'created_by_id', None):
        company = get_company_profile_for_user(instance.created_by)
        if not company:
            return
        # Check if transaction already exists
        existing_transaction = Transaction.objects.filter(
            source_app='waybill',
            reference_id=str(instance.id)
        ).first()
        
        if not existing_transaction:
            txn = Transaction.objects.create(
                user=instance.created_by,
                company=company,
                type='income',
                title=f"Waybill Charges - {instance.waybill_number}",
                description=f"Charges for delivered waybill {instance.waybill_number}",
                amount=total_amount,
                currency=company.currency_code,
                source_app='waybill',
                reference_id=str(instance.id),
                reference_model='Waybill',
                transaction_date=instance.delivery_date or instance.created_at.date(),
                notes=f"Auto-synced from delivered waybill {instance.waybill_number}"
            )
            _sync_to_finance_engine(txn)


@receiver(post_save, sender='expense.Expense')
def sync_expense_to_accounting(sender, instance, created, **kwargs):
    """
    Sync approved expenses to accounting transactions.

    We create an expense-type Transaction once an Expense is approved and has a
    positive total_amount, avoiding duplicates via source_app/reference_id.
    """
    from apps.expense.models import Expense  # safety import

    if not isinstance(instance, Expense):
        return

    if instance.status not in ('approved', 'pending'):
        return
    if not instance.total_amount or instance.total_amount <= 0:
        return

    company = instance.company
    if not company and instance.account_id:
        # Fallback: derive company from account if needed
        company = getattr(instance, 'company', None)
    if not company:
        return

    existing_transaction = Transaction.objects.filter(
        company=company,
        source_app='expense',
        reference_id=str(instance.id),
    ).first()

    if existing_transaction:
        return

    txn = Transaction.objects.create(
        user=instance.created_by or getattr(company, 'user', None),
        company=company,
        type='expense',
        title=f"Expense - {instance.product_name or instance.description or instance.transaction_id}",
        description=instance.description,
        amount=instance.total_amount,
        currency=getattr(company, 'currency_symbol', None) or getattr(company, 'currency_code', '₦'),
        source_app='expense',
        reference_id=str(instance.id),
        reference_model='Expense',
        transaction_date=instance.expense_date,
        notes=f"Auto-synced from expense record {instance.transaction_id}",
    )
    _sync_to_finance_engine(txn)


@receiver(post_delete, sender=Transaction)
def handle_transaction_deletion(sender, instance, **kwargs):
    """Handle transaction deletion by updating ledgers and removing finance sync."""
    from apps.finance_engine.services import remove_app_transaction_from_finance
    if instance.reference_id and instance.company_id and instance.source_app:
        remove_app_transaction_from_finance(
            instance.company,
            instance.source_app,
            instance.reference_id,
        )
    if not instance.is_void:
        # Update the ledger for the deleted transaction's month/year
        from .models import Ledger
        
        ledger = Ledger.objects.filter(
            company=instance.company,
            year=instance.transaction_date.year,
            month=instance.transaction_date.month
        ).first()
        
        if ledger:
            # Recalculate totals for this month
            transactions = Transaction.objects.filter(
                company=instance.company,
                transaction_date__year=instance.transaction_date.year,
                transaction_date__month=instance.transaction_date.month,
                is_void=False
            )
            
            from django.db.models import Sum
            
            ledger.total_income = transactions.filter(type='income').aggregate(
                total=Sum('net_amount')
            )['total'] or 0
            
            ledger.total_expense = transactions.filter(type='expense').aggregate(
                total=Sum('net_amount')
            )['total'] or 0
            
            ledger.net_profit = ledger.total_income - ledger.total_expense
            ledger.save()


# Bridge: Sync JournalEntry to Transaction for unified reporting
@receiver(post_save, sender='accounting.JournalEntry')
def sync_journal_entry_to_transaction(sender, instance, created, **kwargs):
    """
    When a JournalEntry is posted, create a corresponding Transaction record
    for unified reporting across both accounting systems.
    """
    from .models import JournalEntry, Transaction
    
    if instance.status != 'posted':
        return
    
    if not instance.company:
        return
    
    journal = instance
    total_amount = journal.total_debit
    
    if total_amount <= 0:
        return
    
    existing = Transaction.objects.filter(
        source_app='journal',
        reference_id=str(journal.id),
    ).first()
    
    if existing:
        return
    
    is_income = False
    is_expense = False
    
    for line in journal.lines.select_related('account__category'):
        cat_type = getattr(line.account.category, 'category_type', None)
        if cat_type == 'income':
            is_income = True
        elif cat_type == 'expense':
            is_expense = True
    
    if not is_income and not is_expense:
        return
    
    txn_type = 'income' if is_income else 'expense'
    
    Transaction.objects.create(
        user=journal.created_by,
        company=journal.company,
        type=txn_type,
        title=f"Journal Entry - {journal.reference or str(journal.id)[:8]}",
        description=journal.description,
        amount=total_amount,
        currency=getattr(journal.company, 'currency_symbol', '₦'),
        source_app='journal',
        reference_id=str(journal.id),
        reference_model='JournalEntry',
        transaction_date=journal.date,
        notes=f"Auto-synced from posted journal entry"
    )


@receiver(post_save, sender='accounting.JournalEntry')
def update_transaction_on_journal_void(sender, instance, **kwargs):
    """When a JournalEntry is voided, void the corresponding Transaction."""
    from .models import Transaction
    
    if instance.status == 'void':
        Transaction.objects.filter(
            source_app='journal',
            reference_id=str(instance.id),
        ).update(is_void=True)
    elif instance.status == 'posted':
        Transaction.objects.filter(
            source_app='journal',
            reference_id=str(instance.id),
        ).update(is_void=False)


# Import signals when the app is ready
def ready():
    import apps.accounting.signals 