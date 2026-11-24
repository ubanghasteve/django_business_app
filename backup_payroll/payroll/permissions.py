from rest_framework import permissions

from apps.core.permissions import DjangoModelPermissions


class PayrollModelPermissions(DjangoModelPermissions):
    """
    DRF permission class for payroll models.
    Extends DjangoModelPermissions so we can plug into existing RBAC.
    """

    pass


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

