"""
Permission mapping: which permissions are required to see notifications from each app.
Aligns with apps.core.feature_permissions for consistency.
Users only see notifications from apps they have access to.
"""
from apps.core.feature_permissions import (
    NAV_MESSAGING,
    NAV_HR_STAFF,
    NAV_INVENTORY,
    NAV_EXPENSE,
    NAV_REQUISITIONS,
    NAV_INVOICES,
    NAV_QUOTATIONS,
    NAV_RECEIPTS,
    NAV_WAYBILLS,
    NAV_CLIENTS,
    NAV_JOB_ORDERS,
    NAV_STAFF_OFFENCES,
    NAV_STORE,
    NAV_PAYROLL,
    NAV_DOCUMENTS,
    NAV_SMART_ATTENDANCE,
    NAV_VIDEO_CALLS,
    NAV_MAILING,
    NAV_ACCOUNTING,
)

# source_app -> tuple of permission codenames (user needs ANY of these to see notifications)
# Automatically detects roles: Company Admin sees all; Team members & Employees see only apps they have permission for
SOURCE_APP_PERMISSIONS = {
    'messaging': NAV_MESSAGING,
    'hr_staff': NAV_HR_STAFF + ('hr_staff.view_employee',),  # Include view_employee so HR roles see HR notifications
    'inventory': NAV_INVENTORY,
    'expense': NAV_EXPENSE,
    'requisitions': NAV_REQUISITIONS,
    'invoices': NAV_INVOICES,
    'quotations': NAV_QUOTATIONS,
    'waybills': NAV_WAYBILLS,
    'receipts': NAV_RECEIPTS,
    'clients': NAV_CLIENTS,
    'job_orders': NAV_JOB_ORDERS,
    'staff_offences': NAV_STAFF_OFFENCES,
    'store': NAV_STORE,
    'payroll': NAV_PAYROLL,
    'documents': NAV_DOCUMENTS,
    'smart_attendance': NAV_SMART_ATTENDANCE,
    'videocalls': NAV_VIDEO_CALLS,
    'mailing': NAV_MAILING,
    'accounting': NAV_ACCOUNTING,
    'system': (),  # System notifications visible to all authenticated users
}


def user_can_see_app_notifications(user, source_app, request=None):
    """
    True if the user has permission to see notifications from this source app.
    Automatically detects: Company Admin (sees all), Team Members (by role permissions),
    Employees (by view_own_hr_dashboard), Superuser (sees all).
    """
    if not user or not getattr(user, 'is_authenticated', True):
        return False
    if user.is_superuser:
        return True
    from apps.core.ownership import is_company_admin
    if is_company_admin(user, request):
        return True
    perms = SOURCE_APP_PERMISSIONS.get(source_app, ())
    if not perms:
        return True  # No permission required (e.g. system)
    return any(user.has_perm(p) for p in perms)


def get_allowed_source_apps_for_user(user, request=None):
    """Return list of source_app values the user can see notifications for."""
    return [src for src in SOURCE_APP_PERMISSIONS if user_can_see_app_notifications(user, src, request)]
