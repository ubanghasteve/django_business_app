"""
Reusable view mixins for core behavior.

- ReadOnlyProtectionMixin: Allow GET, HEAD, OPTIONS; block POST, PUT, PATCH, DELETE
  with HTTP 403 only when the user has full-company-visibility and only view/print/download
  permissions (so admin-assigned add/change/delete are respected).
"""
from django.http import HttpResponseForbidden


def has_full_company_visibility(user):
    """
    True if the user is in any role (AccountGroup) with full_company_visibility=True.
    Such users see all company records (no data isolation). Role name is irrelevant.

    SECURITY: This grants READ/VISIBILITY only. It does NOT grant and must never
    be used to imply: user creation, password control (reset/set/view), or any
    HR permission (create_employee_account, reset_employee_password,
    view_employee_activity). Authority to manage users always requires explicit
    permissions and guarded views.
    """
    if not user or not getattr(user, 'is_authenticated', True):
        return False
    from apps.accounts.models import AccountGroup
    return AccountGroup.objects.filter(
        group__user=user,
        full_company_visibility=True,
    ).exists()


def _user_has_only_view_permissions(user):
    """
    True if the user has at least one permission and all of their permissions
    are view/print/download only (no add, change, delete). Used together with
    has_full_company_visibility to block mutations only when they have no edit perms.
    """
    if not user or not getattr(user, 'is_authenticated', True):
        return False
    from django.contrib.auth.models import Permission
    codenames = set(
        Permission.objects.filter(group__user=user)
        .values_list('codename', flat=True)
        .distinct()
    )
    if not codenames:
        return False
    for codename in codenames:
        if not (
            codename.startswith('view_') or
            codename.startswith('print_') or
            codename.startswith('download_')
        ):
            return False
    return True


def is_read_only_user(user):
    """
    True if the user has full company visibility (any role with full_company_visibility=True)
    or has only view/print/download permissions. Used for:
    - Visibility: such users see all company records (ownership.py).
    - Mutation block: only when they also have only view permissions (ReadOnlyProtectionMixin).
    Admin-assigned add/change/delete are never stripped and are respected.
    """
    if not user or not getattr(user, 'is_authenticated', True):
        return False
    if has_full_company_visibility(user):
        return True
    return _user_has_only_view_permissions(user)


class ReadOnlyProtectionMixin:
    """
    Reusable mixin for Create/Update/Delete and any custom POST views.
    - Allow: GET, HEAD, OPTIONS
    - Block: POST, PUT, PATCH, DELETE with HTTP 403 only when the user has full company
      visibility AND only view/print/download permissions (no add/change/delete).
    If the admin assigned add/change/delete to a full-company-visibility role, those
    permissions are used and we do not block.
    Use as the leftmost mixin so it runs before permission checks.
    """
    def dispatch(self, request, *args, **kwargs):
        if request.method.upper() in ('POST', 'PUT', 'PATCH', 'DELETE'):
            if has_full_company_visibility(request.user) and _user_has_only_view_permissions(request.user):
                return HttpResponseForbidden(
                    'Your role does not allow creating, editing, or deleting.'
                )
        return super().dispatch(request, *args, **kwargs)
