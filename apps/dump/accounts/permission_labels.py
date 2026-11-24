"""
Human-readable labels for permissions displayed on Role Create/Edit pages.

Database permission codenames are NEVER changed; this mapping is for display only.
Format: "app_label.codename" -> "User-friendly label".
"""

# Display order and module names for grouping on role form
PERMISSION_MODULE_ORDER = [
    "job_orders",
    "invoices",
    "receipts",
    "quotations",
    "waybills",
    "requisitions",
    "inventory",
    "expense",
    "clients",
    "accounting",
    "messaging",
    "mailing",
    "hr_staff",
    "smart_attendance",
    "core",
    "accounts",
    "auth",
]

PERMISSION_MODULE_LABELS = {
    "job_orders": "Job Orders",
    "invoices": "Invoices",
    "receipts": "Receipts",
    "quotations": "Quotations",
    "waybills": "Waybills",
    "requisitions": "Requisitions",
    "inventory": "Inventory",
    "expense": "Expense",
    "clients": "Clients",
    "accounting": "Accounting",
    "messaging": "Messaging",
    "mailing": "Bulk Mailing",
    "hr_staff": "HR & Staff",
    "smart_attendance": "Smart Attendance",
    "core": "Company",
    "accounts": "Security & Users",
    "auth": "Roles & Permissions",
}

PERMISSION_LABELS = {
    # Job Orders
    "job_orders.view_product": "View Job Orders",
    "job_orders.add_product": "Create Job Orders",
    "job_orders.change_product": "Edit Job Orders",
    "job_orders.delete_product": "Delete Job Orders",
    "job_orders.view_order": "View Orders",
    "job_orders.add_order": "Create Orders",
    "job_orders.change_order": "Edit Orders",
    "job_orders.delete_order": "Delete Orders",
    "job_orders.view_jobordertemplate": "View Job Order Templates / Layouts",
    "job_orders.print_product": "Print Job Orders",
    "job_orders.download_product": "Download / Export Job Orders",
    "job_orders.can_approve_jobs": "Approve Job Orders",
    "job_orders.can_view_all_jobs": "View All Job Orders",
    "job_orders.can_export_jobs": "Export Job Orders",
    "job_orders.can_manage_production": "Manage Production Status",
    "job_orders.view_dashboard": "View Job Order Dashboard",
    "job_orders.manage_leave": "Manage Leave Requests",
    "job_orders.can_export_products": "Export Products",
    "job_orders.can_export_leaves": "Export Leaves",
    # Invoices
    "invoices.view_invoice": "View Invoices",
    "invoices.add_invoice": "Create Invoices",
    "invoices.change_invoice": "Edit Invoices",
    "invoices.delete_invoice": "Delete Invoices",
    "invoices.print_invoice": "Print Invoices",
    "invoices.download_invoice": "Download / Export Invoices",
    "invoices.can_approve_invoice": "Approve Invoices",
    "invoices.view_invoicetemplate": "View Invoice Templates",
    "invoices.add_invoicetemplate": "Create Invoice Templates",
    "invoices.change_invoicetemplate": "Edit Invoice Templates",
    "invoices.delete_invoicetemplate": "Delete Invoice Templates",
    # Receipts
    "receipts.view_receipt": "View Receipts",
    "receipts.add_receipt": "Create Receipts",
    "receipts.change_receipt": "Edit Receipts",
    "receipts.delete_receipt": "Delete Receipts",
    "receipts.print_receipt": "Print Receipts",
    "receipts.download_receipt": "Download / Export Receipts",
    # Quotations
    "quotations.view_quotation": "View Quotations",
    "quotations.add_quotation": "Create Quotations",
    "quotations.change_quotation": "Edit Quotations",
    "quotations.delete_quotation": "Delete Quotations",
    "quotations.print_quotation": "Print Quotations",
    "quotations.download_quotation": "Download / Export Quotations",
    # Waybills
    "waybills.view_waybill": "View Waybills",
    "waybills.add_waybill": "Create Waybills",
    "waybills.change_waybill": "Edit Waybills",
    "waybills.delete_waybill": "Delete Waybills",
    "waybills.print_waybill": "Print Waybills",
    "waybills.download_waybill": "Download / Export Waybills",
    "waybills.can_approve_waybill": "Approve Waybills",
    # Requisitions
    "requisitions.view_requisition": "View Requisitions",
    "requisitions.add_requisition": "Create Requisitions",
    "requisitions.change_requisition": "Edit Requisitions",
    "requisitions.delete_requisition": "Delete Requisitions",
    "requisitions.print_requisition": "Print Requisitions",
    "requisitions.download_requisition": "Download / Export Requisitions",
    "requisitions.can_approve_requisition": "Approve Requisitions",
    # Inventory
    "inventory.view_inventory": "View Inventory",
    "inventory.add_inventory": "Create Inventory",
    "inventory.change_inventory": "Edit Inventory",
    "inventory.delete_inventory": "Delete Inventory",
    "inventory.print_inventory": "Print Inventory",
    "inventory.download_inventory": "Download Inventory",
    "inventory.can_approve_inventory": "Approve Inventory Records",
    # Expense
    "expense.view_expense": "View Expense",
    "expense.add_expense": "Create Expense",
    "expense.change_expense": "Edit Expense",
    "expense.delete_expense": "Delete Expense",
    "expense.print_expense": "Print Expense",
    "expense.download_expense": "Download Expense",
    "expense.can_approve_expense": "Approve Expense Records",
    # HR & Staff
    "hr_staff.view_department": "View Departments",
    "hr_staff.add_department": "Create Departments",
    "hr_staff.change_department": "Edit Departments",
    "hr_staff.delete_department": "Delete Departments",
    "hr_staff.view_hr_dashboard": "View HR dashboard",
    "hr_staff.view_own_hr_dashboard": "View own HR dashboard",
    "hr_staff.view_employee": "View Employees",
    "hr_staff.add_employee": "Create Employees",
    "hr_staff.change_employee": "Edit Employees",
    "hr_staff.delete_employee": "Delete Employees",
    "hr_staff.view_leaverequest": "View Leave Requests",
    "hr_staff.add_leaverequest": "Create Leave Requests",
    "hr_staff.change_leaverequest": "Edit Leave Requests",
    "hr_staff.delete_leaverequest": "Delete Leave Requests",
    "hr_staff.create_employee_account": "Create employee portal account",
    "hr_staff.reset_employee_password": "Reset employee password",
    "hr_staff.view_employee_activity": "View employee activity",
    # Smart Attendance
    "smart_attendance.view_employee": "View Attendance Employees",
    "smart_attendance.add_employee": "Create Attendance Employees",
    "smart_attendance.change_employee": "Edit Attendance Employees",
    "smart_attendance.delete_employee": "Delete Attendance Employees",
    "smart_attendance.view_biometricdevice": "View Biometric Devices",
    "smart_attendance.add_biometricdevice": "Register Biometric Devices",
    "smart_attendance.change_biometricdevice": "Edit Biometric Devices",
    "smart_attendance.delete_biometricdevice": "Delete Biometric Devices",
    "smart_attendance.view_attendancelog": "View Attendance Logs",
    "smart_attendance.view_dailyattendance": "View Daily Attendance",
    "smart_attendance.view_attendanceanalytics": "View Attendance Analytics",
    "smart_attendance.view_attendance_dashboard": "View Attendance Dashboard",
    "smart_attendance.export_attendance": "Export Attendance & Analytics",
    "smart_attendance.view_own_attendance": "View Own Attendance Only",
    # Clients
    "clients.view_client": "View Clients",
    "clients.add_client": "Create Clients",
    "clients.change_client": "Edit Clients",
    "clients.delete_client": "Delete Clients",
    # Messaging
    "messaging.view_conversation": "View Conversations",
    "messaging.add_conversation": "Create Conversations",
    "messaging.change_conversation": "Edit Conversations",
    "messaging.delete_conversation": "Delete Conversations",
    "messaging.view_conversationmember": "View Conversation Members",
    "messaging.add_conversationmember": "Add Conversation Members",
    "messaging.change_conversationmember": "Edit Conversation Members",
    "messaging.delete_conversationmember": "Remove Conversation Members",
    "messaging.view_message": "View Messages",
    "messaging.add_message": "Send Messages",
    "messaging.change_message": "Edit Messages",
    "messaging.delete_message": "Delete Messages",
    "messaging.view_messagehiddenforuser": "View Message Hidden For User",
    "messaging.add_messagehiddenforuser": "Create Message Hidden For User",
    "messaging.change_messagehiddenforuser": "Edit Message Hidden For User",
    "messaging.delete_messagehiddenforuser": "Delete Message Hidden For User",
    "messaging.view_callsession": "View Call Sessions",
    "messaging.add_callsession": "Create Call Sessions",
    "messaging.change_callsession": "Edit Call Sessions",
    "messaging.delete_callsession": "Delete Call Sessions",
    "messaging.view_userpresence": "View User Presence",
    "messaging.add_userpresence": "Create User Presence",
    "messaging.change_userpresence": "Edit User Presence",
    "messaging.delete_userpresence": "Delete User Presence",
    "messaging.view_typingindicator": "View Typing Indicator",
    "messaging.add_typingindicator": "Create Typing Indicator",
    "messaging.change_typingindicator": "Edit Typing Indicator",
    "messaging.delete_typingindicator": "Delete Typing Indicator",
    # Bulk Mailing
    "mailing.use_bulk_mailing": "Use bulk mailing",
    # Accounting
    "accounting.view_transaction": "View Transactions",
    "accounting.add_transaction": "Create Transactions",
    "accounting.change_transaction": "Edit Transactions",
    "accounting.delete_transaction": "Delete Transactions",
    "accounting.view_ledger": "View Ledger",
    "accounting.view_account": "View Account",
    "accounting.add_account": "Create Account",
    "accounting.change_account": "Edit Account",
    "accounting.delete_account": "Delete Account",
    "accounting.view_financialreport": "View Financial Reports",
    "accounting.add_financialreport": "Create Financial Reports",
    "accounting.change_financialreport": "Edit Financial Reports",
    "accounting.delete_financialreport": "Delete Financial Reports",
    # Core / Company
    "core.view_companyprofile": "View Company Profile",
    "core.add_companyprofile": "Create Company Profile",
    "core.change_companyprofile": "Edit Company Profile",
    "core.delete_companyprofile": "Delete Company Profile",
    "core.view_bankaccount": "View Bank Accounts",
    "core.add_bankaccount": "Create Bank Accounts",
    "core.change_bankaccount": "Edit Bank Accounts",
    "core.delete_bankaccount": "Delete Bank Accounts",
    # Accounts / Security & Users
    "accounts.view_user": "View Users",
    "accounts.add_user": "Create Users",
    "accounts.change_user": "Edit Users",
    "accounts.delete_user": "Delete Users",
    "accounts.view_subuser": "View Team Members",
    "accounts.add_subuser": "Create Team Members",
    "accounts.change_subuser": "Edit Team Members",
    "accounts.delete_subuser": "Delete Team Members",
    "accounts.view_useractivity": "View Activity Log (legacy)",
    "accounts.view_activity_log": "View Activity Log",
    "accounts.view_usersession": "View Sessions",
    "accounts.change_usersession": "Terminate Sessions / Log Out All Users",
    "accounts.view_accountgroup": "View Roles",
    "accounts.add_accountgroup": "Create Roles",
    "accounts.change_accountgroup": "Edit Roles",
    "accounts.delete_accountgroup": "Delete Roles",
    # Auth (Roles & Permissions) – only if ever shown
    "auth.view_group": "View Groups",
    "auth.add_group": "Create Groups",
    "auth.change_group": "Edit Groups",
    "auth.delete_group": "Delete Groups",
}


def get_permission_display_label(permission):
    """
    Return human-readable label for a Permission instance (display only; never modifies DB).
    Uses PERMISSION_LABELS if present, else permission.name if meaningful, else generated from codename.
    """
    if permission is None:
        return ""
    spec = f"{permission.content_type.app_label}.{permission.codename}"
    if spec in PERMISSION_LABELS:
        return PERMISSION_LABELS[spec]
    name = getattr(permission, "name", None) or ""
    if name and name.strip() and name != permission.codename:
        return name.strip()
    # Generate from codename: replace underscores with spaces, capitalize words (no app prefix in label)
    return permission.codename.replace("_", " ").title()


def get_permission_label(permission):
    """Alias for get_permission_display_label; single source of truth for permission display."""
    return get_permission_display_label(permission)


def get_permissions_grouped_by_module(permissions_queryset_or_list):
    """
    Return a list of dicts: [{"module_label": "Job Orders", "app_label": "job_orders", "permissions": [(perm, display_label), ...]}, ...]
    Ordered by PERMISSION_MODULE_ORDER; apps not in order appear at the end.
    Accepts a QuerySet or a list of Permission instances (with content_type loaded when using a list).
    """
    from collections import defaultdict
    grouped = defaultdict(list)
    if hasattr(permissions_queryset_or_list, "select_related"):
        iterable = permissions_queryset_or_list.select_related("content_type")
    else:
        iterable = permissions_queryset_or_list
    for perm in iterable:
        app_label = perm.content_type.app_label
        label = get_permission_display_label(perm)
        grouped[app_label].append((perm, label))
    result = []
    seen = set()
    for app_label in PERMISSION_MODULE_ORDER:
        if app_label in grouped:
            seen.add(app_label)
            result.append({
                "module_label": PERMISSION_MODULE_LABELS.get(app_label, app_label.replace("_", " ").title()),
                "app_label": app_label,
                "permissions": grouped[app_label],
            })
    for app_label in sorted(grouped.keys()):
        if app_label not in seen:
            result.append({
                "module_label": PERMISSION_MODULE_LABELS.get(app_label, app_label.replace("_", " ").title()),
                "app_label": app_label,
                "permissions": grouped[app_label],
            })
    return result


def get_role_permissions_display(permissions_queryset_or_list, max_visible=5):
    """
    For Roles list page: same grouping as Create/Edit, but cap visible items and return more_count.
    Returns (display_grouped, more_count). display_grouped is list of dicts with module_label and
    permissions (list of (perm, display_label)) with at most max_visible permissions total.
    Accepts a QuerySet or list of Permission instances.
    """
    grouped = get_permissions_grouped_by_module(permissions_queryset_or_list)
    total = sum(len(g["permissions"]) for g in grouped)
    display_grouped = []
    remaining = max_visible
    for g in grouped:
        if remaining <= 0:
            break
        perms = g["permissions"][:remaining]
        display_grouped.append({"module_label": g["module_label"], "permissions": perms})
        remaining -= len(perms)
    return display_grouped, max(0, total - max_visible)
