"""
Offline-first sync API: bulk-create-update and changes endpoints.
Tenant-aware, RBAC-enforced, last-write-wins conflict resolution.
"""
import logging
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import JSONParser

from apps.core.ownership import (
    get_account_for_user,
    drf_filter_queryset_for_user,
)
from apps.core.utils import get_company_profile_for_user

from .serializers import (
    ClientSyncSerializer,
    InvoiceSyncSerializer,
    RequisitionSyncSerializer,
    ExpenseSyncSerializer,
    ReceiptSyncSerializer,
    WaybillSyncSerializer,
    QuotationSyncSerializer,
    InventorySyncSerializer,
    ProductSyncSerializer,
    EmployeeSyncSerializer,
    DepartmentSyncSerializer,
    LeaveSyncSerializer,
    TransactionSyncSerializer,
    PayrollItemSyncSerializer,
    PayslipSyncSerializer,
)
from apps.clients.models import Client
from apps.invoices.models import Invoice
from apps.requisitions.models import Requisition
from apps.expense.models import Expense
from apps.receipts.models import Receipt
from apps.waybills.models import Waybill
from apps.quotations.models import Quotation
from apps.inventory.models import Inventory
from apps.job_orders.models import Product
from apps.hr_staff.models import Department, Employee, LeaveRequest
from apps.accounting.models import Transaction
from apps.payroll.models import PayrollItem, Payslip, SalaryAdvance, EmployeeLoan, BonusRule
from apps.smart_attendance.models import AttendanceLog, Employee as AttendanceEmployee, BiometricDevice
from apps.documents.models import Document
from apps.messaging.models import Conversation, Message
from apps.notifications.models import Notification
from apps.core.models import CompanyProfile, BankAccount
from .serializers import (
    ClientSyncSerializer,
    InvoiceSyncSerializer,
    RequisitionSyncSerializer,
    ExpenseSyncSerializer,
    ReceiptSyncSerializer,
    WaybillSyncSerializer,
    QuotationSyncSerializer,
    InventorySyncSerializer,
    ProductSyncSerializer,
    EmployeeSyncSerializer,
    DepartmentSyncSerializer,
    LeaveSyncSerializer,
    TransactionSyncSerializer,
    PayrollItemSyncSerializer,
    PayslipSyncSerializer,
    SalaryAdvanceSyncSerializer,
    LoanSyncSerializer,
    BonusRuleSyncSerializer,
    AttendanceLogSyncSerializer,
    AttendanceEmployeeSyncSerializer,
    BiometricDeviceSyncSerializer,
    DocumentSyncSerializer,
    ConversationSyncSerializer,
    NotificationSyncSerializer,
    CompanyProfileSyncSerializer,
    BankAccountSyncSerializer,
)

logger = logging.getLogger(__name__)

# Per-model sync config: model, serializer class, account_lookup, view_perm, add_perm, change_perm
SYNC_MODELS = {
    'clients': {
        'model': Client,
        'serializer': ClientSyncSerializer,
        'account_lookup': 'company__account',
        'view_perm': 'clients.view_client',
        'add_perm': 'clients.add_client',
        'change_perm': 'clients.change_client',
    },
    'invoices': {
        'model': Invoice,
        'serializer': InvoiceSyncSerializer,
        'account_lookup': 'account',
        'view_perm': 'invoices.view_invoice',
        'add_perm': 'invoices.add_invoice',
        'change_perm': 'invoices.change_invoice',
    },
    'requisitions': {
        'model': Requisition,
        'serializer': RequisitionSyncSerializer,
        'account_lookup': 'account',
        'view_perm': 'requisitions.view_requisition',
        'add_perm': 'requisitions.add_requisition',
        'change_perm': 'requisitions.change_requisition',
    },
    'expense': {
        'model': Expense,
        'serializer': ExpenseSyncSerializer,
        'account_lookup': 'account',
        'view_perm': 'expense.view_expense',
        'add_perm': 'expense.add_expense',
        'change_perm': 'expense.change_expense',
    },
    'receipts': {
        'model': Receipt,
        'serializer': ReceiptSyncSerializer,
        'account_lookup': 'account',
        'view_perm': 'receipts.view_receipt',
        'add_perm': 'receipts.add_receipt',
        'change_perm': 'receipts.change_receipt',
    },
    'waybills': {
        'model': Waybill,
        'serializer': WaybillSyncSerializer,
        'account_lookup': 'account',
        'view_perm': 'waybills.view_waybill',
        'add_perm': 'waybills.add_waybill',
        'change_perm': 'waybills.change_waybill',
    },
    'quotations': {
        'model': Quotation,
        'serializer': QuotationSyncSerializer,
        'account_lookup': 'account',
        'view_perm': 'quotations.view_quotation',
        'add_perm': 'quotations.add_quotation',
        'change_perm': 'quotations.change_quotation',
    },
    'inventory': {
        'model': Inventory,
        'serializer': InventorySyncSerializer,
        'account_lookup': 'account',
        'view_perm': 'inventory.view_inventory',
        'add_perm': 'inventory.add_inventory',
        'change_perm': 'inventory.change_inventory',
    },
    'job_orders': {
        'model': Product,
        'serializer': ProductSyncSerializer,
        'account_lookup': 'account',
        'view_perm': 'job_orders.view_product',
        'add_perm': 'job_orders.add_product',
        'change_perm': 'job_orders.change_product',
    },
    'hr_staff': {
        'model': Employee,
        'serializer': EmployeeSyncSerializer,
        'account_lookup': 'account',
        'view_perm': 'hr_staff.view_employee',
        'add_perm': 'hr_staff.add_employee',
        'change_perm': 'hr_staff.change_employee',
    },
    'hr_departments': {
        'model': Department,
        'serializer': DepartmentSyncSerializer,
        'account_lookup': 'account',
        'view_perm': 'hr_staff.view_department',
        'add_perm': 'hr_staff.add_department',
        'change_perm': 'hr_staff.change_department',
    },
    'hr_leaves': {
        'model': LeaveRequest,
        'serializer': LeaveSyncSerializer,
        'account_lookup': 'account',
        'view_perm': 'hr_staff.view_leaverequest',
        'add_perm': 'hr_staff.add_leaverequest',
        'change_perm': 'hr_staff.change_leaverequest',
    },
    'accounting': {
        'model': Transaction,
        'serializer': TransactionSyncSerializer,
        'account_lookup': 'company__account',
        'uuid_attr': 'id',
        'view_perm': 'accounting.view_transaction',
        'add_perm': 'accounting.add_transaction',
        'change_perm': 'accounting.change_transaction',
    },
    'payroll_items': {
        'model': PayrollItem,
        'serializer': PayrollItemSyncSerializer,
        'account_lookup': 'company__account',
        'view_perm': 'payroll.view_payroll',
        'add_perm': 'payroll.create_payroll',
        'change_perm': 'payroll.edit_payroll',
    },
    'payslips': {
        'model': Payslip,
        'serializer': PayslipSyncSerializer,
        'account_lookup': 'company__account',
        'view_perm': 'payroll.view_payslip',
        'add_perm': 'payroll.generate_payslip',
        'change_perm': 'payroll.generate_payslip',
    },
    'salary_advances': {
        'model': SalaryAdvance,
        'serializer': SalaryAdvanceSyncSerializer,
        'account_lookup': 'company__account',
        'view_perm': 'payroll.view_salary_advance',
        'add_perm': 'payroll.add_salaryadvance',
        'change_perm': 'payroll.change_salaryadvance',
    },
    'loans': {
        'model': EmployeeLoan,
        'serializer': LoanSyncSerializer,
        'account_lookup': 'company__account',
        'view_perm': 'payroll.view_loan',
        'add_perm': 'payroll.add_loan',
        'change_perm': 'payroll.change_loan',
    },
    'bonuses': {
        'model': BonusRule,
        'serializer': BonusRuleSyncSerializer,
        'account_lookup': 'company__account',
        'view_perm': 'payroll.view_bonusrule',
        'add_perm': 'payroll.add_bonusrule',
        'change_perm': 'payroll.change_bonusrule',
    },
    'smart_attendance': {
        'model': AttendanceLog,
        'serializer': AttendanceLogSyncSerializer,
        'account_lookup': 'employee__tenant',
        'view_perm': 'smart_attendance.view_attendancelog',
        'add_perm': 'smart_attendance.add_attendancelog',
        'change_perm': 'smart_attendance.change_attendancelog',
    },
    'attendance_logs': {
        'model': AttendanceLog,
        'serializer': AttendanceLogSyncSerializer,
        'account_lookup': 'employee__tenant',
        'view_perm': 'smart_attendance.view_attendancelog',
        'add_perm': 'smart_attendance.add_attendancelog',
        'change_perm': 'smart_attendance.change_attendancelog',
    },
    'attendance_employees': {
        'model': AttendanceEmployee,
        'serializer': AttendanceEmployeeSyncSerializer,
        'account_lookup': 'tenant',
        'view_perm': 'smart_attendance.view_employee',
        'add_perm': 'smart_attendance.add_employee',
        'change_perm': 'smart_attendance.change_employee',
    },
    'attendance_devices': {
        'model': BiometricDevice,
        'serializer': BiometricDeviceSyncSerializer,
        'account_lookup': 'tenant',
        'view_perm': 'smart_attendance.view_biometricdevice',
        'add_perm': 'smart_attendance.add_biometricdevice',
        'change_perm': 'smart_attendance.change_biometricdevice',
    },
    'documents': {
        'model': Document,
        'serializer': DocumentSyncSerializer,
        'account_lookup': 'company__account',
        'view_perm': 'documents.view_document',
        'add_perm': 'documents.add_document',
        'change_perm': 'documents.change_document',
    },
    'messaging': {
        'model': Conversation,
        'serializer': ConversationSyncSerializer,
        'account_lookup': 'account',
        'view_perm': 'messaging.view_conversation',
        'add_perm': 'messaging.add_conversation',
        'change_perm': 'messaging.change_conversation',
    },
    'notifications': {
        'model': Notification,
        'serializer': NotificationSyncSerializer,
        'account_lookup': 'account',
        'view_perm': 'notifications.view_notification',
        'add_perm': 'notifications.add_notification',
        'change_perm': 'notifications.change_notification',
    },
    'core_company': {
        'model': CompanyProfile,
        'serializer': CompanyProfileSyncSerializer,
        'account_lookup': 'account',
        'view_perm': 'core.view_companyprofile',
        'add_perm': 'core.add_companyprofile',
        'change_perm': 'core.change_companyprofile',
    },
    'core_bank_accounts': {
        'model': BankAccount,
        'serializer': BankAccountSyncSerializer,
        'account_lookup': 'company__account',
        'view_perm': 'core.view_bankaccount',
        'add_perm': 'core.add_bankaccount',
        'change_perm': 'core.change_bankaccount',
    },
}


def _get_queryset_for_request(model, request, account_lookup):
    """Return tenant- and visibility-filtered queryset."""
    qs = model.objects.all()
    return drf_filter_queryset_for_user(qs, request, account_lookup=account_lookup)


def _confirm_object_tenant(object, request, account_lookup):
    """
    Phase 3 Step 13: Confirm object belongs to request.user's tenant. Reject cross-tenant.
    Returns True if object is in the current user's tenant, False otherwise.
    """
    account = get_account_for_user(request.user)
    if not account:
        return False
    if account_lookup == 'account':
        obj_account_id = getattr(object, 'account_id', None)
        return obj_account_id is not None and obj_account_id == account.pk
    # company__account
    company = getattr(object, 'company', None)
    if company is None:
        return False
    return getattr(company, 'account_id', None) == account.pk


def _strip_cross_tenant_fields(item, account_lookup, account):
    """
    Phase 3 Step 13: Remove or overwrite tenant fields from incoming payload so we never
    persist a cross-tenant write. Call before passing item to serializer.
    """
    item = dict(item)
    if account_lookup == 'account':
        item.pop('account', None)
        item.pop('account_id', None)
    else:
        item.pop('company', None)
        item.pop('company_id', None)
    return item


def _ensure_tenant_on_instance(instance, request, account_lookup, config):
    """Set account/company on instance from request.user if missing."""
    user = request.user
    account = get_account_for_user(user)
    if account_lookup == 'account':
        if not getattr(instance, 'account_id', None) and account:
            instance.account = account
    else:
        # company__account
        company = get_company_profile_for_user(user, request)
        if not getattr(instance, 'company_id', None) and company:
            instance.company = company
    if not getattr(instance, 'created_by_id', None):
        instance.created_by = user


class BulkCreateUpdateAPIView(APIView):
    """
    POST /api/v1/{model}/bulk-create-update/
    Body: { "items": [ { "uuid": "...", "updated_at": "ISO8601", ... }, ... ] }
    - If uuid exists in DB (within tenant) and user has change_perm: update only if incoming updated_at > existing (last-write-wins).
    - If uuid missing: create (user must have add_perm). Tenant set from request.user.
    Returns: { "success": [ {...} ], "failed": [ { "uuid": "...", "error": "..." } ] }

    Phase 3: Multi-tenant safety (confirm request.user.tenant and object.tenant); RBAC (view/add/change_perm
    checked before each save); duplicate protection (lookup by uuid within tenant, so sync retries never
    create duplicate records; model.uuid is unique).
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def get_config(self):
        """Override in subclass to return SYNC_MODELS[key]."""
        raise NotImplementedError

    def post(self, request, **kwargs):
        config = self.get_config()
        model = config['model']
        serializer_class = config['serializer']
        account_lookup = config['account_lookup']
        add_perm = config['add_perm']
        change_perm = config['change_perm']

        user = request.user
        if not user.has_perm(config['view_perm']):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        account = get_account_for_user(user)
        if not account:
            return Response({'detail': 'No tenant account.'}, status=status.HTTP_403_FORBIDDEN)

        payload = request.data
        if not isinstance(payload, dict) or 'items' not in payload:
            return Response({'detail': 'Expected {"items": [...]}.'}, status=status.HTTP_400_BAD_REQUEST)
        items = payload.get('items') or []
        if not isinstance(items, list):
            return Response({'detail': 'items must be a list.'}, status=status.HTTP_400_BAD_REQUEST)

        success_list = []
        failed_list = []
        qs = _get_queryset_for_request(model, request, account_lookup)

        key_attr = config.get('uuid_attr', 'uuid')
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                failed_list.append({'index': idx, 'error': 'Not an object.'})
                continue
            item_uuid = item.get('uuid')
            incoming_updated_at = item.get('updated_at')
            try:
                if item_uuid:
                    existing = qs.filter(**{key_attr: item_uuid}).first()
                    if existing:
                        # Phase 3 Step 13: Reject cross-tenant writes (defense in depth; qs is already tenant-scoped)
                        if not _confirm_object_tenant(existing, request, account_lookup):
                            failed_list.append({'uuid': str(item_uuid), 'error': 'Cross-tenant write rejected.'})
                            logger.warning('Sync bulk: cross-tenant reject %s uuid=%s', model.__name__, item_uuid)
                            continue
                        if not user.has_perm(change_perm):
                            failed_list.append({'uuid': str(item_uuid), 'error': 'No change permission.'})
                            logger.warning('Sync bulk: user %s denied change for %s uuid=%s', user.id, model.__name__, item_uuid)
                            continue
                        # Last-write-wins: only overwrite if incoming updated_at > existing.updated_at
                        existing_updated = getattr(existing, 'updated_at', None)
                        if existing_updated and incoming_updated_at:
                            from django.utils.dateparse import parse_datetime
                            inc_dt = parse_datetime(incoming_updated_at)
                            if inc_dt and inc_dt <= existing_updated:
                                logger.info(
                                    'Sync conflict: %s uuid=%s skipped (incoming updated_at %s <= existing %s)',
                                    model.__name__, item_uuid, incoming_updated_at, existing_updated,
                                )
                                success_list.append(serializer_class(existing, context={'request': request}).data)
                                continue
                        safe_item = _strip_cross_tenant_fields(item, account_lookup, account)
                        ser = serializer_class(existing, data=safe_item, partial=True, context={'request': request})
                        if ser.is_valid():
                            ser.save()
                            success_list.append(ser.data)
                            logger.info('Sync bulk: updated %s uuid=%s', model.__name__, item_uuid)
                        else:
                            failed_list.append({'uuid': str(item_uuid), 'error': ser.errors})
                    else:
                        existing_other = model.objects.filter(**{key_attr: item_uuid}).first()
                        if existing_other and not _confirm_object_tenant(existing_other, request, account_lookup):
                            failed_list.append({'uuid': str(item_uuid), 'error': 'Cross-tenant write rejected.'})
                            logger.warning('Sync bulk: cross-tenant reject (uuid exists in other tenant) %s uuid=%s', model.__name__, item_uuid)
                            continue
                        if not user.has_perm(add_perm):
                            failed_list.append({'uuid': str(item_uuid), 'error': 'No add permission.'})
                            continue
                        safe_item = _strip_cross_tenant_fields(item, account_lookup, account)
                        ser = serializer_class(data=safe_item, context={'request': request})
                        if ser.is_valid():
                            instance = ser.save()
                            _ensure_tenant_on_instance(instance, request, account_lookup, config)
                            if item_uuid and key_attr == 'uuid' and getattr(instance, 'uuid', None) != item_uuid:
                                try:
                                    from uuid import UUID
                                    setattr(instance, key_attr, UUID(str(item_uuid)) if isinstance(item_uuid, str) else item_uuid)
                                except (ValueError, TypeError):
                                    pass
                            instance.save()
                            success_list.append(serializer_class(instance, context={'request': request}).data)
                            logger.info('Sync bulk: created %s uuid=%s', model.__name__, item_uuid)
                        else:
                            failed_list.append({'uuid': str(item_uuid), 'error': ser.errors})
                else:
                    if not user.has_perm(add_perm):
                        failed_list.append({'index': idx, 'error': 'No add permission.'})
                        continue
                    safe_item = _strip_cross_tenant_fields(item, account_lookup, account)
                    ser = serializer_class(data=safe_item, context={'request': request})
                    if ser.is_valid():
                        instance = ser.save()
                        _ensure_tenant_on_instance(instance, request, account_lookup, config)
                        item_uuid_from_payload = item.get('uuid')
                        if item_uuid_from_payload and key_attr == 'uuid' and getattr(instance, 'uuid', None) != item_uuid_from_payload:
                            try:
                                from uuid import UUID
                                setattr(instance, key_attr, UUID(str(item_uuid_from_payload)) if isinstance(item_uuid_from_payload, str) else item_uuid_from_payload)
                                instance.save(update_fields=[key_attr])
                            except (ValueError, TypeError):
                                pass
                        instance.save()
                        success_list.append(serializer_class(instance, context={'request': request}).data)
                        logger.info('Sync bulk: created %s (new uuid=%s)', model.__name__, getattr(instance, 'uuid', None))
                    else:
                        failed_list.append({'index': idx, 'error': ser.errors})
            except Exception as e:
                logger.exception('Sync bulk: error for %s item: %s', model.__name__, e)
                failed_list.append({'uuid': str(item_uuid) if item_uuid else 'index=%s' % idx, 'error': str(e)})

        # Phase 3 Step 16: Log sync failure when any item failed
        if failed_list:
            logger.warning(
                'Sync bulk: %s failures for %s (success=%s)',
                len(failed_list), model.__name__, len(success_list),
            )
        return Response({'success': success_list, 'failed': failed_list}, status=status.HTTP_200_OK)


def _sync_timestamp_field(model):
    """Prefer updated_at (SyncMixin); fall back to created_at for models without it.

    Messaging/Notification (and similar) only have created_at. Using updated_at
    there caused 500s on /changes/ and did not affect invoice/receipt sync.
    """
    field_names = {f.name for f in model._meta.get_fields()}
    if 'updated_at' in field_names:
        return 'updated_at'
    if 'created_at' in field_names:
        return 'created_at'
    return None


class ChangesAPIView(APIView):
    """
    GET /api/v1/{model}/changes/?since=ISO8601
    Returns all records for the tenant with updated_at > since (or created_at
    when the model has no updated_at). SyncMixin models are unchanged.
    """
    permission_classes = [IsAuthenticated]

    def get_config(self):
        raise NotImplementedError

    def get(self, request, **kwargs):
        config = self.get_config()
        model = config['model']
        serializer_class = config['serializer']
        account_lookup = config['account_lookup']

        if not request.user.has_perm(config['view_perm']):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        account = get_account_for_user(request.user)
        if not account:
            return Response({'detail': 'No tenant account.'}, status=status.HTTP_403_FORBIDDEN)

        since_str = request.GET.get('since')
        if not since_str:
            return Response({'detail': 'Query parameter "since" (ISO8601) required.'}, status=status.HTTP_400_BAD_REQUEST)
        from django.utils.dateparse import parse_datetime
        since = parse_datetime(since_str)
        if not since:
            return Response({'detail': 'Invalid "since" datetime.'}, status=status.HTTP_400_BAD_REQUEST)

        ts_field = _sync_timestamp_field(model)
        if not ts_field:
            logger.warning(
                'Sync changes: %s has no updated_at/created_at; returning empty list',
                model.__name__,
            )
            return Response([], status=status.HTTP_200_OK)

        qs = _get_queryset_for_request(model, request, account_lookup)
        qs = qs.filter(**{f'{ts_field}__gt': since}).order_by(ts_field)
        try:
            data = serializer_class(qs, many=True, context={'request': request}).data
        except Exception:
            # Broken serializer/field mismatch must not 500 the whole poll loop.
            logger.exception('Sync changes serializer failed for %s; returning []', model.__name__)
            return Response([], status=status.HTTP_200_OK)
        logger.info('Sync changes: %s since=%s count=%s', model.__name__, since_str, len(data))
        return Response(data, status=status.HTTP_200_OK)


# Concrete view classes per model (config injected)
class ClientBulkCreateUpdateView(BulkCreateUpdateAPIView):
    def get_config(self):
        return SYNC_MODELS['clients']


class ClientChangesView(ChangesAPIView):
    def get_config(self):
        return SYNC_MODELS['clients']


class InvoiceBulkCreateUpdateView(BulkCreateUpdateAPIView):
    def get_config(self):
        return SYNC_MODELS['invoices']


class InvoiceChangesView(ChangesAPIView):
    def get_config(self):
        return SYNC_MODELS['invoices']


class RequisitionBulkCreateUpdateView(BulkCreateUpdateAPIView):
    def get_config(self):
        return SYNC_MODELS['requisitions']


class RequisitionChangesView(ChangesAPIView):
    def get_config(self):
        return SYNC_MODELS['requisitions']


class ExpenseBulkCreateUpdateView(BulkCreateUpdateAPIView):
    def get_config(self):
        return SYNC_MODELS['expense']


class ExpenseChangesView(ChangesAPIView):
    def get_config(self):
        return SYNC_MODELS['expense']


class ReceiptBulkCreateUpdateView(BulkCreateUpdateAPIView):
    def get_config(self):
        return SYNC_MODELS['receipts']


class ReceiptChangesView(ChangesAPIView):
    def get_config(self):
        return SYNC_MODELS['receipts']


class WaybillBulkCreateUpdateView(BulkCreateUpdateAPIView):
    def get_config(self):
        return SYNC_MODELS['waybills']


class WaybillChangesView(ChangesAPIView):
    def get_config(self):
        return SYNC_MODELS['waybills']


class QuotationBulkCreateUpdateView(BulkCreateUpdateAPIView):
    def get_config(self):
        return SYNC_MODELS['quotations']


class QuotationChangesView(ChangesAPIView):
    def get_config(self):
        return SYNC_MODELS['quotations']


class InventoryBulkCreateUpdateView(BulkCreateUpdateAPIView):
    def get_config(self):
        return SYNC_MODELS['inventory']


class InventoryChangesView(ChangesAPIView):
    def get_config(self):
        return SYNC_MODELS['inventory']


class JobOrderBulkCreateUpdateView(BulkCreateUpdateAPIView):
    def get_config(self):
        return SYNC_MODELS['job_orders']


class JobOrderChangesView(ChangesAPIView):
    def get_config(self):
        return SYNC_MODELS['job_orders']


class HrStaffBulkCreateUpdateView(BulkCreateUpdateAPIView):
    def get_config(self):
        return SYNC_MODELS['hr_staff']


class HrStaffChangesView(ChangesAPIView):
    def get_config(self):
        return SYNC_MODELS['hr_staff']


class AccountingBulkCreateUpdateView(BulkCreateUpdateAPIView):
    def get_config(self):
        return SYNC_MODELS['accounting']


class AccountingChangesView(ChangesAPIView):
    def get_config(self):
        return SYNC_MODELS['accounting']


class HrDepartmentsBulkCreateUpdateView(BulkCreateUpdateAPIView):
    def get_config(self):
        return SYNC_MODELS['hr_departments']


class HrDepartmentsChangesView(ChangesAPIView):
    def get_config(self):
        return SYNC_MODELS['hr_departments']


class HrLeavesBulkCreateUpdateView(BulkCreateUpdateAPIView):
    def get_config(self):
        return SYNC_MODELS['hr_leaves']


class HrLeavesChangesView(ChangesAPIView):
    def get_config(self):
        return SYNC_MODELS['hr_leaves']


class PayrollItemsBulkCreateUpdateView(BulkCreateUpdateAPIView):
    def get_config(self):
        return SYNC_MODELS['payroll_items']


class PayrollItemsChangesView(ChangesAPIView):
    def get_config(self):
        return SYNC_MODELS['payroll_items']


class PayslipsBulkCreateUpdateView(BulkCreateUpdateAPIView):
    def get_config(self):
        return SYNC_MODELS['payslips']


class PayslipsChangesView(ChangesAPIView):
    def get_config(self):
        return SYNC_MODELS['payslips']


# Salary Advances
class SalaryAdvancesBulkCreateUpdateView(BulkCreateUpdateAPIView):
    def get_config(self):
        return SYNC_MODELS['salary_advances']


class SalaryAdvancesChangesView(ChangesAPIView):
    def get_config(self):
        return SYNC_MODELS['salary_advances']


# Loans
class LoansBulkCreateUpdateView(BulkCreateUpdateAPIView):
    def get_config(self):
        return SYNC_MODELS['loans']


class LoansChangesView(ChangesAPIView):
    def get_config(self):
        return SYNC_MODELS['loans']


# Bonuses
class BonusesBulkCreateUpdateView(BulkCreateUpdateAPIView):
    def get_config(self):
        return SYNC_MODELS['bonuses']


class BonusesChangesView(ChangesAPIView):
    def get_config(self):
        return SYNC_MODELS['bonuses']


# Smart Attendance - Attendance Logs
class AttendanceLogsBulkCreateUpdateView(BulkCreateUpdateAPIView):
    def get_config(self):
        return SYNC_MODELS['attendance_logs']


class AttendanceLogsChangesView(ChangesAPIView):
    def get_config(self):
        return SYNC_MODELS['attendance_logs']


# Smart Attendance - Employees
class AttendanceEmployeesBulkCreateUpdateView(BulkCreateUpdateAPIView):
    def get_config(self):
        return SYNC_MODELS['attendance_employees']


class AttendanceEmployeesChangesView(ChangesAPIView):
    def get_config(self):
        return SYNC_MODELS['attendance_employees']


# Smart Attendance - Devices
class AttendanceDevicesBulkCreateUpdateView(BulkCreateUpdateAPIView):
    def get_config(self):
        return SYNC_MODELS['attendance_devices']


class AttendanceDevicesChangesView(ChangesAPIView):
    def get_config(self):
        return SYNC_MODELS['attendance_devices']


# Documents
class DocumentsBulkCreateUpdateView(BulkCreateUpdateAPIView):
    def get_config(self):
        return SYNC_MODELS['documents']


class DocumentsChangesView(ChangesAPIView):
    def get_config(self):
        return SYNC_MODELS['documents']


# Messaging
class MessagingBulkCreateUpdateView(BulkCreateUpdateAPIView):
    def get_config(self):
        return SYNC_MODELS['messaging']


class MessagingChangesView(ChangesAPIView):
    def get_config(self):
        return SYNC_MODELS['messaging']


# Notifications
class NotificationsBulkCreateUpdateView(BulkCreateUpdateAPIView):
    def get_config(self):
        return SYNC_MODELS['notifications']


class NotificationsChangesView(ChangesAPIView):
    def get_config(self):
        return SYNC_MODELS['notifications']


# Core - Company Profile
class CoreCompanyBulkCreateUpdateView(BulkCreateUpdateAPIView):
    def get_config(self):
        return SYNC_MODELS['core_company']


class CoreCompanyChangesView(ChangesAPIView):
    def get_config(self):
        return SYNC_MODELS['core_company']


# Core - Bank Accounts
class CoreBankAccountsBulkCreateUpdateView(BulkCreateUpdateAPIView):
    def get_config(self):
        return SYNC_MODELS['core_bank_accounts']


class CoreBankAccountsChangesView(ChangesAPIView):
    def get_config(self):
        return SYNC_MODELS['core_bank_accounts']
