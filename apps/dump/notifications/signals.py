"""
Signals to create notifications when records are created or updated across apps.
Respects RBAC, data isolation, and multi-tenant permissions.

Production-safe: resolves account/user from instance when FKs are missing (e.g. bulk save,
migrations, or different server env). Logs errors without breaking the main save.
"""
import logging
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.urls import reverse

from .services import (
    create_notification,
    notify_conversation_members,
    get_hr_notification_recipients,
    get_company_admin_and_visibility_recipients,
)

logger = logging.getLogger(__name__)


ACTIVITY_APP_TO_SOURCE = {
    # Invoices / Receipts / Quotations / Waybills
    'invoices': 'invoices',
    'invoice': 'invoices',
    'receipts': 'receipts',
    'receipt': 'receipts',
    'quotations': 'quotations',
    'quotation': 'quotations',
    'waybills': 'waybills',
    'waybill': 'waybills',
    # Inventory / Expense
    'inventory': 'inventory',
    'expense': 'expense',
    'expenses': 'expense',
    # Requisitions
    'requisitions': 'requisitions',
    'requisition': 'requisitions',
    # Job orders / products
    'job_orders': 'job_orders',
    'joborders': 'job_orders',
    'jobs': 'job_orders',
    'products': 'job_orders',
    # Clients
    'clients': 'clients',
    'client': 'clients',
}


def _get_base_url():
    """Base URL for building action_url - use relative paths for portability."""
    return ''  # Relative paths work from any host


def _account_for_instance(instance, created_by_attr='created_by', user_attr='user'):
    """
    Resolve Account from instance for notification scope. Works when account_id is set
    in save() after our signal or when running in production with different load order.
    """
    from apps.core.models import Account
    acc = getattr(instance, 'account', None)
    if acc is not None:
        return acc
    aid = getattr(instance, 'account_id', None)
    if aid is not None:
        return Account.objects.filter(pk=aid).first()
    for attr in (created_by_attr, user_attr):
        u = getattr(instance, attr, None)
        if u is not None:
            acc = getattr(u, 'account', None)
            if acc is not None:
                return acc
            aid = getattr(u, 'account_id', None)
            if aid is not None:
                return Account.objects.filter(pk=aid).first()
    return None


def _user_for_instance(instance, created_by_attr='created_by', user_attr='user'):
    """Resolve recipient User from instance (created_by or user)."""
    u = getattr(instance, created_by_attr, None) or getattr(instance, user_attr, None)
    return u


def _choice_display(choices, value):
    """Get display label for a choice value; choices is a list of (value, label) tuples."""
    if value is None:
        return ''
    if hasattr(choices, '__iter__') and not isinstance(choices, dict):
        return dict(choices).get(value, str(value))
    return str(value)


def _safe_create_notification(**kwargs):
    """Create notification and log any error so production saves don't fail silently."""
    try:
        return create_notification(**kwargs)
    except Exception as e:
        logger.exception(
            "Notification create failed: %s (user=%s, account=%s, source_app=%s)",
            e, kwargs.get('user'), kwargs.get('account'), kwargs.get('source_app'),
        )
        return None


def _notify_watchers_for_change(
    *,
    account,
    source_app,
    title,
    message,
    action_url,
    target_type='',
    target_id=None,
    actor=None,
    exclude_users=None,
):
    """
    Notify company admin + any full_company_visibility users in the account
    when a record changes (status updated, approved, etc.).

    - Respects tenant scoping via account.
    - Respects per-app permissions via user_can_see_app_notifications.
    - Avoids duplicate notifications for users already notified explicitly
      (submitter, approver, etc.) via exclude_users.
    """
    if not account:
        return
    from .permissions import user_can_see_app_notifications

    exclude_ids = {
        getattr(u, 'id', None)
        for u in (exclude_users or [])
        if getattr(u, 'id', None) is not None
    }
    for user in get_company_admin_and_visibility_recipients(account):
        if user.id in exclude_ids:
            continue
        if not user_can_see_app_notifications(user, source_app, request=None):
            continue
        _safe_create_notification(
            user=user,
            account=account,
            source_app=source_app,
            title=title,
            message=message,
            actor=actor,
            action_url=action_url,
            target_type=target_type,
            target_id=target_id,
        )


# --- Messaging: new message ---
@receiver(post_save)
def on_message_created(sender, instance, created, **kwargs):
    if sender.__name__ != 'Message' or not created:
        return
    try:
        from apps.messaging.models import Message
        if sender is not Message:
            return
    except ImportError:
        return
    msg = instance
    if msg.is_deleted:
        return
    conv = msg.conversation
    if not conv or not conv.account_id:
        return
    preview = (msg.content or '(file)')[:80].replace('\n', ' ')
    sender_name = msg.sender.get_full_name() or msg.sender.email or 'Someone'
    title = 'New Message'
    message = f'{sender_name}: {preview}'
    action_url = f'/messaging/conversation/{conv.id}/'
    notify_conversation_members(
        conversation=conv,
        sender=msg.sender,
        title=title,
        message=message,
        action_url=action_url,
    )


# --- HR: LeaveRequest ---
@receiver(pre_save)
def _store_leave_status(sender, instance, **kwargs):
    try:
        from apps.hr_staff.models import LeaveRequest
        if sender is not LeaveRequest:
            return
    except ImportError:
        return
    if instance.pk:
        try:
            old = LeaveRequest.objects.get(pk=instance.pk)
            instance._prev_leave_status = old.status
        except LeaveRequest.DoesNotExist:
            instance._prev_leave_status = None
    else:
        instance._prev_leave_status = None


@receiver(post_save)
def on_leave_request_save(sender, instance, created, **kwargs):
    try:
        from apps.hr_staff.models import LeaveRequest
        if sender is not LeaveRequest:
            return
    except ImportError:
        return
    leave = instance
    account = leave.account
    if not account:
        return
    prev = getattr(leave, '_prev_leave_status', None)
    if created and leave.status == 'pending':
        # New leave request: notify HR users
        for user in get_hr_notification_recipients(account):
            if user.id != leave.created_by_id:
                _safe_create_notification(
                    user=user,
                    account=account,
                    source_app='hr_staff',
                    title='New Leave Request',
                    message=f'{leave.employee.full_name} has requested {leave.get_leave_type_display()} from {leave.start_date} to {leave.end_date}.',
                    actor=leave.created_by,
                    action_url=f'/hr-staff/leave/{leave.id}/',
                    target_type='leaverequest',
                    target_id=leave.id,
                )
    elif not created and prev != leave.status:
        # Any status change: notify employee if they have portal access
        emp = leave.employee
        if emp and emp.linked_user_id:
            try:
                status_display = dict(getattr(leave.__class__, 'STATUS_CHOICES', [])).get(leave.status, leave.status)
            except Exception:
                status_display = str(leave.status)
            _safe_create_notification(
                user=emp.linked_user,
                account=account,
                source_app='hr_staff',
                title='Leave Status Updated',
                message=f'Your {leave.get_leave_type_display()} request from {leave.start_date} to {leave.end_date} status is now {status_display}.',
                actor=None,
                action_url=f'/hr-staff/leave/{leave.id}/',
                target_type='leaverequest',
                target_id=leave.id,
            )


# --- HR: Employee created ---
@receiver(post_save)
def on_employee_created(sender, instance, created, **kwargs):
    try:
        from apps.hr_staff.models import Employee
        if sender is not Employee:
            return
    except ImportError:
        return
    if not created:
        return
    emp = instance
    account = emp.account
    if not account:
        return
    for user in get_hr_notification_recipients(account):
        if user.id != emp.created_by_id:
            dept = (emp.department.name if emp.department_id and emp.department else '—')
            _safe_create_notification(
                user=user,
                account=account,
                source_app='hr_staff',
                title='New Employee Added',
                message=f'{emp.full_name} has been added to {dept}.',
                actor=emp.created_by,
                action_url=f'/hr-staff/employees/{emp.id}/',
                target_type='employee',
                target_id=emp.id,
            )


# --- Requisition: any status change ---
@receiver(pre_save)
def _store_requisition_status(sender, instance, **kwargs):
    try:
        from apps.requisitions.models import Requisition
        if sender is not Requisition:
            return
    except ImportError:
        return
    if instance.pk:
        try:
            old = Requisition.objects.get(pk=instance.pk)
            instance._prev_req_status = old.status
        except Requisition.DoesNotExist:
            instance._prev_req_status = None
    else:
        instance._prev_req_status = None


@receiver(post_save)
def on_requisition_status_change(sender, instance, created, **kwargs):
    try:
        from apps.requisitions.models import Requisition
        if sender is not Requisition:
            return
    except ImportError:
        return
    req = instance
    account = _account_for_instance(req)
    if not account:
        return
    prev = getattr(req, '_prev_req_status', None)
    if prev == req.status:
        return
    status_display = _choice_display(getattr(Requisition, 'STATUS_CHOICES', []), req.status)
    submitter = _user_for_instance(req)
    if submitter:
        _safe_create_notification(
            user=submitter,
            account=account,
            source_app='requisitions',
            title='Requisition Status Updated',
            message=f'Requisition {req.reference_number} status is now {status_display}.',
            actor=req.approved_by,
            action_url=f'/requisitions/{req.pk}/',
            target_type='requisition',
            target_id=req.id,
        )
    approver = None
    if req.approved_by_id and req.approved_by_id != getattr(req, 'created_by_id', None):
        approver = req.approved_by
        _safe_create_notification(
            user=req.approved_by,
            account=account,
            source_app='requisitions',
            title='Requisition Status Updated',
            message=f'You set requisition {req.reference_number} to {status_display}.',
            actor=req.approved_by,
            action_url=f'/requisitions/{req.pk}/',
            target_type='requisition',
            target_id=req.id,
        )
    _notify_watchers_for_change(
        account=account,
        source_app='requisitions',
        title='Requisition Status Updated',
        message=f'Requisition {req.reference_number} status is now {status_display}.',
        action_url=f'/requisitions/{req.pk}/',
        target_type='requisition',
        target_id=req.id,
        actor=approver or submitter,
        exclude_users=[u for u in (submitter, approver) if u],
    )


# --- Inventory: approval status change ---
@receiver(pre_save)
def _store_inventory_approval(sender, instance, **kwargs):
    try:
        from apps.inventory.models import Inventory
        if sender is not Inventory:
            return
    except ImportError:
        return
    if instance.pk:
        try:
            old = Inventory.objects.get(pk=instance.pk)
            instance._prev_inv_approval = old.approval_status
        except Inventory.DoesNotExist:
            instance._prev_inv_approval = None
    else:
        instance._prev_inv_approval = None


@receiver(post_save)
def on_inventory_approval_change(sender, instance, created, **kwargs):
    try:
        from apps.inventory.models import Inventory
        if sender is not Inventory:
            return
    except ImportError:
        return
    inv = instance
    account = _account_for_instance(inv)
    if not account:
        return
    prev = getattr(inv, '_prev_inv_approval', None)
    if prev == inv.approval_status:
        return
    status_display = _choice_display(getattr(Inventory, 'APPROVAL_STATUS_CHOICES', []), inv.approval_status)
    ref = getattr(inv, 'transaction_id', inv.id)
    submitter = _user_for_instance(inv)
    if submitter:
        _safe_create_notification(
            user=submitter,
            account=account,
            source_app='inventory',
            title='Inventory Status Updated',
            message=f'Inventory record {ref} status is now {status_display}.',
            actor=inv.approved_by,
            action_url=f'/inventory/detail/{inv.pk}/',
            target_type='inventory',
            target_id=inv.id,
        )
    approver = None
    if inv.approved_by_id and inv.approved_by_id != getattr(inv, 'created_by_id', None):
        approver = inv.approved_by
        _safe_create_notification(
            user=inv.approved_by,
            account=account,
            source_app='inventory',
            title='Inventory Status Updated',
            message=f'You set inventory record {ref} to {status_display}.',
            actor=inv.approved_by,
            action_url=f'/inventory/detail/{inv.pk}/',
            target_type='inventory',
            target_id=inv.id,
        )
    _notify_watchers_for_change(
        account=account,
        source_app='inventory',
        title='Inventory Status Updated',
        message=f'Inventory record {ref} status is now {status_display}.',
        action_url=f'/inventory/detail/{inv.pk}/',
        target_type='inventory',
        target_id=inv.id,
        actor=approver or submitter,
        exclude_users=[u for u in (submitter, approver) if u],
    )


# --- Expense: status change to approved/rejected ---
@receiver(pre_save)
def _store_expense_status(sender, instance, **kwargs):
    try:
        from apps.expense.models import Expense
        if sender is not Expense:
            return
    except ImportError:
        return
    if instance.pk:
        try:
            old = Expense.objects.get(pk=instance.pk)
            instance._prev_exp_status = old.status
        except Expense.DoesNotExist:
            instance._prev_exp_status = None
    else:
        instance._prev_exp_status = None


@receiver(post_save)
def on_expense_status_change(sender, instance, created, **kwargs):
    try:
        from apps.expense.models import Expense
        if sender is not Expense:
            return
    except ImportError:
        return
    exp = instance
    account = _account_for_instance(exp)
    if not account:
        return
    prev = getattr(exp, '_prev_exp_status', None)
    if prev == exp.status:
        return
    status_display = _choice_display(getattr(Expense, 'STATUS_CHOICES', []), exp.status)
    ref = getattr(exp, 'transaction_id', exp.id)
    submitter = _user_for_instance(exp)
    if submitter:
        _safe_create_notification(
            user=submitter,
            account=account,
            source_app='expense',
            title='Expense Status Updated',
            message=f'Expense record {ref} status is now {status_display}.',
            actor=exp.approved_by,
            action_url=f'/expense/detail/{exp.pk}/',
            target_type='expense',
            target_id=exp.id,
        )
    approver = None
    if exp.approved_by_id and exp.approved_by_id != getattr(exp, 'created_by_id', None):
        approver = exp.approved_by
        _safe_create_notification(
            user=exp.approved_by,
            account=account,
            source_app='expense',
            title='Expense Status Updated',
            message=f'You set expense record {ref} to {status_display}.',
            actor=exp.approved_by,
            action_url=f'/expense/detail/{exp.pk}/',
            target_type='expense',
            target_id=exp.id,
        )
    _notify_watchers_for_change(
        account=account,
        source_app='expense',
        title='Expense Status Updated',
        message=f'Expense record {ref} status is now {status_display}.',
        action_url=f'/expense/detail/{exp.pk}/',
        target_type='expense',
        target_id=exp.id,
        actor=approver or submitter,
        exclude_users=[u for u in (submitter, approver) if u],
    )


# --- Job Orders: Product approval status change ---
@receiver(pre_save)
def _store_product_approval(sender, instance, **kwargs):
    try:
        from apps.job_orders.models import Product
        if sender is not Product:
            return
    except ImportError:
        return
    if instance.pk:
        try:
            old = Product.objects.get(pk=instance.pk)
            instance._prev_product_approval = old.approval_status
        except Product.DoesNotExist:
            instance._prev_product_approval = None
    else:
        instance._prev_product_approval = None


@receiver(post_save)
def on_product_approval_change(sender, instance, created, **kwargs):
    try:
        from apps.job_orders.models import Product
        if sender is not Product:
            return
    except ImportError:
        return
    prod = instance
    account = _account_for_instance(prod)
    if not account:
        return
    prev = getattr(prod, '_prev_product_approval', None)
    if prev == prod.approval_status:
        return
    status_display = _choice_display(getattr(Product, 'APPROVAL_CHOICES', []), prod.approval_status)
    job_ref = getattr(prod, 'job_order', None) or getattr(prod, 'submission_id', None) or f'#{prod.id}'
    job_ref_display = str(job_ref) if job_ref else f'#{prod.id}'
    submitter = _user_for_instance(prod)
    if submitter:
        _safe_create_notification(
            user=submitter,
            account=account,
            source_app='job_orders',
            title='Job Order Status Updated',
            message=f'Job order {job_ref_display} status is now {status_display}.',
            actor=prod.approved_by,
            action_url=f'/job-orders/{prod.pk}/',
            target_type='product',
            target_id=prod.id,
        )
    approver = None
    if prod.approved_by_id and prod.approved_by_id != getattr(prod, 'created_by_id', None):
        approver = prod.approved_by
        _safe_create_notification(
            user=prod.approved_by,
            account=account,
            source_app='job_orders',
            title='Job Order Status Updated',
            message=f'You set job order {job_ref_display} to {status_display}.',
            actor=prod.approved_by,
            action_url=f'/job-orders/{prod.pk}/',
            target_type='product',
            target_id=prod.id,
        )
    _notify_watchers_for_change(
        account=account,
        source_app='job_orders',
        title='Job Order Status Updated',
        message=f'Job order {job_ref_display} status is now {status_display}.',
        action_url=f'/job-orders/{prod.pk}/',
        target_type='product',
        target_id=prod.id,
        actor=approver or submitter,
        exclude_users=[u for u in (submitter, approver) if u],
    )


# --- Invoices: payment received (status changed to paid) ---
@receiver(pre_save)
def _store_invoice_status(sender, instance, **kwargs):
    try:
        from apps.invoices.models import Invoice
        if sender is not Invoice:
            return
    except ImportError:
        return
    if instance.pk:
        try:
            old = Invoice.objects.get(pk=instance.pk)
            instance._prev_invoice_status = old.status
        except Invoice.DoesNotExist:
            instance._prev_invoice_status = None
    else:
        instance._prev_invoice_status = None


@receiver(post_save)
def on_invoice_status_change(sender, instance, created, **kwargs):
    try:
        from apps.invoices.models import Invoice
        if sender is not Invoice:
            return
    except ImportError:
        return
    inv = instance
    account = _account_for_instance(inv)
    user = _user_for_instance(inv)
    if not account or not user:
        return
    prev = getattr(inv, '_prev_invoice_status', None)
    if prev == inv.status:
        return
    status_display = _choice_display(getattr(Invoice, 'STATUS_CHOICES', []), inv.status)
    _safe_create_notification(
        user=user,
        account=account,
        source_app='invoices',
        title='Invoice Status Updated',
        message=f'Invoice {inv.invoice_number} status is now {status_display}.',
        actor=None,
        action_url=f'/invoices/{inv.pk}/',
        target_type='invoice',
        target_id=inv.id,
    )
    _notify_watchers_for_change(
        account=account,
        source_app='invoices',
        title='Invoice Status Updated',
        message=f'Invoice {inv.invoice_number} status is now {status_display}.',
        action_url=f'/invoices/{inv.pk}/',
        target_type='invoice',
        target_id=inv.id,
        actor=None,
        exclude_users=[user],
    )


# --- Quotations: status change (sent, accepted) ---
@receiver(pre_save)
def _store_quotation_status(sender, instance, **kwargs):
    try:
        from apps.quotations.models import Quotation
        if sender is not Quotation:
            return
    except ImportError:
        return
    if instance.pk:
        try:
            old = Quotation.objects.get(pk=instance.pk)
            instance._prev_quotation_status = old.status
        except Quotation.DoesNotExist:
            instance._prev_quotation_status = None
    else:
        instance._prev_quotation_status = None


@receiver(post_save)
def on_quotation_status_change(sender, instance, created, **kwargs):
    try:
        from apps.quotations.models import Quotation
        if sender is not Quotation:
            return
    except ImportError:
        return
    quot = instance
    account = _account_for_instance(quot)
    user = _user_for_instance(quot)
    if not account or not user:
        return
    prev = getattr(quot, '_prev_quotation_status', None)
    if prev == quot.status:
        return
    status_display = _choice_display(getattr(Quotation, 'STATUS_CHOICES', []), quot.status)
    _safe_create_notification(
        user=user,
        account=account,
        source_app='quotations',
        title='Quotation Status Updated',
        message=f'Quotation {quot.quotation_number} status is now {status_display}.',
        actor=None,
        action_url=f'/quotations/{quot.pk}/',
        target_type='quotation',
        target_id=quot.id,
    )
    _notify_watchers_for_change(
        account=account,
        source_app='quotations',
        title='Quotation Status Updated',
        message=f'Quotation {quot.quotation_number} status is now {status_display}.',
        action_url=f'/quotations/{quot.pk}/',
        target_type='quotation',
        target_id=quot.id,
        actor=None,
        exclude_users=[user],
    )


# --- Quotations: converted to invoice ---
@receiver(pre_save)
def _store_quotation_converted(sender, instance, **kwargs):
    try:
        from apps.quotations.models import Quotation
        if sender is not Quotation:
            return
    except ImportError:
        return
    if instance.pk:
        try:
            old = Quotation.objects.get(pk=instance.pk)
            instance._prev_quotation_converted = bool(old.converted_invoice_id)
        except Quotation.DoesNotExist:
            instance._prev_quotation_converted = False
    else:
        instance._prev_quotation_converted = False


@receiver(post_save)
def on_quotation_converted(sender, instance, created, **kwargs):
    try:
        from apps.quotations.models import Quotation
        if sender is not Quotation:
            return
    except ImportError:
        return
    quot = instance
    account = _account_for_instance(quot)
    user = _user_for_instance(quot)
    if not account or not user:
        return
    prev = getattr(quot, '_prev_quotation_converted', False)
    if quot.converted_invoice_id and not prev:
        _safe_create_notification(
            user=user,
            account=account,
            source_app='quotations',
            title='Quotation Converted',
            message=f'Quotation {quot.quotation_number} has been converted to an invoice.',
            actor=None,
            action_url=f'/quotations/{quot.pk}/',
            target_type='quotation',
            target_id=quot.id,
        )
        _notify_watchers_for_change(
            account=account,
            source_app='quotations',
            title='Quotation Converted',
            message=f'Quotation {quot.quotation_number} has been converted to an invoice.',
            action_url=f'/quotations/{quot.pk}/',
            target_type='quotation',
            target_id=quot.id,
            actor=None,
            exclude_users=[user],
        )


# --- Waybills: status changed to delivered ---
@receiver(pre_save)
def _store_waybill_status(sender, instance, **kwargs):
    try:
        from apps.waybills.models import Waybill
        if sender is not Waybill:
            return
    except ImportError:
        return
    if instance.pk:
        try:
            old = Waybill.objects.get(pk=instance.pk)
            instance._prev_waybill_status = old.status
        except Waybill.DoesNotExist:
            instance._prev_waybill_status = None
    else:
        instance._prev_waybill_status = None


@receiver(post_save)
def on_waybill_delivered(sender, instance, created, **kwargs):
    try:
        from apps.waybills.models import Waybill
        if sender is not Waybill:
            return
    except ImportError:
        return
    wb = instance
    account = _account_for_instance(wb)
    user = _user_for_instance(wb)
    if not account or not user:
        return
    prev = getattr(wb, '_prev_waybill_status', None)
    if prev == wb.status:
        return
    status_display = _choice_display(getattr(Waybill, 'STATUS_CHOICES', []), wb.status)
    _safe_create_notification(
        user=user,
        account=account,
        source_app='waybills',
        title='Waybill Status Updated',
        message=f'Waybill {wb.waybill_number} status is now {status_display}.',
        actor=None,
        action_url=f'/waybills/{wb.pk}/',
        target_type='waybill',
        target_id=wb.id,
    )
    _notify_watchers_for_change(
        account=account,
        source_app='waybills',
        title='Waybill Status Updated',
        message=f'Waybill {wb.waybill_number} status is now {status_display}.',
        action_url=f'/waybills/{wb.pk}/',
        target_type='waybill',
        target_id=wb.id,
        actor=None,
        exclude_users=[user],
    )


# --- UserActivity: create/delete watcher notifications ---
@receiver(post_save)
def on_user_activity_create_delete(sender, instance, created, **kwargs):
    """
    When a CREATE or DELETE UserActivity row is logged for a business app,
    send watcher notifications to company admin + full-company-visibility users.

    This is driven entirely by the audit log, so it works for:
    - API and form submissions
    - Offline-queued requests that replay later
    """
    try:
        from apps.accounts.models import UserActivity as Activity
        if sender is not Activity:
            return
    except ImportError:
        return
    if not created:
        return
    activity = instance
    if activity.activity_type not in ('CREATE', 'DELETE'):
        return
    account = activity.account
    if not account:
        return
    app_name = (activity.app_name or '').lower().strip()
    source_app = ACTIVITY_APP_TO_SOURCE.get(app_name)
    if not source_app:
        return
    # Build a concise title/message
    model_name = (activity.model_name or '').strip() or 'Record'
    object_label = activity.object_repr or (f'#{activity.object_id}' if activity.object_id else '')
    verb = 'Created' if activity.activity_type == 'CREATE' else 'Deleted'
    # Human-readable actor
    actor_name = activity.actor_display or (getattr(activity.user, 'get_full_name', lambda: '')() or getattr(activity.user, 'email', '') or '').strip()
    # Build title and message with actor + timestamp context
    title = f'{model_name} {verb}'
    if object_label:
        base = f'{verb} {model_name} {object_label}'
    else:
        base = f'{verb} {model_name}'
    if actor_name:
        base += f' by {actor_name}'
    when_str = ''
    if getattr(activity, 'timestamp', None):
        try:
            when_str = activity.timestamp.strftime('%Y-%m-%d %I:%M %p')
        except Exception:
            when_str = str(activity.timestamp)
    if when_str:
        message = f'{base} on {when_str}.'
    else:
        message = base + '.'

    # For DELETE, deep-link to security activity detail so humans see
    # who deleted, when, IP address, session, and deleted fields.
    if activity.activity_type == 'DELETE':
        try:
            action_url = reverse('accounts:activity_detail', args=[activity.id])
        except Exception:
            action_url = activity.object_url or activity.url_path or ''
    else:
        # For CREATE, keep linking to the underlying record/page when possible.
        action_url = activity.object_url or activity.url_path or ''
    # Derive target_type / target_id for deep-link UIs
    target_type = (model_name or '').lower()
    target_id = None
    if activity.object_id:
        try:
            target_id = int(str(activity.object_id))
        except (TypeError, ValueError):
            target_id = None
    _notify_watchers_for_change(
        account=account,
        source_app=source_app,
        title=title,
        message=message,
        action_url=action_url,
        target_type=target_type,
        target_id=target_id,
        actor=activity.user,
        exclude_users=[],
    )
