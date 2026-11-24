from django.conf import settings

from .utils import get_company_context, get_company_profile_for_user


def rbac_context(request):
    """
    Permission-based context for UI visibility. All flags use Django model permissions;
    do not use is_staff or role names for authorization.

    - user_can_manage_users: can access Team Members / Security / Roles (view_subuser or view_accountgroup).
    - user_can_access_company_profile: can view company profile and bank accounts.
    - show_request_full_access_cta: True only for authenticated users who have company profile
      access but no elevated permissions (invoices, job_orders, etc.); hidden for superuser/staff.
    - user_can_edit / user_can_delete: deprecated; templates should use perms.<app>.<change_|delete_><model> instead.
    """
    if not request.user.is_authenticated:
        return {
            'user_can_edit': False,
            'user_can_delete': False,
            'user_can_manage_users': False,
            'user_can_access_company_profile': False,
            'show_request_full_access_cta': False,
            'show_approved_assign_role_notice': False,
            'show_contact_developer_in_footer': False,
            'account_is_approved': True,
            'account_has_full_access': True,
            'is_company_admin': False,
            'is_read_only_user': False,
            'show_created_by': False,
            'is_employee_portal': False,
        }
    user = request.user
    from apps.accounts.rbac import is_account_owner
    is_owner = is_account_owner(request)
    # Employee portal users (non-owners linked to an Employee) should not see Company Profile / Bank details.
    # Even if they are accidentally given core.view_companyprofile/change_companyprofile, UI must hide these.
    is_employee_portal = _user_has_linked_employee(user) and not is_owner
    has_company_profile = (
        not is_employee_portal and (
            is_owner or
            user.has_perm('core.view_companyprofile') or
            user.has_perm('core.change_companyprofile')
        )
    )
    account = getattr(user, 'account', None)
    account_is_approved = getattr(account, 'is_approved', True) if account else True
    from .utils import account_has_full_access
    account_full_access = account_has_full_access(account) if account else True
    # Account owner (company admin) always has full access — no approval or role notices
    if account and getattr(account, 'owner_id', None) and user.id == account.owner_id:
        account_full_access = True
    from apps.core.mixins import is_read_only_user
    user_is_read_only = is_read_only_user(user)
    has_elevated = False
    if has_company_profile and not (user.is_superuser or user.is_staff) and account_full_access:
        from .feature_permissions import ELEVATED_PERMISSIONS
        has_elevated = any(user.has_perm(p) for p in ELEVATED_PERMISSIONS)
    # Unapproved + no elevated: show "Request Full Access" (contact admin for approval). Never for account owner.
    show_request_full_access_cta = (
        not is_owner and not account_is_approved and has_company_profile and not has_elevated and not (user.is_superuser or user.is_staff)
    )
    # Approved + no elevated: show "assign yourself a role" notice. Never for account owner.
    show_approved_assign_role_notice = (
        not is_owner and account_is_approved and has_company_profile and not has_elevated and not (user.is_superuser or user.is_staff)
    )
    # Show "Contact the developer" in dashboard footer for all authenticated users (every role).
    show_contact_developer_in_footer = True
    return {
        'user_can_edit': False,
        'user_can_delete': False,
        'user_can_manage_users': (
            account_full_access and
            (user.has_perm('accounts.view_subuser') or user.has_perm('accounts.view_accountgroup'))
        ),
        'user_can_access_company_profile': has_company_profile,
        'show_request_full_access_cta': show_request_full_access_cta,
        'show_approved_assign_role_notice': show_approved_assign_role_notice,
        'show_contact_developer_in_footer': show_contact_developer_in_footer,
        'account_is_approved': account_is_approved,
        'account_has_full_access': account_full_access,
        'is_company_admin': is_owner,
        'is_read_only_user': user_is_read_only,
        # Show "Created by" when user sees all company records (admin or read-only)
        'show_created_by': is_owner or user_is_read_only,
        # Employee portal: user has linked Employee record (sees only own data in HR)
        'is_employee_portal': is_employee_portal,
    }


def _user_has_linked_employee(user):
    """True if user is linked to an Employee (portal user). Used for nav to show My Dashboard."""
    if not user or not getattr(user, 'is_authenticated', True):
        return False
    try:
        from apps.hr_staff.models import Employee
        return Employee.objects.filter(linked_user=user).exists()
    except Exception:
        return False


def company_context(request):
    """
    Context processor to make company data available in all templates.

    Uses get_company_profile_for_user(user, request) so team members (SubUser)
    resolve to the same company as the account owner. request is passed for
    session-based fallback when sub_user_id is set.
    """
    if request.user.is_authenticated:
        from .utils import get_company_profile_for_user
        company_profile = get_company_profile_for_user(request.user, request)
        if company_profile:
            currency_symbol = getattr(company_profile, 'currency_symbol', None) or '$'
            ctx = {
                'company_profile': company_profile,
                'company_logo': company_profile.logo.url if company_profile.logo else None,
                'company_signature': company_profile.signature.url if company_profile.signature else None,
                'currency_symbol': currency_symbol,
                'currency_code': getattr(company_profile, 'currency_code', None) or 'USD',
                'user_currency_symbol': currency_symbol,  # HR & Staff and others: always use company admin currency (updates on refresh)
                'theme_primary_color': getattr(company_profile, 'primary_color', '#1976d2') or '#1976d2',
                'theme_secondary_color': getattr(company_profile, 'secondary_color', '#f8f9fa') or '#f8f9fa',
                'theme_accent_color': getattr(company_profile, 'accent_color', '#e9ecef') or '#e9ecef',
                'theme_text_color': getattr(company_profile, 'text_color', '#333333') or '#333333',
            }
        else:
            ctx = {
                'company_profile': None,
                'company_logo': None,
                'company_signature': None,
                'currency_symbol': '$',
                'currency_code': 'USD',
                'user_currency_symbol': '$',
                'theme_primary_color': '#1976d2',
                'theme_secondary_color': '#f8f9fa',
                'theme_accent_color': '#e9ecef',
                'theme_text_color': '#333333',
            }
        ctx['current_sub_user'] = getattr(request.user, 'linked_subuser', None)
        ctx['request_company'] = company_profile  # Single source: request.company equivalent
        return ctx
    
    return {
        'company_profile': None,
        'company_logo': None,
        'company_signature': None,
        'currency_symbol': '$',
        'currency_code': 'USD',
        'user_currency_symbol': '$',
        'current_sub_user': None,
        'request_company': None,
        # Default theme colors for unauthenticated users
        'theme_primary_color': '#1976d2',
        'theme_secondary_color': '#f8f9fa',
        'theme_accent_color': '#e9ecef',
        'theme_text_color': '#333333',
    }


def app_settings(request):
    """
    Context processor for general app settings
    
    Args:
        request: Django request object
    
    Returns:
        dict: App settings context
    """
    return {
        'app_name': 'Multi-Purpose Business App',
        'app_version': '1.0.0',
        'support_email': 'support@example.com',
        'max_file_upload_size': '5MB',
        'allowed_image_types': ['JPG', 'PNG', 'GIF', 'WebP'],
    }


def navigation_context(request):
    """
    Context processor for navigation data
    
    Args:
        request: Django request object
    
    Returns:
        dict: Navigation context
    """
    if not request.user.is_authenticated:
        return {}
    
    # Check if company profile exists (for owner or team member via account)
    has_company_profile = get_company_profile_for_user(request.user, request) is not None
    
    navigation_items = [
        {
            'name': 'Dashboard',
            'url': 'core:dashboard',
            'icon': 'fas fa-tachometer-alt',
            'active': request.resolver_match.url_name == 'dashboard' if request.resolver_match else False
        },
        {
            'name': 'Company Profile',
            'url': 'core:company_profile',
            'icon': 'fas fa-building',
            'active': request.resolver_match.url_name in ['company_profile'] if request.resolver_match else False,
            'badge': 'Setup Required' if not has_company_profile else None,
            'badge_class': 'badge-warning' if not has_company_profile else None
        },
        {
            'name': 'Bank Accounts',
            'url': 'core:bank_accounts',
            'icon': 'fas fa-university',
            'active': request.resolver_match.url_name in ['bank_accounts', 'edit_bank_account'] if request.resolver_match else False
        },
    ]
    user = request.user
    from apps.accounts.rbac import is_account_owner
    # Show Company Profile / Bank Accounts to account owner or user with view or edit permission.
    # Employee portal users (non-owners linked to an Employee) should never see these, even if misconfigured with perms.
    if not (is_account_owner(request) or user.has_perm('core.view_companyprofile') or user.has_perm('core.change_companyprofile')):
        navigation_items = [it for it in navigation_items if it['url'] not in ('core:company_profile', 'core:bank_accounts')]
    if _user_has_linked_employee(user) and not is_account_owner(request):
        navigation_items = [it for it in navigation_items if it['url'] not in ('core:company_profile', 'core:bank_accounts')]
    # App-specific items: show only when user has view permission for that app.
    # Applies to company admin and team members (including Company Read Only): no app in sidenav/dashboard unless the user has the corresponding view permission.
    from .utils import account_has_full_access
    from .feature_permissions import (
        NAV_CLIENTS, NAV_INVOICES, NAV_QUOTATIONS, NAV_RECEIPTS, NAV_JOB_ORDERS,
        NAV_WAYBILLS, NAV_REQUISITIONS, NAV_STAFF_OFFENCES, NAV_STORE, NAV_INVENTORY, NAV_EXPENSE, NAV_ACCOUNTING, NAV_MESSAGING,
        NAV_MAILING, NAV_HR_STAFF, NAV_SMART_ATTENDANCE, NAV_PAYROLL, NAV_VIDEO_CALLS,
    )
    account = getattr(user, 'account', None)
    account_is_approved = getattr(account, 'is_approved', True) if account else True
    owner_is_approved_company_admin = (
        account and getattr(account, 'owner_id', None) and user.id == account.owner_id and account_is_approved
    )
    # App links: show for superuser, approved company admin, or approved account with full access.
    if getattr(user, 'is_superuser', False) or owner_is_approved_company_admin or (has_company_profile and account_has_full_access(account)):
        additional_specs = [
            ('Clients', 'clients:client_list', 'fas fa-users', 'clients', NAV_CLIENTS),
            ('Invoices', 'invoices:list', 'fas fa-file-invoice', 'invoices', NAV_INVOICES),
            ('Quotations', 'quotations:quotation_list', 'fas fa-file-contract', 'quotations', NAV_QUOTATIONS),
            ('Receipts', 'receipts:list', 'fas fa-receipt', 'receipts', NAV_RECEIPTS),
            ('Job Orders', 'job_orders:products', 'fas fa-clipboard-list', 'job_orders', NAV_JOB_ORDERS),
            ('Waybills', 'waybills:list', 'fas fa-truck', 'waybills', NAV_WAYBILLS),
            ('Requisitions', 'requisitions:list', 'fas fa-clipboard-list', 'requisitions', NAV_REQUISITIONS),
            ('Staff Offences', 'staff_offences:list', 'fas fa-exclamation-triangle', 'staff_offences', NAV_STAFF_OFFENCES),
            ('Store', 'store:list', 'fas fa-store', 'store', NAV_STORE),
            ('Inventory', 'inventory:list', 'fas fa-boxes', 'inventory', NAV_INVENTORY),
            ('Expense', 'expense:list', 'fas fa-money-bill-wave', 'expense', NAV_EXPENSE),
            ('Accounting', 'accounting:dashboard', 'fas fa-calculator', 'accounting', NAV_ACCOUNTING),
            ('Messaging', 'messaging:inbox', 'fas fa-comments', 'messaging', NAV_MESSAGING),
            ('Bulk Mailing', 'mailing:bulk_send', 'fas fa-paper-plane', 'mailing', NAV_MAILING),
            ('HR & Staff', 'hr_staff:dashboard', 'fas fa-user-tie', 'hr_staff', NAV_HR_STAFF),
            ('Attendance', 'smart_attendance:dashboard', 'fas fa-user-check', 'smart_attendance', NAV_SMART_ATTENDANCE),
            ('Payroll', 'payroll:dashboard', 'fas fa-file-invoice', 'payroll', NAV_PAYROLL),
            ('Video Calls', 'videocalls:lobby', 'fas fa-users', 'videocalls', NAV_VIDEO_CALLS),
        ]
        # Full HR dashboard for users with view_hr_dashboard; employee portal only when they have view_own_hr_dashboard only and linked employee
        hr_url = 'hr_staff:employee_portal_dashboard' if (_user_has_linked_employee(user) and not user.has_perm('hr_staff.view_hr_dashboard')) else 'hr_staff:dashboard'
        for name, url, icon, namespace, perms in additional_specs:
            if any(user.has_perm(p) for p in perms):
                use_url = hr_url if namespace == 'hr_staff' else url
                navigation_items.append({
                    'name': name,
                    'url': use_url,
                    'icon': icon,
                    'active': request.resolver_match.namespace == namespace if request.resolver_match else False
                })
    # HR & Staff: explicit access by view_hr_dashboard OR view_own_hr_dashboard (no Full Company Visibility).
    # Show link even when user does not have full account access (e.g. employee with view_own_hr_dashboard only).
    if (user.has_perm('hr_staff.view_hr_dashboard') or user.has_perm('hr_staff.view_own_hr_dashboard')) and not any(
        it.get('url', '').startswith('hr_staff:') for it in navigation_items
    ):
        hr_nav_url = 'hr_staff:employee_portal_dashboard' if _user_has_linked_employee(user) and not user.has_perm('hr_staff.view_hr_dashboard') else 'hr_staff:dashboard'
        navigation_items.append({
            'name': 'HR & Staff',
            'url': hr_nav_url,
            'icon': 'fas fa-user-tie',
            'active': request.resolver_match.namespace == 'hr_staff' if request.resolver_match else False
        })

    return {
        'navigation_items': navigation_items,
        'has_company_profile': has_company_profile,
    }


def breadcrumb_context(request):
    """
    Context processor for breadcrumb navigation
    
    Args:
        request: Django request object
    
    Returns:
        dict: Breadcrumb context
    """
    breadcrumbs = [
        {'name': 'Home', 'url': 'core:dashboard'}
    ]
    
    if request.resolver_match:
        url_name = request.resolver_match.url_name
        namespace = request.resolver_match.namespace
        
        # Add breadcrumbs based on current page
        if namespace == 'core':
            if url_name == 'company_profile':
                breadcrumbs.append({'name': 'Company Profile', 'url': None})
            elif url_name in ['bank_accounts', 'edit_bank_account', 'delete_bank_account']:
                breadcrumbs.append({'name': 'Bank Accounts', 'url': 'core:bank_accounts'})
                if url_name == 'edit_bank_account':
                    breadcrumbs.append({'name': 'Edit', 'url': None})
                elif url_name == 'delete_bank_account':
                    breadcrumbs.append({'name': 'Delete', 'url': None})
        elif namespace == 'inventory':
            breadcrumbs.append({'name': 'Inventory', 'url': 'inventory:list'})
            if url_name == 'list':
                breadcrumbs.append({'name': 'Inventory', 'url': None})
            elif url_name == 'dashboard':
                breadcrumbs.append({'name': 'Dashboard', 'url': None})
            elif url_name == 'inventory_list':
                breadcrumbs.append({'name': 'Products', 'url': None})
            elif url_name == 'inventory_create':
                breadcrumbs.append({'name': 'Add Product', 'url': None})
            elif url_name == 'inventory_update':
                breadcrumbs.append({'name': 'Edit Product', 'url': None})
            elif url_name == 'category_list':
                breadcrumbs.append({'name': 'Categories', 'url': None})
            elif url_name == 'custom_form_list':
                breadcrumbs.append({'name': 'Custom Forms', 'url': None})
            elif url_name == 'inventory_import':
                breadcrumbs.append({'name': 'Import', 'url': None})
            elif url_name == 'inventory_export':
                breadcrumbs.append({'name': 'Export', 'url': None})
        elif namespace == 'expense':
            breadcrumbs.append({'name': 'Expense', 'url': 'expense:list'})
            if url_name == 'list':
                breadcrumbs.append({'name': 'Expense', 'url': None})
            elif url_name == 'dashboard':
                breadcrumbs.append({'name': 'Dashboard', 'url': None})
            elif url_name == 'expense_list':
                breadcrumbs.append({'name': 'List', 'url': None})
            elif url_name == 'expense_create':
                breadcrumbs.append({'name': 'Add', 'url': None})
            elif url_name == 'expense_update':
                breadcrumbs.append({'name': 'Edit', 'url': None})
        elif namespace == 'hr_staff':
            # Full HR users → general dashboard; employee-portal only → portal dashboard
            hr_staff_url = 'hr_staff:dashboard' if (request.user.is_authenticated and request.user.has_perm('hr_staff.view_hr_dashboard')) else 'hr_staff:employee_portal_dashboard'
            breadcrumbs.append({'name': 'HR & Staff', 'url': hr_staff_url})
            if url_name == 'dashboard':
                breadcrumbs.append({'name': 'Dashboard', 'url': None})
            elif url_name == 'employee_portal_dashboard':
                breadcrumbs.append({'name': 'My dashboard', 'url': None})
            elif url_name == 'employee_list':
                breadcrumbs.append({'name': 'Employees', 'url': None})
            elif url_name == 'employee_detail':
                breadcrumbs.append({'name': 'Employee', 'url': None})
            elif url_name == 'employee_create':
                breadcrumbs.append({'name': 'Add Employee', 'url': None})
            elif url_name == 'employee_edit':
                breadcrumbs.append({'name': 'Employees', 'url': 'hr_staff:employee_list'})
                breadcrumbs.append({'name': 'Edit', 'url': None})
            elif url_name == 'employee_delete':
                breadcrumbs.append({'name': 'Employees', 'url': 'hr_staff:employee_list'})
                breadcrumbs.append({'name': 'Delete', 'url': None})
            elif url_name == 'department_list':
                breadcrumbs.append({'name': 'Departments', 'url': None})
            elif url_name == 'department_detail':
                breadcrumbs.append({'name': 'Department', 'url': None})
            elif url_name == 'department_create':
                breadcrumbs.append({'name': 'Add Department', 'url': None})
            elif url_name == 'department_edit':
                breadcrumbs.append({'name': 'Departments', 'url': 'hr_staff:department_list'})
                breadcrumbs.append({'name': 'Edit', 'url': None})
            elif url_name == 'department_delete':
                breadcrumbs.append({'name': 'Departments', 'url': 'hr_staff:department_list'})
                breadcrumbs.append({'name': 'Delete', 'url': None})
            elif url_name == 'leave_list':
                leave_label = 'My Leave' if (request.user.is_authenticated and request.user.has_perm('hr_staff.view_own_hr_dashboard') and not request.user.has_perm('hr_staff.view_hr_dashboard')) else 'Leave Requests'
                breadcrumbs.append({'name': leave_label, 'url': None})
            elif url_name == 'leave_detail':
                breadcrumbs.append({'name': 'Leave Request', 'url': None})
            elif url_name == 'leave_create':
                breadcrumbs.append({'name': 'Add Leave Request', 'url': None})
            elif url_name == 'leave_edit':
                leave_list_label = 'My Leave' if (request.user.is_authenticated and request.user.has_perm('hr_staff.view_own_hr_dashboard') and not request.user.has_perm('hr_staff.view_hr_dashboard')) else 'Leave Requests'
                breadcrumbs.append({'name': leave_list_label, 'url': 'hr_staff:leave_list'})
                breadcrumbs.append({'name': 'Edit', 'url': None})
            elif url_name == 'leave_delete':
                leave_del_label = 'My Leave' if (request.user.is_authenticated and request.user.has_perm('hr_staff.view_own_hr_dashboard') and not request.user.has_perm('hr_staff.view_hr_dashboard')) else 'Leave Requests'
                breadcrumbs.append({'name': leave_del_label, 'url': 'hr_staff:leave_list'})
                breadcrumbs.append({'name': 'Delete', 'url': None})
    
    return {
        'breadcrumbs': breadcrumbs
    }


def user_preferences(request):
    """
    Context processor for user preferences and settings
    
    Args:
        request: Django request object
    
    Returns:
        dict: User preferences context
    """
    if not request.user.is_authenticated:
        return {}
    
    # Default preferences - can be extended with UserProfile model later
    preferences = {
        'theme': 'light',  # light, dark
        'sidebar_collapsed': False,
        'language': 'en',
        'timezone': 'UTC',
        'date_format': 'MM/DD/YYYY',
        'time_format': '12h',  # 12h, 24h
        'decimal_places': 2,
        'show_tooltips': True,
    }
    
    return {
        'user_preferences': preferences
    }


def debug_context(request):
    """
    Exposes debug and settings.DEBUG for templates so UI behaves consistently
    across localhost and production. Does not alter RBAC or app logic.
    """
    return {
        'debug': settings.DEBUG,
    }


def currency_context(request):
    """
    Context processor to make currency information available globally
    """
    if request.user.is_authenticated:
        company_context = get_company_context(request.user, request)
        return {
            'user_currency_symbol': company_context['currency_symbol'],
            'user_currency_code': company_context['currency_code'],
            'company_profile': company_context['company_profile'],
        }
    else:
        return {
            'user_currency_symbol': '$',
            'user_currency_code': 'USD',
            'company_profile': None,
        }
