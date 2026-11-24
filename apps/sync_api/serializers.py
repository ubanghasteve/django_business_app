"""
Sync API serializers for offline-first bulk create/update and changes.
Include uuid, updated_at, is_deleted; tenant is set server-side from request.user.
"""
from rest_framework import serializers
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
from apps.messaging.models import Conversation
from apps.notifications.models import Notification
from apps.core.models import CompanyProfile, BankAccount
from apps.core.ownership import get_account_for_user
from apps.core.utils import get_company_profile_for_user


class ClientSyncSerializer(serializers.ModelSerializer):
    """Client sync: uuid, updated_at, is_deleted + editable fields. Tenant (company) set in create()."""
    class Meta:
        model = Client
        fields = [
            'uuid', 'id', 'updated_at', 'is_deleted',
            'company', 'name', 'email', 'phone', 'address', 'contact_person', 'notes',
            'source_app', 'source_record_id', 'source_record_url', 'source_record_label', 'other_sources',
            'created_by', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']
        extra_kwargs = {'company': {'required': False}}

    def create(self, validated_data):
        request = self.context.get('request')
        if request and 'company' not in validated_data:
            company = get_company_profile_for_user(request.user, request)
            if company:
                validated_data['company'] = company
            validated_data.setdefault('created_by', request.user)
        return super().create(validated_data)


class InvoiceSyncSerializer(serializers.ModelSerializer):
    """Invoice sync: uuid, updated_at, is_deleted + key fields. Tenant (account) set in create()."""
    class Meta:
        model = Invoice
        fields = [
            'uuid', 'id', 'updated_at', 'is_deleted',
            'account', 'invoice_number', 'invoice_date', 'due_date', 'user', 'template',
            'client_name', 'client_phone', 'client_email', 'client_address',
            'subtotal', 'total_tax', 'tax_type', 'tax_value', 'total_discount', 'discount_type', 'discount_value',
            'shipping_fee', 'other_charges', 'grand_total', 'amount_paid', 'balance_due',
            'status', 'notes', 'show_bank_details', 'show_signature',
            'created_by', 'created_at',
        ]
        read_only_fields = ['id', 'invoice_number', 'created_at']
        extra_kwargs = {'account': {'required': False}}

    def create(self, validated_data):
        request = self.context.get('request')
        if request:
            if 'account' not in validated_data:
                account = get_account_for_user(request.user)
                if account:
                    validated_data['account'] = account
            validated_data.setdefault('created_by', request.user)
            validated_data.setdefault('user', request.user)
        return super().create(validated_data)


class RequisitionSyncSerializer(serializers.ModelSerializer):
    """Requisition sync: uuid, updated_at, is_deleted + editable fields. Tenant set in create()."""
    class Meta:
        model = Requisition
        fields = [
            'uuid', 'id', 'updated_at', 'is_deleted',
            'account', 'company', 'organization_name', 'address', 'contact_number', 'date',
            'job_type', 'print_product', 'quantity', 'colors', 'size', 'micron', 'other_info',
            'signature', 'status', 'reference_number',
            'created_by', 'approved_by', 'approved_at', 'created_at',
        ]
        read_only_fields = ['id', 'reference_number', 'created_at']
        extra_kwargs = {'account': {'required': False}, 'company': {'required': False}}

    def create(self, validated_data):
        request = self.context.get('request')
        if request:
            account = get_account_for_user(request.user)
            company = get_company_profile_for_user(request.user, request)
            if account and 'account' not in validated_data:
                validated_data['account'] = account
            if company and 'company' not in validated_data:
                validated_data['company'] = company
            validated_data.setdefault('created_by', request.user)
        return super().create(validated_data)


class ExpenseSyncSerializer(serializers.ModelSerializer):
    """Expense sync: uuid, updated_at, is_deleted + editable fields. Tenant set in create()."""
    class Meta:
        model = Expense
        fields = [
            'uuid', 'id', 'updated_at', 'is_deleted',
            'account', 'company', 'transaction_id', 'sn', 'expense_date', 'expense_category',
            'department', 'vendor', 'po_number', 'description',
            'product_id', 'product_name', 'product_category', 'product_description', 'unit_of_measurement',
            'quantity_purchased', 'quantity_out', 'unit_price', 'quantity_threshold',
            'subtotal', 'tax', 'discount', 'total_amount',
            'payment_method', 'payment_date', 'receipt_upload', 'status',
            'created_by', 'approved_by', 'approved_at', 'created_at',
        ]
        read_only_fields = ['id', 'transaction_id', 'sn', 'created_at']
        extra_kwargs = {'account': {'required': False}, 'company': {'required': False}}

    def create(self, validated_data):
        request = self.context.get('request')
        if request:
            account = get_account_for_user(request.user)
            company = get_company_profile_for_user(request.user, request)
            if account and 'account' not in validated_data:
                validated_data['account'] = account
            if company and 'company' not in validated_data:
                validated_data['company'] = company
            validated_data.setdefault('created_by', request.user)
        return super().create(validated_data)


class ReceiptSyncSerializer(serializers.ModelSerializer):
    """Receipt sync: uuid, updated_at, is_deleted; invoice resolved from invoice_uuid."""
    invoice_uuid = serializers.UUIDField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = Receipt
        fields = [
            'uuid', 'id', 'updated_at', 'is_deleted',
            'account', 'invoice', 'invoice_uuid', 'receipt_no', 'client_name', 'client_phone', 'client_address',
            'amount_received', 'amount_in_words', 'payment_method', 'transaction_id', 'received_by',
            'date_received', 'notes', 'balance_after_payment', 'refund_due', 'payment_type',
            'custom_color', 'show_bank_details', 'show_signature',
            'created_by', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']
        extra_kwargs = {'account': {'required': False}, 'invoice': {'required': False}}

    def _resolve_invoice(self, invoice_uuid, account):
        if not invoice_uuid or not account:
            return None
        return Invoice.objects.filter(account=account).filter(uuid=invoice_uuid).first()

    def create(self, validated_data):
        request = self.context.get('request')
        invoice_uuid = validated_data.pop('invoice_uuid', None)
        if request:
            account = get_account_for_user(request.user)
            if account and 'account' not in validated_data:
                validated_data['account'] = account
            if invoice_uuid and 'invoice' not in validated_data:
                inv = self._resolve_invoice(invoice_uuid, account)
                if inv:
                    validated_data['invoice'] = inv
            validated_data.setdefault('created_by', request.user)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop('invoice_uuid', None)
        return super().update(instance, validated_data)


class WaybillSyncSerializer(serializers.ModelSerializer):
    """Waybill sync: uuid, updated_at, is_deleted + key fields."""
    class Meta:
        model = Waybill
        fields = [
            'uuid', 'id', 'updated_at', 'is_deleted',
            'account', 'waybill_number', 'waybill_date', 'delivery_date', 'user', 'template',
            'custom_data', 'status', 'notes', 'created_by', 'created_at',
        ]
        read_only_fields = ['id', 'waybill_number', 'created_at']
        extra_kwargs = {'account': {'required': False}}

    def create(self, validated_data):
        request = self.context.get('request')
        if request:
            if 'account' not in validated_data:
                account = get_account_for_user(request.user)
                if account:
                    validated_data['account'] = account
            validated_data.setdefault('created_by', request.user)
            validated_data.setdefault('user', request.user)
        return super().create(validated_data)


class QuotationSyncSerializer(serializers.ModelSerializer):
    """Quotation sync: uuid, updated_at, is_deleted; client from client_uuid if needed."""
    client_uuid = serializers.UUIDField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = Quotation
        fields = [
            'uuid', 'id', 'updated_at', 'is_deleted',
            'account', 'quotation_number', 'quotation_date', 'valid_until', 'user', 'template', 'client', 'client_uuid',
            'subtotal', 'total_tax', 'tax_type', 'tax_value', 'total_discount', 'discount_type', 'discount_value',
            'shipping_fee', 'other_charges', 'grand_total', 'status', 'terms', 'notes',
            'converted_invoice', 'conversion_date', 'custom_fields',
            'created_by', 'created_at',
        ]
        read_only_fields = ['id', 'quotation_number', 'created_at']
        extra_kwargs = {'account': {'required': False}, 'client': {'required': False}}

    def create(self, validated_data):
        request = self.context.get('request')
        client_uuid = validated_data.pop('client_uuid', None)
        if request:
            account = get_account_for_user(request.user)
            if account and 'account' not in validated_data:
                validated_data['account'] = account
            if client_uuid and 'client' not in validated_data:
                from apps.clients.models import Client
                client = Client.objects.filter(company__account=account).filter(uuid=client_uuid).first()
                if client:
                    validated_data['client'] = client
            validated_data.setdefault('created_by', request.user)
            validated_data.setdefault('user', request.user)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop('client_uuid', None)
        return super().update(instance, validated_data)


class InventorySyncSerializer(serializers.ModelSerializer):
    """Inventory sync: uuid, updated_at, is_deleted + editable fields. Computed fields recalc on save."""
    class Meta:
        model = Inventory
        fields = [
            'uuid', 'id', 'updated_at', 'is_deleted',
            'account', 'company', 'transaction_id', 'sn', 'product_name', 'category', 'company_name',
            'vendor', 'stock_location', 'phone_number', 'quantity_in', 'quantity_out', 'unit_price',
            'total_amount', 'stock_balance_remaining', 'balance_quantity', 'low_stock_threshold',
            'stock_status', 'approval_status', 'workflow_status', 'remark',
            'created_by', 'approved_by', 'approved_at', 'created_at',
        ]
        read_only_fields = ['id', 'transaction_id', 'sn', 'created_at']
        extra_kwargs = {'account': {'required': False}, 'company': {'required': False}}

    def create(self, validated_data):
        request = self.context.get('request')
        if request:
            account = get_account_for_user(request.user)
            company = get_company_profile_for_user(request.user, request)
            if account and 'account' not in validated_data:
                validated_data['account'] = account
            if company and 'company' not in validated_data:
                validated_data['company'] = company
            validated_data.setdefault('created_by', request.user)
        return super().create(validated_data)


class ProductSyncSerializer(serializers.ModelSerializer):
    """Job order Product sync: uuid, updated_at, is_deleted + key fields."""
    class Meta:
        model = Product
        fields = [
            'uuid', 'id', 'updated_at', 'is_deleted',
            'account', 'name', 'category', 'job_order', 'submission_id', 'organization_name', 'address', 'contact_number',
            'treatment', 'cutting_length', 'flap', 'printing', 'print_product', 'colors', 'order_info', 'size', 'micron',
            'width', 'sealing_type', 'cutting', 'gusset', 'job_title', 'image', 'price', 'quantity', 'order_quantity', 'total',
            'date_created', 'job_order_date', 'estimated_delivery_date', 'actual_delivery_date', 'cycle_time',
            'production_status_date', 'approval_status', 'production_status',
            'created_by', 'approved_by', 'updated_by',
        ]
        read_only_fields = ['id', 'job_order', 'submission_id']
        extra_kwargs = {'account': {'required': False}}

    def create(self, validated_data):
        request = self.context.get('request')
        if request:
            if 'account' not in validated_data:
                account = get_account_for_user(request.user)
                if account:
                    validated_data['account'] = account
            validated_data.setdefault('created_by', request.user)
        return super().create(validated_data)


class EmployeeSyncSerializer(serializers.ModelSerializer):
    """HR Employee sync: uuid, updated_at, is_deleted + key fields."""
    class Meta:
        model = Employee
        fields = [
            'uuid', 'id', 'updated_at', 'is_deleted',
            'account', 'company', 'employee_id', 'first_name', 'last_name', 'department', 'position',
            'email', 'phone', 'profile_photo', 'status', 'date_joined', 'date_of_birth',
            'street_address', 'city', 'state_province', 'zip_code', 'monthly_salary', 'reporting_manager',
            'emergency_contact_name', 'emergency_contact_phone', 'created_by', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']
        extra_kwargs = {'account': {'required': False}, 'company': {'required': False}}

    def create(self, validated_data):
        request = self.context.get('request')
        if request:
            account = get_account_for_user(request.user)
            company = get_company_profile_for_user(request.user, request)
            if account and 'account' not in validated_data:
                validated_data['account'] = account
            if company and 'company' not in validated_data:
                validated_data['company'] = company
            validated_data.setdefault('created_by', request.user)
        return super().create(validated_data)


class DepartmentSyncSerializer(serializers.ModelSerializer):
    """HR Department sync: uuid, updated_at, is_deleted + key fields."""

    class Meta:
        model = Department
        fields = [
            'uuid', 'id', 'updated_at', 'is_deleted',
            'account', 'name', 'manager_name', 'budget',
            'created_by', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']
        extra_kwargs = {'account': {'required': False}}

    def create(self, validated_data):
        request = self.context.get('request')
        if request:
            account = get_account_for_user(request.user)
            if account and 'account' not in validated_data:
                validated_data['account'] = account
            validated_data.setdefault('created_by', request.user)
        return super().create(validated_data)


class LeaveSyncSerializer(serializers.ModelSerializer):
    """HR LeaveRequest sync: uuid, updated_at, is_deleted + key fields and status metadata."""

    class Meta:
        model = LeaveRequest
        fields = [
            'uuid', 'id', 'updated_at', 'is_deleted',
            'account', 'employee', 'leave_type', 'reason',
            'start_date', 'end_date', 'status',
            'supporting_document',
            'supervisor_manager', 'work_handover_to', 'handover_notes',
            'contact_number', 'address_during_leave',
            'emergency_contact_name', 'emergency_contact_phone',
            'created_by', 'created_at',
            'status_changed_by', 'status_changed_at',
        ]
        read_only_fields = ['id', 'created_at']
        extra_kwargs = {'account': {'required': False}}

    def create(self, validated_data):
        request = self.context.get('request')
        if request:
            account = get_account_for_user(request.user)
            if account and 'account' not in validated_data:
                validated_data['account'] = account
            validated_data.setdefault('created_by', request.user)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        # Mirror leave_update_status behaviour: track approver and timestamp when status changes.
        new_status = validated_data.get('status', instance.status)
        if new_status in ('approved', 'rejected') and new_status != instance.status:
            from django.utils import timezone
            request = self.context.get('request')
            if request:
                instance.status_changed_by = request.user
            instance.status_changed_at = timezone.now()
        return super().update(instance, validated_data)


class TransactionSyncSerializer(serializers.ModelSerializer):
    """Accounting Transaction sync: id is UUID (used as sync uuid), updated_at, is_deleted."""
    uuid = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Transaction
        fields = [
            'uuid', 'id', 'updated_at', 'is_deleted',
            'user', 'company', 'type', 'title', 'description', 'amount', 'currency',
            'tax', 'tax_type', 'tax_value', 'discount', 'discount_type', 'discount_value', 'net_amount',
            'source_app', 'reference_id', 'reference_model', 'transaction_date',
            'created_by', 'created_at', 'notes', 'is_reconciled', 'is_void',
        ]
        read_only_fields = ['created_at']
        extra_kwargs = {'company': {'required': False}}

    def get_uuid(self, obj):
        return str(obj.id)

    def create(self, validated_data):
        request = self.context.get('request')
        uuid_val = self.initial_data.get('uuid') if self.initial_data else None
        if uuid_val and 'id' not in validated_data:
            import uuid as uuid_mod
            try:
                validated_data['id'] = uuid_mod.UUID(str(uuid_val)) if isinstance(uuid_val, str) else uuid_val
            except (ValueError, TypeError):
                pass
        if request:
            company = get_company_profile_for_user(request.user, request)
            if company and 'company' not in validated_data:
                validated_data['company'] = company
            validated_data.setdefault('user', request.user)
            validated_data.setdefault('created_by', request.user)
        return super().create(validated_data)


class PayrollItemSyncSerializer(serializers.ModelSerializer):
    """PayrollItem sync: uuid, updated_at, is_deleted + key relations."""

    class Meta:
        model = PayrollItem
        fields = [
            "uuid",
            "id",
            "updated_at",
            "is_deleted",
            "account",
            "company",
            "payroll_run",
            "employee",
            "basic_salary",
            "allowances",
            "bonuses",
            "overtime",
            "gross_salary",
            "pension",
            "nhf",
            "tax",
            "loan_deduction",
            "salary_advance",
            "other_deductions",
            "net_salary",
            "total_work_days",
            "absent_days",
            "overtime_hours",
            "created_by",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
        extra_kwargs = {"account": {"required": False}, "company": {"required": False}}

    def create(self, validated_data):
        request = self.context.get("request")
        if request:
            account = get_account_for_user(request.user)
            company = get_company_profile_for_user(request.user, request)
            if account and "account" not in validated_data:
                validated_data["account"] = account
            if company and "company" not in validated_data:
                validated_data["company"] = company
            validated_data.setdefault("created_by", request.user)
        return super().create(validated_data)


class PayslipSyncSerializer(serializers.ModelSerializer):
    """Payslip sync: uuid, updated_at, is_deleted + key relations."""

    class Meta:
        model = Payslip
        fields = [
            "uuid",
            "id",
            "updated_at",
            "is_deleted",
            "account",
            "company",
            "payroll_item",
            "employee",
            "period",
            "pdf_file",
            "created_by",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
        extra_kwargs = {"account": {"required": False}, "company": {"required": False}}

    def create(self, validated_data):
        request = self.context.get("request")
        if request:
            account = get_account_for_user(request.user)
            company = get_company_profile_for_user(request.user, request)
            if account and "account" not in validated_data:
                validated_data["account"] = account
            if company and "company" not in validated_data:
                validated_data["company"] = company
            validated_data.setdefault("created_by", request.user)
        return super().create(validated_data)


class SalaryAdvanceSyncSerializer(serializers.ModelSerializer):
    """Salary Advance sync serializer."""
    class Meta:
        model = SalaryAdvance
        fields = ['uuid', 'id', 'updated_at', 'is_deleted', 'account', 'company', 'employee', 
                  'amount', 'reason', 'status', 'requested_by', 'created_at']
        read_only_fields = ['id', 'created_at']
        extra_kwargs = {'account': {'required': False}, 'company': {'required': False}}


class LoanSyncSerializer(serializers.ModelSerializer):
    """Loan sync serializer."""
    class Meta:
        model = EmployeeLoan
        fields = ['uuid', 'id', 'updated_at', 'is_deleted', 'account', 'company', 'employee',
                  'principal_amount', 'interest_rate', 'tenure_months', 'reason', 'status', 
                  'created_by', 'created_at']
        read_only_fields = ['id', 'created_at']
        extra_kwargs = {'account': {'required': False}, 'company': {'required': False}}


class BonusRuleSyncSerializer(serializers.ModelSerializer):
    """Bonus Rule sync serializer."""
    class Meta:
        model = BonusRule
        fields = ['uuid', 'id', 'updated_at', 'is_deleted', 'account', 'company',
                  'name', 'bonus_type', 'calculation_type', 'amount', 'percentage', 
                  'is_active', 'created_by', 'created_at']
        read_only_fields = ['id', 'created_at']
        extra_kwargs = {'account': {'required': False}, 'company': {'required': False}}


class AttendanceLogSyncSerializer(serializers.ModelSerializer):
    """Attendance Log sync serializer."""
    class Meta:
        model = AttendanceLog
        fields = ['uuid', 'id', 'updated_at', 'employee', 'device', 'punch_time', 
                  'punch_type', 'verify_mode', 'work_code', 'is_duplicate']
        read_only_fields = ['id']


class AttendanceEmployeeSyncSerializer(serializers.ModelSerializer):
    """Attendance Employee sync serializer."""
    class Meta:
        model = AttendanceEmployee
        fields = ['uuid', 'id', 'updated_at', 'tenant', 'hr_employee', 'employee_id',
                  'first_name', 'last_name', 'department', 'position', 'email', 'phone',
                  'biometric_uid', 'is_active', 'created_at']
        read_only_fields = ['id', 'created_at']
        extra_kwargs = {'tenant': {'required': False}}


class BiometricDeviceSyncSerializer(serializers.ModelSerializer):
    """Biometric Device sync serializer."""
    class Meta:
        model = BiometricDevice
        fields = ['uuid', 'id', 'updated_at', 'tenant', 'device_name', 'device_serial',
                  'device_ip', 'device_port', 'device_model', 'device_secret', 'location',
                  'status', 'last_seen']
        read_only_fields = ['id', 'last_seen']
        extra_kwargs = {'tenant': {'required': False}}


class DocumentSyncSerializer(serializers.ModelSerializer):
    """Document sync serializer."""
    class Meta:
        model = Document
        fields = ['uuid', 'id', 'updated_at', 'company', 'uploaded_by', 'file', 
                  'file_type', 'document_type', 'processing_status', 'processing_error',
                  'created_at']
        read_only_fields = ['id', 'created_at']
        extra_kwargs = {'company': {'required': False}}


class ConversationSyncSerializer(serializers.ModelSerializer):
    """Conversation sync serializer.

    Conversation has no SyncMixin (no uuid/updated_at/is_deleted); only real columns.
    """
    class Meta:
        model = Conversation
        fields = ['id', 'account', 'is_group', 'name', 'created_by', 'created_at']
        read_only_fields = ['id', 'created_at']
        extra_kwargs = {'account': {'required': False}}


class NotificationSyncSerializer(serializers.ModelSerializer):
    """Notification sync serializer.

    Notification has no SyncMixin (no uuid/updated_at/is_deleted); only real columns.
    """
    class Meta:
        model = Notification
        fields = [
            'id', 'user', 'account', 'source_app', 'title', 'message', 'actor',
            'action_url', 'target_type', 'target_id', 'is_read', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']
        extra_kwargs = {'account': {'required': False}}


class CompanyProfileSyncSerializer(serializers.ModelSerializer):
    """Company Profile sync serializer (no SyncMixin uuid on this model)."""
    class Meta:
        model = CompanyProfile
        fields = [
            'id', 'updated_at', 'account', 'user', 'company_name',
            'email', 'phone', 'website', 'address_line_1', 'address_line_2',
            'city', 'state', 'postal_code', 'country', 'business_type',
            'tax_id', 'registration_number', 'currency_code', 'currency_symbol',
        ]
        read_only_fields = ['id', 'updated_at']
        extra_kwargs = {'account': {'required': False}, 'user': {'required': False}}


class BankAccountSyncSerializer(serializers.ModelSerializer):
    """Bank Account sync serializer (no SyncMixin uuid on this model)."""
    class Meta:
        model = BankAccount
        fields = [
            'id', 'updated_at', 'company', 'bank_name', 'account_name',
            'account_number', 'account_type', 'routing_number', 'swift_code',
            'iban', 'is_default', 'is_active', 'created_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
        extra_kwargs = {'company': {'required': False}}
