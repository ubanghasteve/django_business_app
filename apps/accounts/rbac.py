"""
RBAC helpers for the business app.

Authorization is enforced via Django model permissions (user.has_perm / permission_required).
Do not use is_staff or role names for access control; use permissions and groups instead.

- can_manage_users / can_edit / can_delete: Permission-based checks for UI only; backend must use
  @permission_required or PermissionRequiredMixin.
- company_profile_required: Decorator that requires core.view_companyprofile (use @permission_required in new code).
- staff_required: Deprecated; use @permission_required('app.action_model') or PermissionRequiredMixin.
"""
from functools import wraps
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.contrib import messages


def get_effective_staff(request):
    """
    Deprecated. Returns True if user has staff-like permissions.
    Prefer checking specific permissions (e.g. request.user.has_perm('expenses.change_expense')).
    When logged in as team member (SubUser), request.user is the linked_user; staff is derived
    from that user's permissions (or legacy is_staff on SubUser).
    """
    if not request.user.is_authenticated:
        return False
    sub_user = getattr(request.user, 'linked_subuser', None)
    if sub_user:
        return sub_user.is_staff
    return request.user.is_staff


def staff_required(view_func):
    """
    Deprecated. Use @permission_required('app.action_model', raise_exception=True) or
    PermissionRequiredMixin instead. This decorator still checks get_effective_staff for backward compatibility.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())
        if not get_effective_staff(request):
            messages.error(
                request,
                'You need staff permissions to perform this action. Contact your account administrator.'
            )
            return HttpResponseForbidden(
                '<h1>403 Forbidden</h1>'
                '<p>You need staff permissions to perform this action.</p>'
                '<p><a href="/">Return to Dashboard</a></p>'
            )
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def can_manage_users(request):
    """True if user can access team/roles (Django permissions). Use for UI only; enforce in views with permission_required."""
    if not request.user.is_authenticated:
        return False
    return (
        request.user.has_perm('accounts.view_subuser') or
        request.user.has_perm('accounts.view_accountgroup')
    )


def can_edit(request):
    """Deprecated. No single permission; check per-resource (e.g. perms.expenses.change_expense) in templates."""
    return False


def can_delete(request):
    """Deprecated. No single permission; check per-resource (e.g. perms.expenses.delete_expense) in templates."""
    return False


def is_account_owner(request):
    """True if the current user is the account owner (account.owner_id == user.id) and not impersonating a team member."""
    if not request.user.is_authenticated:
        return False
    if request.session.get('sub_user_id'):
        return False
    from apps.core.models import Account
    account_id = getattr(request.user, 'account_id', None)
    if not account_id:
        return False
    account = Account.objects.filter(pk=account_id).first()
    if not account:
        return False
    owner_id = getattr(account, 'owner_id', None)
    if owner_id is None:
        Account.objects.filter(pk=account_id).update(owner_id=request.user.id)
        return True
    return owner_id == request.user.id


def is_company_admin(request):
    """
    True if the current actor is the company admin (account owner).
    Company admins can see and manage ALL records under the company; team members
    can only see/edit/delete records they created (per-team-member isolation).

    Use for row-level visibility: when True, show all company records; when False,
    filter to created_by=request.user. See apps.core.ownership for queryset helpers.
    """
    return is_account_owner(request)


def can_access_company_profile(request):
    """True if user has permission to view or change company profile (Django permissions)."""
    if not request.user.is_authenticated:
        return False
    return (
        request.user.has_perm('core.view_companyprofile') or
        request.user.has_perm('core.change_companyprofile')
    )


def company_profile_required(view_func):
    """Decorator: requires core.view_companyprofile. Prefer @permission_required('core.view_companyprofile', raise_exception=True)."""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())
        if not can_access_company_profile(request):
            messages.error(request, 'You do not have permission to access company settings.')
            return HttpResponseForbidden(
                '<h1>403 Forbidden</h1>'
                '<p>You do not have permission to access company profile and bank accounts.</p>'
                '<p><a href="/">Return to Dashboard</a></p>'
            )
        return view_func(request, *args, **kwargs)
    return _wrapped_view
