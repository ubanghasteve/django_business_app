"""
Human-readable labels for permissions displayed on Role Create/Edit pages.

Database permission codenames are NEVER changed; this mapping is for display only.
Format: "app_label.codename" -> "User-friendly label".
"""

PERMISSION_MODULE_ORDER = [
    "job_orders",
    "invoices",
    "receipts",
    "quotations",
    "waybills",
    "requisitions",
    "staff_offences",
    "store",
    "inventory",
    "expense",
    "expenses",
    "clients",
    "accounting",
    "finance_engine",
    "messaging",
    "mailing",
    "hr_staff",
    "payroll",
    "smart_attendance",
    "documents",
    "notifications",
    "videocalls",
    "tax_engine",
    "ai_engine",
    "extraction",
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
    "staff_offences": "Staff Offences",
    "store": "Store",
    "inventory": "Inventory",
    "expense": "Expense",
    "expenses": "Expenses (Extended)",
    "clients": "Clients",
    "accounting": "Accounting",
    "finance_engine": "Finance Engine",
    "messaging": "Messaging",
    "mailing": "Bulk Mailing",
    "hr_staff": "HR & Staff",
    "payroll": "Payroll",
    "smart_attendance": "Smart Attendance",
    "documents": "Documents",
    "notifications": "Notifications",
    "videocalls": "Video Calls & Recordings",
    "tax_engine": "Tax Engine",
    "ai_engine": "AI Engine",
    "extraction": "Extraction",
    "core": "Company",
    "accounts": "Security & Users",
    "auth": "Roles & Permissions",
}

PERMISSION_LABELS = {
    # =============================================================================
    # JOB ORDERS - Products, Orders, Templates, Production, Leave
    # =============================================================================
    # Products
    "job_orders.view_product": "View Job Order Products",
    "job_orders.add_product": "Create Job Order Products",
    "job_orders.change_product": "Edit Job Order Products",
    "job_orders.delete_product": "Delete Job Order Products",
    "job_orders.print_product": "Print Job Order Products",
    "job_orders.download_product": "Download/Export Job Order Products",
    "job_orders.can_approve_jobs": "Approve Job Order Products",
    "job_orders.can_view_all_jobs": "View All Job Order Products",
    "job_orders.can_export_jobs": "Export Job Order Products",
    "job_orders.can_manage_production": "Manage Production Status",
    "job_orders.can_export_products": "Export Products",
    "job_orders.view_dashboard": "View Job Order Dashboard",
    # Orders
    "job_orders.view_order": "View Orders",
    "job_orders.add_order": "Create Orders",
    "job_orders.change_order": "Edit Orders",
    "job_orders.delete_order": "Delete Orders",
    # Templates
    "job_orders.view_jobordertemplate": "View Job Order Templates",
    "job_orders.add_jobordertemplate": "Create Job Order Templates",
    "job_orders.change_jobordertemplate": "Edit Job Order Templates",
    "job_orders.delete_jobordertemplate": "Delete Job Order Templates",
    # Leave
    "job_orders.view_leave": "View Leave Requests",
    "job_orders.add_leave": "Create Leave Requests",
    "job_orders.change_leave": "Edit Leave Requests",
    "job_orders.delete_leave": "Delete Leave Requests",
    "job_orders.manage_leave": "Manage Leave Requests",
    "job_orders.can_export_leaves": "Export Leave Requests",
    "job_orders.view_customer": "View Customers",
    "job_orders.add_customer": "Create Customers",
    "job_orders.change_customer": "Edit Customers",
    "job_orders.delete_customer": "Delete Customers",
    "job_orders.view_employeeprofile": "View Employee Profiles",
    "job_orders.add_employeeprofile": "Create Employee Profiles",
    "job_orders.change_employeeprofile": "Edit Employee Profiles",
    "job_orders.delete_employeeprofile": "Delete Employee Profiles",
    "job_orders.view_profile": "View Profiles",
    "job_orders.add_profile": "Create Profiles",
    "job_orders.change_profile": "Edit Profiles",
    "job_orders.delete_profile": "Delete Profiles",
    "job_orders.view_receipt": "View Receipts",
    "job_orders.add_receipt": "Create Receipts",
    "job_orders.change_receipt": "Edit Receipts",
    "job_orders.delete_receipt": "Delete Receipts",
    "job_orders.view_invoice": "View Invoices",
    "job_orders.add_invoice": "Create Invoices",
    "job_orders.change_invoice": "Edit Invoices",
    "job_orders.delete_invoice": "Delete Invoices",
    "job_orders.view_waybill": "View Waybills",
    "job_orders.add_waybill": "Create Waybills",
    "job_orders.change_waybill": "Edit Waybills",
    "job_orders.delete_waybill": "Delete Waybills",
    "job_orders.view_store": "View Stores",
    "job_orders.add_store": "Create Stores",
    "job_orders.change_store": "Edit Stores",
    "job_orders.delete_store": "Delete Stores",
    "job_orders.view_storeinventory": "View Store Inventory",
    "job_orders.add_storeinventory": "Create Store Inventory",
    "job_orders.change_storeinventory": "Edit Store Inventory",
    "job_orders.delete_storeinventory": "Delete Store Inventory",
    "job_orders.view_stockmovement": "View Stock Movements",
    "job_orders.add_stockmovement": "Create Stock Movements",
    "job_orders.change_stockmovement": "Edit Stock Movements",
    "job_orders.delete_stockmovement": "Delete Stock Movements",
    "job_orders.view_productstatushistory": "View Product Status History",
    "job_orders.add_productstatushistory": "Create Product Status History",
    "job_orders.change_productstatushistory": "Edit Product Status History",
    "job_orders.delete_productstatushistory": "Delete Product Status History",

    # =============================================================================
    # INVOICES - Invoices and Templates
    # =============================================================================
    "invoices.view_invoice": "View Invoices",
    "invoices.add_invoice": "Create Invoices",
    "invoices.change_invoice": "Edit Invoices",
    "invoices.delete_invoice": "Delete Invoices",
    "invoices.print_invoice": "Print Invoices",
    "invoices.download_invoice": "Download/Export Invoices",
    "invoices.can_approve_invoice": "Approve Invoices",
    "invoices.view_invoicetemplate": "View Invoice Templates",
    "invoices.add_invoicetemplate": "Create Invoice Templates",
    "invoices.change_invoicetemplate": "Edit Invoice Templates",
    "invoices.delete_invoicetemplate": "Delete Invoice Templates",
    "invoices.view_invoiceitem": "View Invoice Items",
    "invoices.add_invoiceitem": "Create Invoice Items",
    "invoices.change_invoiceitem": "Edit Invoice Items",
    "invoices.delete_invoiceitem": "Delete Invoice Items",

    # =============================================================================
    # RECEIPTS
    # =============================================================================
    "receipts.view_receipt": "View Receipts",
    "receipts.add_receipt": "Create Receipts",
    "receipts.change_receipt": "Edit Receipts",
    "receipts.delete_receipt": "Delete Receipts",
    "receipts.print_receipt": "Print Receipts",
    "receipts.download_receipt": "Download/Export Receipts",

    # =============================================================================
    # QUOTATIONS - Quotations and Templates
    # =============================================================================
    "quotations.view_quotation": "View Quotations",
    "quotations.add_quotation": "Create Quotations",
    "quotations.change_quotation": "Edit Quotations",
    "quotations.delete_quotation": "Delete Quotations",
    "quotations.print_quotation": "Print Quotations",
    "quotations.download_quotation": "Download/Export Quotations",
    "quotations.can_approve_quotation": "Approve Quotations",
    "quotations.view_quotationtemplate": "View Quotation Templates",
    "quotations.add_quotationtemplate": "Create Quotation Templates",
    "quotations.change_quotationtemplate": "Edit Quotation Templates",
    "quotations.delete_quotationtemplate": "Delete Quotation Templates",
    "quotations.view_quotationitem": "View Quotation Items",
    "quotations.add_quotationitem": "Create Quotation Items",
    "quotations.change_quotationitem": "Edit Quotation Items",
    "quotations.delete_quotationitem": "Delete Quotation Items",

    # =============================================================================
    # WAYBILLS - Waybills and Templates
    # =============================================================================
    "waybills.view_waybill": "View Waybills",
    "waybills.add_waybill": "Create Waybills",
    "waybills.change_waybill": "Edit Waybills",
    "waybills.delete_waybill": "Delete Waybills",
    "waybills.print_waybill": "Print Waybills",
    "waybills.download_waybill": "Download/Export Waybills",
    "waybills.can_approve_waybill": "Approve Waybills",
    "waybills.view_waybilltemplate": "View Waybill Templates",
    "waybills.add_waybilltemplate": "Create Waybill Templates",
    "waybills.change_waybilltemplate": "Edit Waybill Templates",
    "waybills.delete_waybilltemplate": "Delete Waybill Templates",
    "waybills.view_waybillitem": "View Waybill Items",
    "waybills.add_waybillitem": "Create Waybill Items",
    "waybills.change_waybillitem": "Edit Waybill Items",
    "waybills.delete_waybillitem": "Delete Waybill Items",
    "waybills.view_waybillfieldtemplate": "View Waybill Field Templates",
    "waybills.add_waybillfieldtemplate": "Create Waybill Field Templates",
    "waybills.change_waybillfieldtemplate": "Edit Waybill Field Templates",
    "waybills.delete_waybillfieldtemplate": "Delete Waybill Field Templates",
    "waybills.view_waybillmovement": "View Waybill Movements",
    "waybills.add_waybillmovement": "Create Waybill Movements",
    "waybills.change_waybillmovement": "Edit Waybill Movements",
    "waybills.delete_waybillmovement": "Delete Waybill Movements",

    # =============================================================================
    # REQUISITIONS
    # =============================================================================
    "requisitions.view_requisition": "View Requisitions",
    "requisitions.add_requisition": "Create Requisitions",
    "requisitions.change_requisition": "Edit Requisitions",
    "requisitions.delete_requisition": "Delete Requisitions",
    "requisitions.print_requisition": "Print Requisitions",
    "requisitions.download_requisition": "Download/Export Requisitions",
    "requisitions.can_approve_requisition": "Approve Requisitions",

    # =============================================================================
    # STAFF OFFENCES
    # =============================================================================
    "staff_offences.view_staffoffenceregister": "View Staff Offence Registers",
    "staff_offences.add_staffoffenceregister": "Create Staff Offence Registers",
    "staff_offences.change_staffoffenceregister": "Edit Staff Offence Registers (payment status, signature)",
    "staff_offences.delete_staffoffenceregister": "Delete Staff Offence Registers",
    "staff_offences.print_staffoffenceregister": "Print Staff Offence Registers",
    "staff_offences.download_staffoffenceregister": "Download Staff Offence Registers (PDF)",
    "staff_offences.view_staffoffenceentry": "View Staff Offence Entries",
    "staff_offences.add_staffoffenceentry": "Add Staff Offence Entries",
    "staff_offences.change_staffoffenceentry": "Edit Staff Offence Entries",
    "staff_offences.delete_staffoffenceentry": "Delete Staff Offence Entries",

    # =============================================================================
    # STORE
    # =============================================================================
    "store.view_store": "View Store Records",
    "store.add_store": "Create Store Records",
    "store.change_store": "Edit Store Records",
    "store.delete_store": "Delete Store Records",
    "store.print_store": "Print Store Records",
    "store.download_store": "Download/Export Store Records",
    "store.can_approve_store": "Approve Store Records",
    "store.view_storecategory": "View Store Categories",
    "store.add_storecategory": "Create Store Categories",
    "store.change_storecategory": "Edit Store Categories",
    "store.delete_storecategory": "Delete Store Categories",
    "store.view_storecustomfield": "View Store Custom Fields",
    "store.add_storecustomfield": "Create Store Custom Fields",
    "store.change_storecustomfield": "Edit Store Custom Fields",
    "store.delete_storecustomfield": "Delete Store Custom Fields",
    "store.view_storelayout": "View Store Layouts",
    "store.add_storelayout": "Create Store Layouts",
    "store.change_storelayout": "Edit Store Layouts",
    "store.delete_storelayout": "Delete Store Layouts",
    "store.view_storeexport": "View Store Exports",
    "store.add_storeexport": "Create Store Exports",
    "store.change_storeexport": "Edit Store Exports",
    "store.delete_storeexport": "Delete Store Exports",
    "store.view_importedstorefile": "View Imported Store Files",
    "store.add_importedstorefile": "Import Store Files",
    "store.change_importedstorefile": "Edit Imported Store Files",
    "store.delete_importedstorefile": "Delete Imported Store Files",
    "store.view_store_category": "View Store Categories (alias)",
    "store.view_store_customfield": "View Store Custom Fields (alias)",
    "store.view_store_customform": "View Store Custom Forms (alias)",
    "store.view_store_layout": "View Store Layouts (alias)",
    "store.view_storecustomfieldvalue": "View Store Custom Field Values",
    "store.add_storecustomfieldvalue": "Create Store Custom Field Values",
    "store.change_storecustomfieldvalue": "Edit Store Custom Field Values",
    "store.delete_storecustomfieldvalue": "Delete Store Custom Field Values",
    "store.view_storecustomform": "View Store Custom Forms",
    "store.add_storecustomform": "Create Store Custom Forms",
    "store.change_storecustomform": "Edit Store Custom Forms",
    "store.delete_storecustomform": "Delete Store Custom Forms",
    "store.view_wastelog": "View Store Waste Logs",
    "store.add_wastelog": "Create Store Waste Logs",
    "store.change_wastelog": "Edit Store Waste Logs",
    "store.delete_wastelog": "Delete Store Waste Logs",

    # =============================================================================
    # INVENTORY
    # =============================================================================
    "inventory.view_inventory": "View Inventory",
    "inventory.add_inventory": "Create Inventory Records",
    "inventory.change_inventory": "Edit Inventory Records",
    "inventory.delete_inventory": "Delete Inventory Records",
    "inventory.print_inventory": "Print Inventory",
    "inventory.download_inventory": "Download/Export Inventory",
    "inventory.can_approve_inventory": "Approve Inventory Records",
    "inventory.view_importedinventoryfile": "View Imported Inventory Files",
    "inventory.add_importedinventoryfile": "Import Inventory Files",
    "inventory.change_importedinventoryfile": "Edit Imported Inventory Files",
    "inventory.delete_importedinventoryfile": "Delete Imported Inventory Files",
    "inventory.view_inventorycategory": "View Inventory Categories",
    "inventory.add_inventorycategory": "Create Inventory Categories",
    "inventory.change_inventorycategory": "Edit Inventory Categories",
    "inventory.delete_inventorycategory": "Delete Inventory Categories",
    "inventory.view_inventorycustomfield": "View Inventory Custom Fields",
    "inventory.add_inventorycustomfield": "Create Inventory Custom Fields",
    "inventory.change_inventorycustomfield": "Edit Inventory Custom Fields",
    "inventory.delete_inventorycustomfield": "Delete Inventory Custom Fields",
    "inventory.view_inventoryexport": "View Inventory Exports",
    "inventory.add_inventoryexport": "Create Inventory Exports",
    "inventory.change_inventoryexport": "Edit Inventory Exports",
    "inventory.delete_inventoryexport": "Delete Inventory Exports",
    "inventory.view_inventoryitem": "View Inventory Items",
    "inventory.add_inventoryitem": "Create Inventory Items",
    "inventory.change_inventoryitem": "Edit Inventory Items",
    "inventory.delete_inventoryitem": "Delete Inventory Items",
    "inventory.view_inventorylayout": "View Inventory Layouts",
    "inventory.add_inventorylayout": "Create Inventory Layouts",
    "inventory.change_inventorylayout": "Edit Inventory Layouts",
    "inventory.delete_inventorylayout": "Delete Inventory Layouts",
    "inventory.view_inventorylog": "View Inventory Logs",
    "inventory.add_inventorylog": "Create Inventory Logs",
    "inventory.change_inventorylog": "Edit Inventory Logs",
    "inventory.delete_inventorylog": "Delete Inventory Logs",
    "inventory.view_inventorymovement": "View Inventory Movements",
    "inventory.add_inventorymovement": "Create Inventory Movements",
    "inventory.change_inventorymovement": "Edit Inventory Movements",
    "inventory.delete_inventorymovement": "Delete Inventory Movements",
    "inventory.view_inventoryproduct": "View Inventory Products",
    "inventory.add_inventoryproduct": "Create Inventory Products",
    "inventory.change_inventoryproduct": "Edit Inventory Products",
    "inventory.delete_inventoryproduct": "Delete Inventory Products",
    "inventory.view_inventoryissue": "View Inventory Issues",
    "inventory.add_inventoryissue": "Create Inventory Issues",
    "inventory.change_inventoryissue": "Edit Inventory Issues",
    "inventory.delete_inventoryissue": "Delete Inventory Issues",
    "inventory.view_inventoryreceipt": "View Inventory Receipts",
    "inventory.add_inventoryreceipt": "Create Inventory Receipts",
    "inventory.change_inventoryreceipt": "Edit Inventory Receipts",
    "inventory.delete_inventoryreceipt": "Delete Inventory Receipts",
    "inventory.view_wastelog": "View Inventory Waste Logs",
    "inventory.add_wastelog": "Create Inventory Waste Logs",
    "inventory.change_wastelog": "Edit Inventory Waste Logs",
    "inventory.delete_wastelog": "Delete Inventory Waste Logs",
    "inventory.view_inventorystatus": "View Inventory Status",
    "inventory.add_inventorystatus": "Create Inventory Status",
    "inventory.change_inventorystatus": "Edit Inventory Status",
    "inventory.delete_inventorystatus": "Delete Inventory Status",
    "inventory.view_inventorytemplate": "View Inventory Templates",
    "inventory.add_inventorytemplate": "Create Inventory Templates",
    "inventory.change_inventorytemplate": "Edit Inventory Templates",
    "inventory.delete_inventorytemplate": "Delete Inventory Templates",
    "inventory.view_inventorytransaction": "View Inventory Transactions",
    "inventory.add_inventorytransaction": "Create Inventory Transactions",
    "inventory.change_inventorytransaction": "Edit Inventory Transactions",
    "inventory.delete_inventorytransaction": "Delete Inventory Transactions",

    # =============================================================================
    # EXPENSE
    # =============================================================================
    "expense.view_expense": "View Expenses",
    "expense.add_expense": "Create Expenses",
    "expense.change_expense": "Edit Expenses",
    "expense.delete_expense": "Delete Expenses",
    "expense.print_expense": "Print Expenses",
    "expense.download_expense": "Download/Export Expenses",
    "expense.can_approve_expense": "Approve Expenses",
    "expense.view_expensemovement": "View Expense Movements",
    "expense.add_expensemovement": "Create Expense Movements",
    "expense.change_expensemovement": "Edit Expense Movements",
    "expense.delete_expensemovement": "Delete Expense Movements",

    # =============================================================================
    # EXPENSES (Legacy/Extended - multiple models)
    # =============================================================================
    "expenses.view_expense": "View Expenses (Extended)",
    "expenses.add_expense": "Create Expenses (Extended)",
    "expenses.change_expense": "Edit Expenses (Extended)",
    "expenses.delete_expense": "Delete Expenses (Extended)",
    "expenses.view_expenseapproval": "View Expense Approvals",
    "expenses.add_expenseapproval": "Create Expense Approvals",
    "expenses.change_expenseapproval": "Edit Expense Approvals",
    "expenses.delete_expenseapproval": "Delete Expense Approvals",
    "expenses.view_expenseattachment": "View Expense Attachments",
    "expenses.add_expenseattachment": "Create Expense Attachments",
    "expenses.change_expenseattachment": "Edit Expense Attachments",
    "expenses.delete_expenseattachment": "Delete Expense Attachments",
    "expenses.view_expensecategory": "View Expense Categories",
    "expenses.add_expensecategory": "Create Expense Categories",
    "expenses.change_expensecategory": "Edit Expense Categories",
    "expenses.delete_expensecategory": "Delete Expense Categories",
    "expenses.view_expensereport": "View Expense Reports",
    "expenses.add_expensereport": "Create Expense Reports",
    "expenses.change_expensereport": "Edit Expense Reports",
    "expenses.delete_expensereport": "Delete Expense Reports",
    "expenses.view_expensetemplate": "View Expense Templates",
    "expenses.add_expensetemplate": "Create Expense Templates",
    "expenses.change_expensetemplate": "Edit Expense Templates",
    "expenses.delete_expensetemplate": "Delete Expense Templates",

    # =============================================================================
    # FINANCE ENGINE - Account, FinancialTransaction, JournalEntry, JournalLine
    # =============================================================================
    "finance_engine.view_account": "View Finance Accounts",
    "finance_engine.add_account": "Create Finance Accounts",
    "finance_engine.change_account": "Edit Finance Accounts",
    "finance_engine.delete_account": "Delete Finance Accounts",
    "finance_engine.view_financialtransaction": "View Financial Transactions",
    "finance_engine.add_financialtransaction": "Create Financial Transactions",
    "finance_engine.change_financialtransaction": "Edit Financial Transactions",
    "finance_engine.delete_financialtransaction": "Delete Financial Transactions",
    "finance_engine.view_journalentry": "View Journal Entries",
    "finance_engine.add_journalentry": "Create Journal Entries",
    "finance_engine.change_journalentry": "Edit Journal Entries",
    "finance_engine.delete_journalentry": "Delete Journal Entries",
    "finance_engine.view_journalline": "View Journal Lines",
    "finance_engine.add_journalline": "Create Journal Lines",
    "finance_engine.change_journalline": "Edit Journal Lines",
    "finance_engine.delete_journalline": "Delete Journal Lines",

    # =============================================================================
    # CLIENTS
    # =============================================================================
    "clients.view_client": "View Clients",
    "clients.add_client": "Create Clients",
    "clients.change_client": "Edit Clients",
    "clients.delete_client": "Delete Clients",
    "clients.print_client": "Print Clients",
    "clients.download_client": "Download/Export Clients",

    # =============================================================================
    # ACCOUNTING - Transactions, Ledger, Accounts, Journal, Reports
    # =============================================================================
    "accounting.view_transaction": "View Transactions",
    "accounting.add_transaction": "Create Transactions",
    "accounting.change_transaction": "Edit Transactions",
    "accounting.delete_transaction": "Delete Transactions",
    "accounting.view_ledger": "View Ledger",
    "accounting.view_account": "View Accounts",
    "accounting.add_account": "Create Accounts",
    "accounting.change_account": "Edit Accounts",
    "accounting.delete_account": "Delete Accounts",
    "accounting.view_financialreport": "View Financial Reports",
    "accounting.add_financialreport": "Create Financial Reports",
    "accounting.change_financialreport": "Edit Financial Reports",
    "accounting.delete_financialreport": "Delete Financial Reports",
    "accounting.view_journalentry": "View Journal Entries",
    "accounting.add_journalentry": "Create Journal Entries",
    "accounting.change_journalentry": "Edit Journal Entries",
    "accounting.delete_journalentry": "Delete Journal Entries",
    "accounting.view_chartofaccount": "View Chart of Accounts",
    "accounting.add_chartofaccount": "Create Chart of Accounts",
    "accounting.change_chartofaccount": "Edit Chart of Accounts",
    "accounting.delete_chartofaccount": "Delete Chart of Accounts",
    # Accounting Double-Entry Extensions
    "accounting.view_accountcategory": "View Account Categories",
    "accounting.add_accountcategory": "Create Account Categories",
    "accounting.change_accountcategory": "Edit Account Categories",
    "accounting.delete_accountcategory": "Delete Account Categories",
    "accounting.view_accounttype": "View Account Types",
    "accounting.add_accounttype": "Create Account Types",
    "accounting.change_accounttype": "Edit Account Types",
    "accounting.delete_accounttype": "Delete Account Types",
    "accounting.view_fiscalperiod": "View Fiscal Periods",
    "accounting.add_fiscalperiod": "Create Fiscal Periods",
    "accounting.change_fiscalperiod": "Edit Fiscal Periods",
    "accounting.delete_fiscalperiod": "Delete Fiscal Periods",
    "accounting.view_currency": "View Currencies",
    "accounting.add_currency": "Create Currencies",
    "accounting.change_currency": "Edit Currencies",
    "accounting.delete_currency": "Delete Currencies",
    "accounting.view_accountingtransaction": "View Accounting Transactions",
    "accounting.add_accountingtransaction": "Create Accounting Transactions",
    "accounting.change_accountingtransaction": "Edit Accounting Transactions",
    "accounting.delete_accountingtransaction": "Delete Accounting Transactions",
    "accounting.view_journalentryline": "View Journal Entry Lines",
    "accounting.add_journalentryline": "Create Journal Entry Lines",
    "accounting.change_journalentryline": "Edit Journal Entry Lines",
    "accounting.delete_journalentryline": "Delete Journal Entry Lines",
    "accounting.view_ledgerentry": "View Ledger Entries",
    "accounting.add_ledgerentry": "Create Ledger Entries",
    "accounting.change_ledgerentry": "Edit Ledger Entries",
    "accounting.delete_ledgerentry": "Delete Ledger Entries",
    "accounting.view_ledger": "View Ledger",
    "accounting.add_ledger": "Create Ledger",
    "accounting.change_ledger": "Edit Ledger",
    "accounting.delete_ledger": "Delete Ledger",

    # =============================================================================
    # MESSAGING - Conversations, Messages, Calls, Presence
    # =============================================================================
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
    "messaging.view_messagehiddenforuser": "View Hidden Messages",
    "messaging.add_messagehiddenforuser": "Hide Messages",
    "messaging.change_messagehiddenforuser": "Edit Hidden Messages",
    "messaging.delete_messagehiddenforuser": "Delete Hidden Messages",
    "messaging.view_callsession": "View Call Sessions",
    "messaging.add_callsession": "Create Call Sessions",
    "messaging.change_callsession": "Edit Call Sessions",
    "messaging.delete_callsession": "Delete Call Sessions",
    "messaging.view_userpresence": "View User Presence",
    "messaging.add_userpresence": "Update User Presence",
    "messaging.change_userpresence": "Change User Presence",
    "messaging.delete_userpresence": "Remove User Presence",
    "messaging.view_typingindicator": "View Typing Indicators",
    "messaging.add_typingindicator": "Send Typing Indicator",
    "messaging.change_typingindicator": "Update Typing Indicator",
    "messaging.delete_typingindicator": "Remove Typing Indicator",

    # =============================================================================
    # BULK MAILING
    # =============================================================================
    "mailing.use_bulk_mailing": "Use Bulk Mailing",

    # =============================================================================
    # HR & STAFF - Dashboard, Employees, Departments, Leave, Training, etc.
    # =============================================================================
    # Dashboard & HR Permissions
    "hr_staff.view_hr_dashboard": "View HR Dashboard",
    "hr_staff.view_own_hr_dashboard": "View Own HR Dashboard",
    "hr_staff.create_employee_account": "Create Employee Portal Account",
    "hr_staff.reset_employee_password": "Reset Employee Password",
    "hr_staff.view_employee_activity": "View Employee Activity",
    # Departments
    "hr_staff.view_department": "View Departments",
    "hr_staff.add_department": "Create Departments",
    "hr_staff.change_department": "Edit Departments",
    "hr_staff.delete_department": "Delete Departments",
    # Employees
    "hr_staff.view_employee": "View Employees",
    "hr_staff.add_employee": "Create Employees",
    "hr_staff.change_employee": "Edit Employees",
    "hr_staff.delete_employee": "Delete Employees",
    # Leave Requests
    "hr_staff.view_leaverequest": "View Leave Requests",
    "hr_staff.add_leaverequest": "Create Leave Requests",
    "hr_staff.change_leaverequest": "Edit Leave Requests",
    "hr_staff.delete_leaverequest": "Delete Leave Requests",
    "hr_staff.approve_leaverequest": "Approve Leave Requests",
    "hr_staff.reject_leaverequest": "Reject Leave Requests",
    # Leave Policies
    "hr_staff.view_leavepolicy": "View Leave Policies",
    "hr_staff.add_leavepolicy": "Create Leave Policies",
    "hr_staff.change_leavepolicy": "Edit Leave Policies",
    "hr_staff.delete_leavepolicy": "Delete Leave Policies",
    # Attendance
    "hr_staff.view_attendance": "View HR Attendance Records",
    "hr_staff.add_attendance": "Create HR Attendance Records",
    "hr_staff.change_attendance": "Edit HR Attendance Records",
    "hr_staff.delete_attendance": "Delete HR Attendance Records",
    "hr_staff.view_attendancesetting": "View Attendance Settings",
    "hr_staff.add_attendancesetting": "Create Attendance Settings",
    "hr_staff.change_attendancesetting": "Edit Attendance Settings",
    "hr_staff.delete_attendancesetting": "Delete Attendance Settings",
    # Performance Reviews
    "hr_staff.view_performancereview": "View Performance Reviews",
    "hr_staff.add_performancereview": "Create Performance Reviews",
    "hr_staff.change_performancereview": "Edit Performance Reviews",
    "hr_staff.delete_performancereview": "Delete Performance Reviews",
    # Performance Goals
    "hr_staff.view_performancegoal": "View Performance Goals",
    "hr_staff.add_performancegoal": "Create Performance Goals",
    "hr_staff.change_performancegoal": "Edit Performance Goals",
    "hr_staff.delete_performancegoal": "Delete Performance Goals",
    # Performance Evaluations
    "hr_staff.view_performanceevaluation": "View Performance Evaluations",
    "hr_staff.add_performanceevaluation": "Create Performance Evaluations",
    "hr_staff.change_performanceevaluation": "Edit Performance Evaluations",
    "hr_staff.delete_performanceevaluation": "Delete Performance Evaluations",
    # Training
    "hr_staff.view_trainingcourse": "View Training Courses",
    "hr_staff.add_trainingcourse": "Create Training Courses",
    "hr_staff.change_trainingcourse": "Edit Training Courses",
    "hr_staff.delete_trainingcourse": "Delete Training Courses",
    "hr_staff.view_trainingenrollment": "View Training Enrollments",
    "hr_staff.add_trainingenrollment": "Create Training Enrollments",
    "hr_staff.change_trainingenrollment": "Edit Training Enrollments",
    "hr_staff.delete_trainingenrollment": "Delete Training Enrollments",
    # Employee Documents
    "hr_staff.view_employeedocument": "View Employee Documents",
    "hr_staff.add_employeedocument": "Upload Employee Documents",
    "hr_staff.change_employeedocument": "Edit Employee Documents",
    "hr_staff.delete_employeedocument": "Delete Employee Documents",
    # Job Seekers
    "hr_staff.view_jobseeker": "View Job Seekers",
    "hr_staff.add_jobseeker": "Create Job Seeker Records",
    "hr_staff.change_jobseeker": "Edit Job Seeker Records",
    "hr_staff.delete_jobseeker": "Delete Job Seeker Records",
    "hr_staff.view_jobseekerdocument": "View Job Seeker Documents",
    "hr_staff.add_jobseekerdocument": "Upload Job Seeker Documents",
    "hr_staff.change_jobseekerdocument": "Edit Job Seeker Documents",
    "hr_staff.delete_jobseekerdocument": "Delete Job Seeker Documents",

    # =============================================================================
    # PAYROLL - Records, Categories, Settings, Legacy Models
    # =============================================================================
    # Payroll Records
    "payroll.view_payrollrecord": "View Payroll Records",
    "payroll.add_payrollrecord": "Upload Payroll Records",
    "payroll.change_payrollrecord": "Edit Payroll Records",
    "payroll.delete_payrollrecord": "Delete Payroll Records",
    "payroll.verify_payrollrecord": "Verify Payroll Records",
    "payroll.approve_payrollrecord": "Approve Payroll Records",
    "payroll.share_payrollrecord": "Share Payroll Records",
    # Payroll Categories
    "payroll.view_payrollcategory": "View Payroll Categories",
    "payroll.add_payrollcategory": "Create Payroll Categories",
    "payroll.change_payrollcategory": "Edit Payroll Categories",
    "payroll.delete_payrollcategory": "Delete Payroll Categories",
    # Payroll Access Logs
    "payroll.view_payrollrecordaccesslog": "View Payroll Access Logs",
    "payroll.add_payrollrecordaccesslog": "Create Payroll Access Logs",
    "payroll.change_payrollrecordaccesslog": "Edit Payroll Access Logs",
    "payroll.delete_payrollrecordaccesslog": "Delete Payroll Access Logs",
    # Payroll Shares
    "payroll.view_payrollrecordshare": "View Payroll Shares",
    "payroll.add_payrollrecordshare": "Create Payroll Shares",
    "payroll.change_payrollrecordshare": "Edit Payroll Shares",
    "payroll.delete_payrollrecordshare": "Delete Payroll Shares",
    # Extracted Payroll Data
    "payroll.view_extractedpayrolldata": "View Extracted Payroll Data",
    "payroll.add_extractedpayrolldata": "Create Extracted Payroll Data",
    "payroll.change_extractedpayrolldata": "Edit Extracted Payroll Data",
    "payroll.delete_extractedpayrolldata": "Delete Extracted Payroll Data",
    # Payroll Templates
    "payroll.view_payrolltemplate": "View Payroll Templates",
    "payroll.add_payrolltemplate": "Create Payroll Templates",
    "payroll.change_payrolltemplate": "Edit Payroll Templates",
    "payroll.delete_payrolltemplate": "Delete Payroll Templates",
    # Payroll Entries
    "payroll.view_payrollementry": "View Payroll Entries",
    "payroll.add_payrollementry": "Create Payroll Entries",
    "payroll.change_payrollementry": "Edit Payroll Entries",
    "payroll.delete_payrollementry": "Delete Payroll Entries",
    # Payroll Notifications
    "payroll.view_payrollnotification": "View Payroll Notifications",
    "payroll.add_payrollnotification": "Create Payroll Notifications",
    "payroll.change_payrollnotification": "Edit Payroll Notifications",
    "payroll.delete_payrollnotification": "Delete Payroll Notifications",
    # Payroll Settings
    "payroll.view_payrollsetting": "View Payroll Settings",
    "payroll.add_payrollsetting": "Create Payroll Settings",
    "payroll.change_payrollsetting": "Edit Payroll Settings",
    "payroll.delete_payrollsetting": "Delete Payroll Settings",
    # Legacy Payroll Models
    "payroll.view_payroll": "View Payroll",
    "payroll.create_payroll": "Create Payroll",
    "payroll.edit_payroll": "Edit Payroll",
    "payroll.delete_payroll": "Delete Payroll",
    "payroll.view_payslip": "View Payslips",
    "payroll.generate_payslip": "Generate Payslips",
    "payroll.view_salaryadvance": "View Salary Advances",
    "payroll.add_salaryadvance": "Create Salary Advances",
    "payroll.change_salaryadvance": "Edit Salary Advances",
    "payroll.delete_salaryadvance": "Delete Salary Advances",
    "payroll.approve_salaryadvance": "Approve Salary Advances",
    "payroll.view_loan": "View Loans",
    "payroll.add_loan": "Create Loans",
    "payroll.change_loan": "Edit Loans",
    "payroll.delete_loan": "Delete Loans",
    "payroll.view_bonusrule": "View Bonus Rules",
    "payroll.add_bonusrule": "Create Bonus Rules",
    "payroll.change_bonusrule": "Edit Bonus Rules",
    "payroll.delete_bonusrule": "Delete Bonus Rules",
    "payroll.view_payrollstructure": "View Payroll Structures",
    "payroll.add_payrollstructure": "Create Payroll Structures",
    "payroll.change_payrollstructure": "Edit Payroll Structures",
    "payroll.delete_payrollstructure": "Delete Payroll Structures",
    "payroll.view_employeepayrollprofile": "View Employee Payroll Profiles",
    "payroll.add_employeepayrollprofile": "Create Employee Payroll Profiles",
    "payroll.change_employeepayrollprofile": "Edit Employee Payroll Profiles",
    "payroll.delete_employeepayrollprofile": "Delete Employee Payroll Profiles",
    "payroll.view_payrollperiod": "View Payroll Periods",
    "payroll.add_payrollperiod": "Create Payroll Periods",
    "payroll.change_payrollperiod": "Edit Payroll Periods",
    "payroll.delete_payrollperiod": "Delete Payroll Periods",
    "payroll.view_payrollrun": "View Payroll Runs",
    "payroll.add_payrollrun": "Create Payroll Runs",
    "payroll.change_payrollrun": "Edit Payroll Runs",
    "payroll.delete_payrollrun": "Delete Payroll Runs",
    "payroll.view_payrollitem": "View Payroll Items",
    "payroll.add_payrollitem": "Create Payroll Items",
    "payroll.change_payrollitem": "Edit Payroll Items",
    "payroll.delete_payrollitem": "Delete Payroll Items",
    "payroll.view_employeebonus": "View Employee Bonuses",
    "payroll.add_employeebonus": "Create Employee Bonuses",
    "payroll.change_employeebonus": "Edit Employee Bonuses",
    "payroll.delete_employeebonus": "Delete Employee Bonuses",
    "payroll.view_employeeloan": "View Employee Loans",
    "payroll.add_employeeloan": "Create Employee Loans",
    "payroll.change_employeeloan": "Edit Employee Loans",
    "payroll.delete_employeeloan": "Delete Employee Loans",
    "payroll.view_loanrepayment": "View Loan Repayments",
    "payroll.add_loanrepayment": "Create Loan Repayments",
    "payroll.change_loanrepayment": "Edit Loan Repayments",
    "payroll.delete_loanrepayment": "Delete Loan Repayments",
    "payroll.view_exceldata": "View Excel Payroll Data",
    "payroll.add_exceldata": "Create Excel Payroll Data",
    "payroll.change_exceldata": "Edit Excel Payroll Data",
    "payroll.delete_exceldata": "Delete Excel Payroll Data",
    "payroll.view_extractedpayrollrecord": "View Extracted Payroll Records",
    "payroll.add_extractedpayrollrecord": "Create Extracted Payroll Records",
    "payroll.change_extractedpayrollrecord": "Edit Extracted Payroll Records",
    "payroll.delete_extractedpayrollrecord": "Delete Extracted Payroll Records",
    "payroll.view_fileaccesslog": "View File Access Logs",
    "payroll.add_fileaccesslog": "Create File Access Logs",
    "payroll.change_fileaccesslog": "Edit File Access Logs",
    "payroll.delete_fileaccesslog": "Delete File Access Logs",
    "payroll.view_filecategory": "View File Categories",
    "payroll.add_filecategory": "Create File Categories",
    "payroll.change_filecategory": "Edit File Categories",
    "payroll.delete_filecategory": "Delete File Categories",
    "payroll.view_payrollentry": "View Payroll Entries",
    "payroll.add_payrollentry": "Create Payroll Entries",
    "payroll.change_payrollentry": "Edit Payroll Entries",
    "payroll.delete_payrollentry": "Delete Payroll Entries",
    "payroll.view_payrollfile": "View Payroll Files",
    "payroll.add_payrollfile": "Create Payroll Files",
    "payroll.change_payrollfile": "Edit Payroll Files",
    "payroll.delete_payrollfile": "Delete Payroll Files",
    "payroll.delete_payroll_file": "Delete Payroll File",
    "payroll.view_payslip": "View Payslips",
    "payroll.add_payslip": "Create Payslips",
    "payroll.change_payslip": "Edit Payslips",
    "payroll.delete_payslip": "Delete Payslips",
    "payroll.approve_payroll": "Approve Payroll",
    "payroll.run_payroll": "Run Payroll",
    "payroll.upload_payroll_file": "Upload Payroll File",
    "payroll.manage_payroll_files": "Manage Payroll Files",
    "payroll.manage_payroll_template": "Manage Payroll Template",
    "payroll.use_payroll_template": "Use Payroll Template",

    # =============================================================================
    # SMART ATTENDANCE - Dashboard, Employees, Devices, Logs, Analytics
    # =============================================================================
    "smart_attendance.view_attendancelog": "View Attendance Logs",
    "smart_attendance.add_attendancelog": "Create Attendance Logs",
    "smart_attendance.change_attendancelog": "Edit Attendance Logs",
    "smart_attendance.delete_attendancelog": "Delete Attendance Logs",
    "smart_attendance.view_employee": "View Attendance Employees",
    "smart_attendance.add_employee": "Create Attendance Employees",
    "smart_attendance.change_employee": "Edit Attendance Employees",
    "smart_attendance.delete_employee": "Delete Attendance Employees",
    "smart_attendance.view_biometricdevice": "View Biometric Devices",
    "smart_attendance.add_biometricdevice": "Create Biometric Devices",
    "smart_attendance.change_biometricdevice": "Edit Biometric Devices",
    "smart_attendance.delete_biometricdevice": "Delete Biometric Devices",
    "smart_attendance.view_attendancedashboard": "View Attendance Dashboard",
    "smart_attendance.view_dailyattendance": "View Daily Attendance",
    "smart_attendance.view_attendanceanalytics": "View Attendance Analytics",
    "smart_attendance.view_own_attendance": "View Own Attendance",
    "smart_attendance.export_attendance": "Export Attendance Data",
    # Shift Management
    "smart_attendance.view_shift": "View Shifts",
    "smart_attendance.add_shift": "Create Shifts",
    "smart_attendance.change_shift": "Edit Shifts",
    "smart_attendance.delete_shift": "Delete Shifts",
    # Device Status
    "smart_attendance.view_devicestatus": "View Device Status",
    "smart_attendance.add_devicestatus": "Create Device Status",
    "smart_attendance.change_devicestatus": "Edit Device Status",
    "smart_attendance.delete_devicestatus": "Delete Device Status",
    # Biometric Users
    "smart_attendance.view_biometricuser": "View Biometric Users",
    "smart_attendance.add_biometricuser": "Create Biometric Users",
    "smart_attendance.change_biometricuser": "Edit Biometric Users",
    "smart_attendance.delete_biometricuser": "Delete Biometric Users",
    # Raw Biometric Logs
    "smart_attendance.view_rawbiometriclog": "View Raw Biometric Logs",
    "smart_attendance.add_rawbiometriclog": "Create Raw Biometric Logs",
    "smart_attendance.change_rawbiometriclog": "Edit Raw Biometric Logs",
    "smart_attendance.delete_rawbiometriclog": "Delete Raw Biometric Logs",
    # Daily Attendance
    "smart_attendance.view_dailyattendance": "View Daily Attendance Records",
    "smart_attendance.add_dailyattendance": "Create Daily Attendance Records",
    "smart_attendance.change_dailyattendance": "Edit Daily Attendance Records",
    "smart_attendance.delete_dailyattendance": "Delete Daily Attendance Records",
    # Attendance Analytics
    "smart_attendance.view_attendanceanalytics": "View Attendance Analytics",
    "smart_attendance.add_attendanceanalytics": "Create Attendance Analytics",
    "smart_attendance.change_attendanceanalytics": "Edit Attendance Analytics",
    "smart_attendance.delete_attendanceanalytics": "Delete Attendance Analytics",
    # Sync Queue
    "smart_attendance.view_syncqueue": "View Sync Queue",
    "smart_attendance.add_syncqueue": "Create Sync Queue Items",
    "smart_attendance.change_syncqueue": "Edit Sync Queue Items",
    "smart_attendance.delete_syncqueue": "Delete Sync Queue Items",
    # Corrupted Logs
    "smart_attendance.view_corruptedlog": "View Corrupted Logs",
    "smart_attendance.add_corruptedlog": "Create Corrupted Logs",
    "smart_attendance.change_corruptedlog": "Edit Corrupted Logs",
    "smart_attendance.delete_corruptedlog": "Delete Corrupted Logs",
    # Device Sync History
    "smart_attendance.view_devicesynchnistory": "View Device Sync History",
    "smart_attendance.add_devicesynchnistory": "Create Device Sync History",
    "smart_attendance.change_devicesynchnistory": "Edit Device Sync History",
    "smart_attendance.delete_devicesynchnistory": "Delete Device Sync History",
    "smart_attendance.view_attendance_dashboard": "View Attendance Dashboard",
    "smart_attendance.view_devicesynchistory": "View Device Sync History",
    "smart_attendance.add_devicesynchistory": "Create Device Sync History",
    "smart_attendance.change_devicesynchistory": "Edit Device Sync History",
    "smart_attendance.delete_devicesynchistory": "Delete Device Sync History",

    # =============================================================================
    # DOCUMENTS - Upload, Process, Tax Reports
    # =============================================================================
    "documents.view_document": "View Documents",
    "documents.add_document": "Upload Documents",
    "documents.change_document": "Edit Documents",
    "documents.delete_document": "Delete Documents",
    "documents.process_document": "Process Documents",
    "documents.view_documentprocessingstatus": "View Document Processing Status",
    "documents.reprocess_document": "Reprocess Documents",
    "documents.download_document": "Download Documents",
    "documents.print_document": "Print Documents",
    "documents.view_tax_report": "View Tax Reports",
    # Document Pages
    "documents.view_documentpage": "View Document Pages",
    "documents.add_documentpage": "Create Document Pages",
    "documents.change_documentpage": "Edit Document Pages",
    "documents.delete_documentpage": "Delete Document Pages",

    # =============================================================================
    # NOTIFICATIONS
    # =============================================================================
    "notifications.view_notification": "View Notifications",
    "notifications.add_notification": "Create Notifications",
    "notifications.change_notification": "Edit Notifications",
    "notifications.delete_notification": "Delete Notifications",
    "notifications.mark_notification_read": "Mark Notifications as Read",
    "notifications.mark_all_notifications_read": "Mark All Notifications as Read",
    "notifications.clear_notifications": "Clear All Notifications",

    # =============================================================================
    # CORE / COMPANY - Profile, Bank Accounts
    # =============================================================================
    "core.view_companyprofile": "View Company Profile",
    "core.add_companyprofile": "Create Company Profile",
    "core.change_companyprofile": "Edit Company Profile",
    "core.delete_companyprofile": "Delete Company Profile",
    "core.view_bankaccount": "View Bank Accounts",
    "core.add_bankaccount": "Create Bank Accounts",
    "core.change_bankaccount": "Edit Bank Accounts",
    "core.delete_bankaccount": "Delete Bank Accounts",
    "core.set_default_bankaccount": "Set Default Bank Account",
    # Dashboard
    "core.view_dashboard": "View Dashboard",
    "core.view_dashboard_metrics": "View Dashboard Metrics",
    "core.export_dashboard_data": "Export Dashboard Data",
    # Account
    "core.view_account": "View Account",
    "core.add_account": "Create Account",
    "core.change_account": "Edit Account",
    "core.delete_account": "Delete Account",
    # User Activity
    "core.view_useractivity": "View User Activity",
    "core.add_useractivity": "Create User Activity",
    "core.change_useractivity": "Edit User Activity",
    "core.delete_useractivity": "Delete User Activity",
    # Dashboard Settings
    "core.view_dashboardsettings": "View Dashboard Settings",
    "core.add_dashboardsettings": "Create Dashboard Settings",
    "core.change_dashboardsettings": "Edit Dashboard Settings",
    "core.delete_dashboardsettings": "Delete Dashboard Settings",

    # =============================================================================
    # ACCOUNTS / SECURITY & USERS
    # =============================================================================
    "accounts.view_user": "View Users",
    "accounts.add_user": "Create Users",
    "accounts.change_user": "Edit Users",
    "accounts.delete_user": "Delete Users",
    "accounts.view_subuser": "View Team Members",
    "accounts.add_subuser": "Create Team Members",
    "accounts.change_subuser": "Edit Team Members",
    "accounts.delete_subuser": "Delete Team Members",
    "accounts.view_useractivity": "View User Activity",
    "accounts.add_useractivity": "Create User Activity",
    "accounts.change_useractivity": "Edit User Activity",
    "accounts.delete_useractivity": "Delete User Activity",
    "accounts.view_activity_log": "View Activity Log",
    "accounts.view_usersession": "View Sessions",
    "accounts.change_usersession": "Terminate Sessions",
    "accounts.view_accountgroup": "View Roles",
    "accounts.add_accountgroup": "Create Roles",
    "accounts.change_accountgroup": "Edit Roles",
    "accounts.delete_accountgroup": "Delete Roles",
    # User Profile
    "accounts.view_userprofile": "View User Profile",
    "accounts.change_userprofile": "Edit Own Profile",
    "accounts.change_user_password": "Change User Password",
    "accounts.force_password_change": "Force Password Change",
    # Session Management
    "accounts.logout_session": "Logout Session",
    "accounts.logout_all_sessions": "Logout All Sessions",
    "accounts.add_usersession": "Create Sessions",
    "accounts.delete_usersession": "Delete Sessions",

    # =============================================================================
    # AUTH / ROLES & PERMISSIONS - Groups and Permissions (Superuser Only)
    # =============================================================================
    "auth.view_group": "View Groups",
    "auth.add_group": "Create Groups",
    "auth.change_group": "Edit Groups",
    "auth.delete_group": "Delete Groups",
    "auth.view_permission": "View Permissions",
    "auth.add_permission": "Create Permissions",
    "auth.change_permission": "Edit Permissions",
    "auth.delete_permission": "Delete Permissions",

    # =============================================================================
    # REPORTS - Tax Reports, Financial Reports
    # =============================================================================
    "reports.view_tax_report": "View Tax Reports",
    "reports.add_tax_report": "Create Tax Reports",
    "reports.change_tax_report": "Edit Tax Reports",
    "reports.delete_tax_report": "Delete Tax Reports",
    "reports.export_tax_report": "Export Tax Reports",
    "reports.view_monthly_report": "View Monthly Reports",
    "reports.view_quarterly_report": "View Quarterly Reports",
    "reports.view_annual_report": "View Annual Reports",
    "reports.view_profit_and_loss": "View Profit and Loss",
    "reports.view_balance_sheet": "View Balance Sheet",
    "reports.view_tax_history": "View Tax History",

    # =============================================================================
    # TAX ENGINE
    # =============================================================================
    "tax_engine.view_taxrecord": "View Tax Records",
    "tax_engine.add_taxrecord": "Create Tax Records",
    "tax_engine.change_taxrecord": "Edit Tax Records",
    "tax_engine.delete_taxrecord": "Delete Tax Records",
    "tax_engine.compute_tax": "Compute Tax",

    # =============================================================================
    # VIDEO CALLS & RECORDINGS
    # =============================================================================
    "videocalls.view_videocallroom": "View Video Call Rooms",
    "videocalls.add_videocallroom": "Create Video Call Rooms",
    "videocalls.change_videocallroom": "Edit Video Call Rooms",
    "videocalls.delete_videocallroom": "Delete Video Call Rooms",
    "videocalls.view_callrecording": "View Call Recordings",
    "videocalls.add_callrecording": "Create Call Recordings",
    "videocalls.change_callrecording": "Edit Call Recordings",
    "videocalls.delete_callrecording": "Delete Call Recordings",
    "videocalls.view_callsession": "View Call Sessions",
    "videocalls.add_callsession": "Create Call Sessions",
    "videocalls.view_signalmessage": "View Signal Messages",
    "videocalls.add_signalmessage": "Send Signal Messages",
    "videocalls.view_scheduledmeeting": "View Scheduled Meetings",
    "videocalls.add_scheduledmeeting": "Create Scheduled Meetings",
    "videocalls.change_scheduledmeeting": "Edit Scheduled Meetings",
    "videocalls.delete_scheduledmeeting": "Delete Scheduled Meetings",
    "videocalls.view_meetinginvitation": "View Meeting Invitations",
    "videocalls.add_meetinginvitation": "Create Meeting Invitations",
    "videocalls.view_jitsiroom": "View Jitsi Rooms",
    "videocalls.add_jitsiroom": "Create Jitsi Rooms",
    "videocalls.change_jitsiroom": "Edit Jitsi Rooms",
    "videocalls.delete_jitsiroom": "Delete Jitsi Rooms",
    "videocalls.view_jitsiparticipant": "View Jitsi Participants",
    "videocalls.add_jitsiparticipant": "Add Jitsi Participants",
    "videocalls.view_jitsirecording": "View Jitsi Recordings",
    "videocalls.add_jitsirecording": "Create Jitsi Recordings",
    "videocalls.delete_jitsirecording": "Delete Jitsi Recordings",
    "videocalls.access_videocalls": "Access Video Calls Module",
    "videocalls.view_callparticipant": "View Call Participants",
    "videocalls.add_callparticipant": "Add Call Participants",
    "videocalls.change_callparticipant": "Edit Call Participants",
    "videocalls.delete_callparticipant": "Delete Call Participants",
    "videocalls.change_callsession": "Edit Call Sessions",
    "videocalls.delete_callsession": "Delete Call Sessions",
    "videocalls.change_jitsiparticipant": "Edit Jitsi Participants",
    "videocalls.delete_jitsiparticipant": "Delete Jitsi Participants",
    "videocalls.change_jitsirecording": "Edit Jitsi Recordings",
    "videocalls.change_meetinginvitation": "Edit Meeting Invitations",
    "videocalls.delete_meetinginvitation": "Delete Meeting Invitations",
    "videocalls.change_signalmessage": "Edit Signal Messages",
    "videocalls.delete_signalmessage": "Delete Signal Messages",
    "videocalls.view_videocall": "View Video Calls",
    "videocalls.create_videocall": "Create Video Calls",
    "videocalls.manage_videocall": "Manage Video Calls",
    "videocalls.record_videocall": "Record Video Calls",

    # =============================================================================
    # AI ENGINE & EXTRACTION
    # =============================================================================
    "ai_engine.view_aianalysis": "View AI Analysis",
    "ai_engine.add_aianalysis": "Create AI Analysis",
    "ai_engine.change_aianalysis": "Edit AI Analysis",
    "ai_engine.delete_aianalysis": "Delete AI Analysis",
    "extraction.view_extraction": "View Extractions",
    "extraction.add_extraction": "Create Extractions",
    "extraction.change_extraction": "Edit Extractions",
    "extraction.delete_extraction": "Delete Extractions",
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
        if perm.content_type.model in {
            'invoicemovement',
            'storemovement',
            'inventorymovement',
            'waybillmovement',
        }:
            continue
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
