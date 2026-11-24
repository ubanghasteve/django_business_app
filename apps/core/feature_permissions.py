"""
Feature → required permission(s) mapping for UI and backend consistency.

Use this module as the single source of truth for which permission(s) gate each feature.
Navigation (context_processors.rbac_context / navigation_context), views, and templates
should align with these definitions. A user must have at least one of the listed
permissions to see or access the feature.

Format: FEATURE_NAME -> tuple of permission codenames (app_label.codename).

REGRESSION SAFEGUARD: When adding new apps/features, define permissions here and use
them in navigation_context and @permission_required. Do not gate by is_staff or role names.
"""

NAV_CLIENTS = ('clients.view_client',)
NAV_INVOICES = ('invoices.view_invoice',)
NAV_QUOTATIONS = ('quotations.view_quotation',)
NAV_RECEIPTS = ('receipts.view_receipt',)
NAV_JOB_ORDERS = ('job_orders.view_product', 'job_orders.view_order')
NAV_JOB_ORDER_LAYOUTS = ('job_orders.view_jobordertemplate',)
JOB_ORDERS_PRINT = ('job_orders.print_product',)
JOB_ORDERS_DOWNLOAD = ('job_orders.download_product', 'job_orders.can_export_jobs', 'job_orders.can_export_products')
NAV_WAYBILLS = ('waybills.view_waybill',)
NAV_REQUISITIONS = ('requisitions.view_requisition',)
NAV_STAFF_OFFENCES = ('staff_offences.view_staffoffenceregister',)
NAV_STORE = ('store.view_store',)
NAV_INVENTORY = ('inventory.view_inventory',)
NAV_INVENTORY_TEMPLATES = ('inventory.view_inventory',)
NAV_EXPENSE = ('expense.view_expense',)
NAV_EXPENSES = ('expenses.view_expense',)
NAV_FINANCE_ENGINE = ('finance_engine.view_account', 'finance_engine.view_financialtransaction', 'finance_engine.view_journalentry')
NAV_ACCOUNTING = ('accounting.view_transaction',)
NAV_MESSAGING = ('messaging.view_conversation',)
NAV_MAILING = ('mailing.use_bulk_mailing',)
NAV_TEAM_AND_ROLES = ('accounts.view_subuser', 'accounts.view_accountgroup')
NAV_COMPANY_PROFILE = ('core.view_companyprofile', 'core.change_companyprofile')
NAV_ACTIVITY = ('accounts.view_useractivity', 'accounts.view_activity_log')
NAV_HR_STAFF = ('hr_staff.view_hr_dashboard', 'hr_staff.view_own_hr_dashboard')
NAV_SMART_ATTENDANCE = ('smart_attendance.view_attendance_dashboard',)
NAV_PAYROLL = ('payroll.view_payrollrecord', 'payroll.view_payroll')

NAV_DOCUMENTS = ('documents.view_document',)
NAV_NOTIFICATIONS = ('notifications.view_notification',)
NAV_REPORTS = ('reports.view_tax_report', 'documents.view_tax_report')
NAV_DASHBOARD = ('core.view_dashboard',)

NAV_HR_DEPARTMENTS = ('hr_staff.view_department',)
NAV_HR_EMPLOYEES = ('hr_staff.view_employee',)
NAV_HR_LEAVE = ('hr_staff.view_leaverequest',)
NAV_HR_LEAVE_POLICIES = ('hr_staff.view_leavepolicy',)
NAV_HR_ATTENDANCE = ('hr_staff.view_attendance',)
NAV_HR_PERFORMANCE = ('hr_staff.view_performancereview',)
NAV_HR_TRAINING = ('hr_staff.view_trainingcourse',)
NAV_HR_JOB_SEEKERS = ('hr_staff.view_jobseeker',)

NAV_ATTENDANCE_DEVICES = ('smart_attendance.view_biometricdevice',)
NAV_ATTENDANCE_LOGS = ('smart_attendance.view_attendancelog',)
NAV_ATTENDANCE_EMPLOYEES = ('smart_attendance.view_employee',)
NAV_ATTENDANCE_DAILY = ('smart_attendance.view_dailyattendance',)
NAV_ATTENDANCE_ANALYTICS = ('smart_attendance.view_attendanceanalytics',)

NAV_ACCOUNTING_TRANSACTIONS = ('accounting.view_transaction',)
NAV_ACCOUNTING_ACCOUNTS = ('accounting.view_account',)
NAV_ACCOUNTING_JOURNAL = ('accounting.view_journalentry',)
NAV_ACCOUNTING_REPORTS = ('accounting.view_financialreport',)
NAV_ACCOUNTING_CHART = ('accounting.view_chartofaccount',)

NAV_PAYROLL_RECORDS = ('payroll.view_payrollrecord',)
NAV_PAYROLL_CATEGORIES = ('payroll.view_payrollcategory',)
NAV_PAYROLL_LOGS = ('payroll.view_payrollrecordaccesslog',)
NAV_PAYROLL_SETTINGS = ('payroll.view_payrollsetting',)

NAV_VIDEO_CALLS = ('videocalls.view_videocallroom',)
NAV_MY_RECORDINGS = ('videocalls.view_callrecording',)
NAV_VIDEO_CALLS_CREATE = ('videocalls.add_videocallroom',)
NAV_VIDEO_CALLS_SCHEDULE = ('videocalls.add_scheduledmeeting',)
NAV_VIDEO_CALLS_RECORDINGS = ('videocalls.view_callrecording',)
NAV_VIDEO_CALLS_MANAGE = ('videocalls.change_videocallroom',)

NAV_INVOICE_TEMPLATES = ('invoices.view_invoicetemplate',)
NAV_QUOTATION_TEMPLATES = ('quotations.view_quotationtemplate',)
NAV_WAYBILL_TEMPLATES = ('waybills.view_waybilltemplate',)

NAV_CLIENTS_PRINT = ('clients.print_client',)
NAV_CLIENTS_DOWNLOAD = ('clients.download_client',)
NAV_INVOICES_PRINT = ('invoices.print_invoice',)
NAV_INVOICES_DOWNLOAD = ('invoices.download_invoice',)
NAV_INVOICES_APPROVE = ('invoices.can_approve_invoice',)
NAV_INVOICES_REPORT = ('invoices.view_invoice',)
NAV_RECEIPTS_PRINT = ('receipts.print_receipt',)
NAV_RECEIPTS_DOWNLOAD = ('receipts.download_receipt',)
NAV_QUOTATIONS_PRINT = ('quotations.print_quotation',)
NAV_QUOTATIONS_DOWNLOAD = ('quotations.download_quotation',)
NAV_WAYBILLS_PRINT = ('waybills.print_waybill',)
NAV_WAYBILLS_DOWNLOAD = ('waybills.download_waybill',)
NAV_WAYBILLS_APPROVE = ('waybills.can_approve_waybill',)
NAV_REQUISITIONS_PRINT = ('requisitions.print_requisition',)
NAV_REQUISITIONS_DOWNLOAD = ('requisitions.download_requisition',)
NAV_REQUISITIONS_APPROVE = ('requisitions.can_approve_requisition',)
NAV_STAFF_OFFENCES_PRINT = ('staff_offences.print_staffoffenceregister',)
NAV_STAFF_OFFENCES_DOWNLOAD = ('staff_offences.download_staffoffenceregister',)
NAV_STAFF_OFFENCES_ADD = ('staff_offences.add_staffoffenceregister',)
NAV_STAFF_OFFENCES_CHANGE = ('staff_offences.change_staffoffenceregister',)
NAV_STAFF_OFFENCES_DELETE = ('staff_offences.delete_staffoffenceregister',)
NAV_STAFF_OFFENCES_ADD_ENTRY = ('staff_offences.add_staffoffenceentry', 'staff_offences.change_staffoffenceregister')
NAV_STAFF_OFFENCES_CHANGE_ENTRY = ('staff_offences.change_staffoffenceentry', 'staff_offences.change_staffoffenceregister')
NAV_STAFF_OFFENCES_DELETE_ENTRY = ('staff_offences.delete_staffoffenceentry', 'staff_offences.change_staffoffenceregister')
NAV_STORE_PRINT = ('store.print_store',)
NAV_STORE_DOWNLOAD = ('store.download_store',)
NAV_STORE_APPROVE = ('store.can_approve_store',)
NAV_INVENTORY_PRINT = ('inventory.print_inventory',)
NAV_INVENTORY_DOWNLOAD = ('inventory.download_inventory',)
NAV_INVENTORY_APPROVE = ('inventory.can_approve_inventory',)
NAV_EXPENSE_PRINT = ('expense.print_expense',)
NAV_EXPENSE_DOWNLOAD = ('expense.download_expense',)
NAV_EXPENSE_APPROVE = ('expense.can_approve_expense',)

NAV_EXPENSES_EXPENSE = ('expenses.view_expense',)
NAV_EXPENSES_APPROVAL = ('expenses.view_expenseapproval',)
NAV_EXPENSES_CATEGORY = ('expenses.view_expensecategory',)
NAV_EXPENSES_REPORT = ('expenses.view_expensereport',)
NAV_EXPENSES_TEMPLATE = ('expenses.view_expensetemplate',)
NAV_EXPENSES_ATTACHMENT = ('expenses.view_expenseattachment',)

NAV_FINANCE_ACCOUNTS = ('finance_engine.view_account',)
NAV_FINANCE_TRANSACTIONS = ('finance_engine.view_financialtransaction',)
NAV_FINANCE_JOURNAL = ('finance_engine.view_journalentry',)
NAV_FINANCE_LINES = ('finance_engine.view_journalline',)

NAV_DOCUMENTS_PROCESS = ('documents.process_document',)
NAV_DOCUMENTS_DOWNLOAD = ('documents.download_document',)
NAV_DOCUMENTS_TAX_REPORTS = ('documents.view_tax_report',)

NAV_TEAM_VIEW = ('accounts.view_subuser',)
NAV_TEAM_CREATE = ('accounts.add_subuser',)
NAV_TEAM_EDIT = ('accounts.change_subuser',)
NAV_TEAM_DELETE = ('accounts.delete_subuser',)
NAV_ROLES_VIEW = ('accounts.view_accountgroup',)
NAV_ROLES_CREATE = ('accounts.add_accountgroup',)
NAV_ROLES_EDIT = ('accounts.change_accountgroup',)
NAV_ROLES_DELETE = ('accounts.delete_accountgroup',)
NAV_SESSIONS_VIEW = ('accounts.view_usersession',)
NAV_SESSIONS_MANAGE = ('accounts.change_usersession',)

ELEVATED_PERMISSIONS = (
    *NAV_CLIENTS, *NAV_INVOICES, *NAV_QUOTATIONS, *NAV_RECEIPTS,
    *NAV_JOB_ORDERS, *NAV_JOB_ORDER_LAYOUTS, *NAV_WAYBILLS, *NAV_REQUISITIONS,
    *NAV_STAFF_OFFENCES, *NAV_STORE,
    *NAV_INVENTORY, *NAV_INVENTORY_TEMPLATES, *NAV_EXPENSE, *NAV_EXPENSES,
    *NAV_FINANCE_ENGINE, *NAV_ACCOUNTING,
    *NAV_MESSAGING, *NAV_MAILING, *NAV_TEAM_AND_ROLES, *NAV_ACTIVITY, *NAV_HR_STAFF,
    *NAV_SMART_ATTENDANCE, *NAV_PAYROLL, *NAV_DOCUMENTS, *NAV_NOTIFICATIONS,
    *NAV_REPORTS, *NAV_DASHBOARD, *NAV_VIDEO_CALLS, *NAV_MY_RECORDINGS,
)

NAV_APP_PERMISSIONS = {
    'clients': NAV_CLIENTS,
    'invoices': NAV_INVOICES,
    'quotations': NAV_QUOTATIONS,
    'receipts': NAV_RECEIPTS,
    'job_orders': NAV_JOB_ORDERS,
    'job_order_layouts': NAV_JOB_ORDER_LAYOUTS,
    'waybills': NAV_WAYBILLS,
    'requisitions': NAV_REQUISITIONS,
    'staff_offences': NAV_STAFF_OFFENCES,
    'store': NAV_STORE,
    'inventory': NAV_INVENTORY,
    'inventory_templates': NAV_INVENTORY_TEMPLATES,
    'expense': NAV_EXPENSE,
    'expenses': NAV_EXPENSES,
    'finance_engine': NAV_FINANCE_ENGINE,
    'accounting': NAV_ACCOUNTING,
    'messaging': NAV_MESSAGING,
    'mailing': NAV_MAILING,
    'team_and_roles': NAV_TEAM_AND_ROLES,
    'company_profile': NAV_COMPANY_PROFILE,
    'activity': NAV_ACTIVITY,
    'hr_staff': NAV_HR_STAFF,
    'smart_attendance': NAV_SMART_ATTENDANCE,
    'payroll': NAV_PAYROLL,
    'documents': NAV_DOCUMENTS,
    'notifications': NAV_NOTIFICATIONS,
    'reports': NAV_REPORTS,
    'dashboard': NAV_DASHBOARD,
    'video_calls': NAV_VIDEO_CALLS,
    'my_recordings': NAV_MY_RECORDINGS,
}

FEATURE_PERMISSIONS = {
    'clients.view': NAV_CLIENTS,
    'clients.print': NAV_CLIENTS_PRINT,
    'clients.download': NAV_CLIENTS_DOWNLOAD,
    'invoices.view': NAV_INVOICES,
    'invoices.print': NAV_INVOICES_PRINT,
    'invoices.download': NAV_INVOICES_DOWNLOAD,
    'invoices.approve': NAV_INVOICES_APPROVE,
    'invoices.report': NAV_INVOICES_REPORT,
    'invoices.templates': NAV_INVOICE_TEMPLATES,
    'quotations.view': NAV_QUOTATIONS,
    'quotations.print': NAV_QUOTATIONS_PRINT,
    'quotations.download': NAV_QUOTATIONS_DOWNLOAD,
    'quotations.templates': NAV_QUOTATION_TEMPLATES,
    'receipts.view': NAV_RECEIPTS,
    'receipts.print': NAV_RECEIPTS_PRINT,
    'receipts.download': NAV_RECEIPTS_DOWNLOAD,
    'job_orders.view': NAV_JOB_ORDERS,
    'job_orders.print': JOB_ORDERS_PRINT,
    'job_orders.download': JOB_ORDERS_DOWNLOAD,
    'job_orders.templates': NAV_JOB_ORDER_LAYOUTS,
    'waybills.view': NAV_WAYBILLS,
    'waybills.print': NAV_WAYBILLS_PRINT,
    'waybills.download': NAV_WAYBILLS_DOWNLOAD,
    'waybills.approve': NAV_WAYBILLS_APPROVE,
    'waybills.templates': NAV_WAYBILL_TEMPLATES,
    'requisitions.view': NAV_REQUISITIONS,
    'requisitions.print': NAV_REQUISITIONS_PRINT,
    'requisitions.download': NAV_REQUISITIONS_DOWNLOAD,
    'requisitions.approve': NAV_REQUISITIONS_APPROVE,
    'staff_offences.view': NAV_STAFF_OFFENCES,
    'staff_offences.print': NAV_STAFF_OFFENCES_PRINT,
    'staff_offences.download': NAV_STAFF_OFFENCES_DOWNLOAD,
    'staff_offences.add': NAV_STAFF_OFFENCES_ADD,
    'staff_offences.change': NAV_STAFF_OFFENCES_CHANGE,
    'staff_offences.delete': NAV_STAFF_OFFENCES_DELETE,
    'staff_offences.add_entry': NAV_STAFF_OFFENCES_ADD_ENTRY,
    'staff_offences.change_entry': NAV_STAFF_OFFENCES_CHANGE_ENTRY,
    'staff_offences.delete_entry': NAV_STAFF_OFFENCES_DELETE_ENTRY,
    'store.view': NAV_STORE,
    'store.print': NAV_STORE_PRINT,
    'store.download': NAV_STORE_DOWNLOAD,
    'store.approve': NAV_STORE_APPROVE,
    'inventory.view': NAV_INVENTORY,
    'inventory.print': NAV_INVENTORY_PRINT,
    'inventory.download': NAV_INVENTORY_DOWNLOAD,
    'inventory.approve': NAV_INVENTORY_APPROVE,
    'expense.view': NAV_EXPENSE,
    'expense.print': NAV_EXPENSE_PRINT,
    'expense.download': NAV_EXPENSE_DOWNLOAD,
    'expense.approve': NAV_EXPENSE_APPROVE,
    'expenses.view': NAV_EXPENSES_EXPENSE,
    'expenses.approval': NAV_EXPENSES_APPROVAL,
    'expenses.category': NAV_EXPENSES_CATEGORY,
    'expenses.report': NAV_EXPENSES_REPORT,
    'expenses.template': NAV_EXPENSES_TEMPLATE,
    'expenses.attachment': NAV_EXPENSES_ATTACHMENT,
    'finance_engine.view': NAV_FINANCE_ENGINE,
    'finance_engine.accounts': NAV_FINANCE_ACCOUNTS,
    'finance_engine.transactions': NAV_FINANCE_TRANSACTIONS,
    'finance_engine.journal': NAV_FINANCE_JOURNAL,
    'finance_engine.lines': NAV_FINANCE_LINES,
    'accounting.view': NAV_ACCOUNTING,
    'accounting.transactions': NAV_ACCOUNTING_TRANSACTIONS,
    'accounting.accounts': NAV_ACCOUNTING_ACCOUNTS,
    'accounting.journal': NAV_ACCOUNTING_JOURNAL,
    'accounting.reports': NAV_ACCOUNTING_REPORTS,
    'accounting.chart': NAV_ACCOUNTING_CHART,
    'messaging.view': NAV_MESSAGING,
    'mailing.use': NAV_MAILING,
    'hr_staff.view': NAV_HR_STAFF,
    'hr_staff.departments': NAV_HR_DEPARTMENTS,
    'hr_staff.employees': NAV_HR_EMPLOYEES,
    'hr_staff.leave': NAV_HR_LEAVE,
    'hr_staff.leave_policies': NAV_HR_LEAVE_POLICIES,
    'hr_staff.attendance': NAV_HR_ATTENDANCE,
    'hr_staff.performance': NAV_HR_PERFORMANCE,
    'hr_staff.training': NAV_HR_TRAINING,
    'hr_staff.job_seekers': NAV_HR_JOB_SEEKERS,
    'payroll.view': NAV_PAYROLL,
    'payroll.records': NAV_PAYROLL_RECORDS,
    'payroll.categories': NAV_PAYROLL_CATEGORIES,
    'payroll.logs': NAV_PAYROLL_LOGS,
    'payroll.settings': NAV_PAYROLL_SETTINGS,
    'smart_attendance.view': NAV_SMART_ATTENDANCE,
    'smart_attendance.devices': NAV_ATTENDANCE_DEVICES,
    'smart_attendance.logs': NAV_ATTENDANCE_LOGS,
    'smart_attendance.employees': NAV_ATTENDANCE_EMPLOYEES,
    'smart_attendance.daily': NAV_ATTENDANCE_DAILY,
    'smart_attendance.analytics': NAV_ATTENDANCE_ANALYTICS,
    'documents.view': NAV_DOCUMENTS,
    'documents.process': NAV_DOCUMENTS_PROCESS,
    'documents.download': NAV_DOCUMENTS_DOWNLOAD,
    'documents.tax_reports': NAV_DOCUMENTS_TAX_REPORTS,
    'notifications.view': NAV_NOTIFICATIONS,
    'reports.view': NAV_REPORTS,
    'dashboard.view': NAV_DASHBOARD,
    'company_profile.view': NAV_COMPANY_PROFILE,
    'team.view': NAV_TEAM_VIEW,
    'team.create': NAV_TEAM_CREATE,
    'team.edit': NAV_TEAM_EDIT,
    'team.delete': NAV_TEAM_DELETE,
    'roles.view': NAV_ROLES_VIEW,
    'roles.create': NAV_ROLES_CREATE,
    'roles.edit': NAV_ROLES_EDIT,
    'roles.delete': NAV_ROLES_DELETE,
    'sessions.view': NAV_SESSIONS_VIEW,
    'sessions.manage': NAV_SESSIONS_MANAGE,
    'video_calls.view': NAV_VIDEO_CALLS,
    'video_calls.create': NAV_VIDEO_CALLS_CREATE,
    'video_calls.schedule': NAV_VIDEO_CALLS_SCHEDULE,
    'video_calls.recordings': NAV_VIDEO_CALLS_RECORDINGS,
    'video_calls.manage': NAV_VIDEO_CALLS_MANAGE,
    'my_recordings.view': NAV_MY_RECORDINGS,
}


def get_feature_permissions(feature_name):
    """
    Get the permissions required for a given feature.
    Returns a tuple of permission codenames, or an empty tuple if not found.
    """
    return FEATURE_PERMISSIONS.get(feature_name, ())


def has_feature_permission(user, feature_name):
    """
    Check if a user has any of the permissions required for a feature.
    """
    perms = get_feature_permissions(feature_name)
    if not perms:
        return False
    return any(user.has_perm(p) for p in perms)


def get_nav_permissions_for_user(user):
    """
    Get all navigation items a user can access based on their permissions.
    Returns a dict of nav_key -> boolean (True if user has access).
    """
    result = {}
    for nav_key, perms in NAV_APP_PERMISSIONS.items():
        result[nav_key] = any(user.has_perm(p) for p in perms) if perms else False
    return result
