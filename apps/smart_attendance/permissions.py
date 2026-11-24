from rest_framework import permissions


class IsCompanyAdminOrModelPermission(permissions.BasePermission):
    """
    DRF permission that grants access if the user is company admin, otherwise
    falls back to Django model permissions.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        from apps.core.ownership import is_company_admin

        if is_company_admin(request.user, request):
            return True

        from apps.core.permissions import DjangoModelPermissions

        return DjangoModelPermissions().has_permission(request, view)

