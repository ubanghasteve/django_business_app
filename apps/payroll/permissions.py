"""
Smart Payroll Permissions
====================
RBAC permissions for payroll records.
"""

from rest_framework import permissions
from apps.core.permissions import DjangoModelPermissions


class PayrollModelPermissions(DjangoModelPermissions):
    """
    DRF permission class for payroll models.
    Extends DjangoModelPermissions to plug into existing RBAC.
    """
    
    perms_map = {
        'GET': ['%(app_label)s.view_%(model_name)s'],
        'HEAD': ['%(app_label)s.view_%(model_name)s'],
        'POST': ['%(app_label)s.add_%(model_name)s'],
        'PUT': ['%(app_label)s.change_%(model_name)s'],
        'PATCH': ['%(app_label)s.change_%(model_name)s'],
        'DELETE': ['%(app_label)s.delete_%(model_name)s'],
    }


class IsCompanyAdminOrPayrollPermission(permissions.BasePermission):
    """
    Allow if user is company admin or has the required payroll.* permission.
    Intended for FBV checks via @permission_classes on non-ModelViewSet APIs.
    """
    
    def has_permission(self, request, view):
        from apps.core.ownership import is_company_admin

        user = request.user
        if not user or not user.is_authenticated:
            return False
        if is_company_admin(user, request):
            return True
        required = getattr(view, "required_permissions", [])
        if not required:
            return True
        return any(user.has_perm(p) for p in required)


class CanViewPayrollRecord(permissions.BasePermission):
    """
    Permission to view payroll records.
    """
    
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        
        from apps.core.ownership import is_company_admin
        if is_company_admin(user, request):
            return True
        
        return user.has_perm('payroll.view_payroll_record')


class CanAddPayrollRecord(permissions.BasePermission):
    """
    Permission to add payroll records.
    """
    
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        
        from apps.core.ownership import is_company_admin
        if is_company_admin(user, request):
            return True
        
        return user.has_perm('payroll.add_payroll_record')


class CanChangePayrollRecord(permissions.BasePermission):
    """
    Permission to change payroll records.
    """
    
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        
        from apps.core.ownership import is_company_admin
        if is_company_admin(user, request):
            return True
        
        return user.has_perm('payroll.change_payroll_record')


class CanDeletePayrollRecord(permissions.BasePermission):
    """
    Permission to delete payroll records.
    """
    
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        
        from apps.core.ownership import is_company_admin
        if is_company_admin(user, request):
            return True
        
        return user.has_perm('payroll.delete_payroll_record')


class CanViewPayrollCategory(permissions.BasePermission):
    """
    Permission to view payroll categories.
    """
    
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        
        from apps.core.ownership import is_company_admin
        if is_company_admin(user, request):
            return True
        
        return user.has_perm('payroll.view_payroll_category')


class CanAddPayrollCategory(permissions.BasePermission):
    """
    Permission to add payroll categories.
    """
    
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        
        from apps.core.ownership import is_company_admin
        if is_company_admin(user, request):
            return True
        
        return user.has_perm('payroll.add_payroll_category')


class CanChangePayrollCategory(permissions.BasePermission):
    """
    Permission to change payroll categories.
    """
    
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        
        from apps.core.ownership import is_company_admin
        if is_company_admin(user, request):
            return True
        
        return user.has_perm('payroll.change_payroll_category')


class CanDeletePayrollCategory(permissions.BasePermission):
    """
    Permission to delete payroll categories.
    """
    
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        
        from apps.core.ownership import is_company_admin
        if is_company_admin(user, request):
            return True
        
        return user.has_perm('payroll.delete_payroll_category')


PAYROLL_PERMISSIONS = {
    'payroll.view_payroll_record': 'View Payroll Records',
    'payroll.add_payroll_record': 'Add Payroll Records',
    'payroll.change_payroll_record': 'Change Payroll Records',
    'payroll.delete_payroll_record': 'Delete Payroll Records',
    'payroll.view_payroll_category': 'View Payroll Categories',
    'payroll.add_payroll_category': 'Add Payroll Categories',
    'payroll.change_payroll_category': 'Change Payroll Categories',
    'payroll.delete_payroll_category': 'Delete Payroll Categories',
    'payroll.verify_payroll_record': 'Verify Payroll Records',
    'payroll.approve_payroll_record': 'Approve Payroll Records',
    'payroll.share_payroll_record': 'Share Payroll Records',
    'payroll.view_payroll_access_logs': 'View Payroll Access Logs',
    'payroll.view_payroll_analytics': 'View Payroll Analytics',
}


def get_payroll_permissions():
    """Get all payroll permissions with their descriptions."""
    return PAYROLL_PERMISSIONS


def assign_default_payroll_permissions(role, role_type='member'):
    """
    Assign default payroll permissions based on role type.
    
    Args:
        role: The role to assign permissions to
        role_type: Type of role ('admin', 'manager', 'member')
    """
    from apps.accounts.models import RolePermission
    
    if role_type == 'admin':
        permissions_to_assign = [
            'payroll.view_payroll_record',
            'payroll.add_payroll_record',
            'payroll.change_payroll_record',
            'payroll.delete_payroll_record',
            'payroll.view_payroll_category',
            'payroll.add_payroll_category',
            'payroll.change_payroll_category',
            'payroll.delete_payroll_category',
            'payroll.verify_payroll_record',
            'payroll.approve_payroll_record',
            'payroll.share_payroll_record',
            'payroll.view_payroll_access_logs',
            'payroll.view_payroll_analytics',
        ]
    elif role_type == 'manager':
        permissions_to_assign = [
            'payroll.view_payroll_record',
            'payroll.add_payroll_record',
            'payroll.change_payroll_record',
            'payroll.verify_payroll_record',
            'payroll.share_payroll_record',
            'payroll.view_payroll_analytics',
        ]
    else:
        permissions_to_assign = [
            'payroll.view_payroll_record',
        ]
    
    for perm in permissions_to_assign:
        RolePermission.objects.get_or_create(
            role=role,
            permission=perm,
            defaults={'is_active': True}
        )
