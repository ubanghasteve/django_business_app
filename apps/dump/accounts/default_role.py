"""
Default onboarding role: locked-down access for newly registered users.

SECURITY: All newly registered users are automatically assigned to this role only.
They cannot access invoices, expenses, receipts, quotations, waybills, inventory,
job orders, security/roles, or user management until a superuser explicitly
assigns them an elevated role (e.g. Company Admin).

This is the default onboarding role — minimal access by design.
"""
from .permission_labels import PERMISSION_LABELS

# Role name used for the default locked-down group (Django Group via AccountGroup).
DEFAULT_ONBOARDING_ROLE_NAME = "Company Profile Viewer"

# Company Admin: role name and full-permission template (NOT stored in DB as a shared group).
# Used only to populate account-scoped Company Admin groups (one per account).
COMPANY_ADMIN_ROLE_NAME = "Company Admin"

# Company Read Only: strict read-only role. When an AccountGroup has this role_name,
# its Group permissions are enforced to only view_* (no add/change/delete) via signal.
COMPANY_READ_ONLY_ROLE_NAME = "Company Read Only"
COMPANY_ADMIN_PERMISSION_CODENAMES = list(PERMISSION_LABELS.keys())

# Only these permissions are granted to the default role. No other app permissions.
# - core.view_companyprofile: view company profile (name, address, logo, contact details).
# - Own profile and sign out use @login_required only (no permission), so no extra perm needed.
DEFAULT_ONBOARDING_PERMISSION_CODENAMES = [
    "core.view_companyprofile",
]

# Permissions explicitly forbidden for this role (documentation only; enforced by not granting them):
# - Invoices, Expenses, Receipts, Quotations, Waybills, Inventory, Job orders
# - Security / roles / permissions (auth.view_group, auth.change_group, etc.)
# - User or team management (accounts.view_subuser, accounts.view_accountgroup, etc.)
# - Any other business modules (clients, accounting, etc.)
#
# NOTE: No "Approved Company" role. Approval only controls access gating (middleware).
# Companies must manually create roles, assign permissions, and assign users.
