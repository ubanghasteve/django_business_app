"""
DRF permission classes and decorators for view-level access control.

- DjangoModelPermissions: DRF class for API views.
- company_admin_or_permission_required: decorator for FBVs so company admin (account owner)
  can use all app features (Edit, Download, Print, etc.) without being blocked by
  missing role permissions.
- require_not_read_only: decorator for FBVs that modify data; returns 403 for "Company Read Only" users.
ReadOnlyProtectionMixin lives in apps.core.mixins.
"""
from functools import wraps
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseForbidden, JsonResponse

from rest_framework import permissions


def _is_ajax(request):
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def require_not_read_only(view_func):
    """
    Decorator for function-based views that accept POST/PUT/PATCH/DELETE.
    Returns 403 for users in the "Company Read Only" role on mutating methods.
    Use on any FBV that modifies data.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if request.method.upper() in ('POST', 'PUT', 'PATCH', 'DELETE'):
            from apps.core.mixins import is_read_only_user
            if is_read_only_user(request.user):
                return HttpResponseForbidden(
                    'Your role does not allow creating, editing, or deleting.'
                )
        return view_func(request, *args, **kwargs)
    return _wrapped


def company_admin_or_any_permission_required(perms, raise_exception=True):
    """
    View decorator: allow access if the user is the company admin OR has any of the given permissions.
    perms: list of permission strings, e.g. ['hr_staff.change_leaverequest', 'hr_staff.view_hr_dashboard'].
    """
    perms = perms if isinstance(perms, (list, tuple)) else [perms]

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                if raise_exception:
                    if _is_ajax(request):
                        return JsonResponse(
                            {'success': False, 'message': 'Please log in to continue.'},
                            status=401
                        )
                    raise PermissionDenied
                from django.contrib.auth.views import redirect_to_login
                return redirect_to_login(request.get_full_path())
            if getattr(request.user, 'is_superuser', False):
                return view_func(request, *args, **kwargs)
            from apps.core.ownership import is_company_admin as _is_company_admin
            if _is_company_admin(request.user, request):
                return view_func(request, *args, **kwargs)
            if any(request.user.has_perm(p) for p in perms):
                return view_func(request, *args, **kwargs)
            if raise_exception:
                if _is_ajax(request):
                    return JsonResponse(
                        {'success': False, 'message': 'You do not have permission to perform this action.'},
                        status=403
                    )
                raise PermissionDenied
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())
        return _wrapped_view
    return decorator


def company_admin_or_permission_required(perm, raise_exception=True):
    """
    View decorator: allow access if the user is the company admin (account owner) OR has the given permission.
    Use for actions (print, download, edit, delete) so company admin is never restricted.

    Usage:
        @login_required
        @company_admin_or_permission_required('receipts.print_receipt', raise_exception=True)
        def receipt_print_view(request, receipt_id): ...
    """
    return company_admin_or_any_permission_required([perm], raise_exception)


class CompanyAdminOrPermissionRequiredMixin:
    """
    Mixin for class-based views using PermissionRequiredMixin.
    Grants access if the user is the company admin (account owner); otherwise
    falls back to the normal permission check.
    Use as the leftmost mixin: CompanyAdminOrPermissionRequiredMixin, ..., PermissionRequiredMixin, ...
    """
    def has_permission(self):
        from apps.core.ownership import is_company_admin
        if is_company_admin(self.request.user, self.request):
            return True
        return super().has_permission()


class DjangoModelPermissions(permissions.BasePermission):
    """
    Enforce Django model permissions (view/add/change/delete) per DRF action.
    Requires the view to have a .queryset or .model attribute so we can resolve
    app_label and model name. Use with IsAuthenticated.
    """
    perms_map = {
        'GET': ['%(app_label)s.view_%(model_name)s'],
        'OPTIONS': ['%(app_label)s.view_%(model_name)s'],
        'HEAD': ['%(app_label)s.view_%(model_name)s'],
        'POST': ['%(app_label)s.add_%(model_name)s'],
        'PUT': ['%(app_label)s.change_%(model_name)s'],
        'PATCH': ['%(app_label)s.change_%(model_name)s'],
        'DELETE': ['%(app_label)s.delete_%(model_name)s'],
    }

    def get_required_permissions(self, request, view):
        """Resolve (app_label, model_name) from view.queryset or view.model."""
        model = getattr(view, 'model', None) or getattr(view, 'queryset', None)
        if model is not None:
            model = getattr(model, 'model', model)
        if model is None:
            return []
        opts = model._meta
        app_label = opts.app_label
        model_name = opts.model_name
        method = request.method.upper()
        if method not in self.perms_map:
            return []
        return [p % {'app_label': app_label, 'model_name': model_name} for p in self.perms_map[method]]

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        perms = self.get_required_permissions(request, view)
        if not perms:
            return True
        return request.user.has_perms(perms)
