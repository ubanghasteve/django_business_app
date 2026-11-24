"""
Multi-tenant admin base: permission-based visibility and account-scoped querysets.

Use AccountScopedAdmin for any model that belongs to a single tenant (Account).
Set account_scope_lookup to the lookup path from the model to core.Account, e.g.:
  - 'account' (model has ForeignKey to Account)
  - 'company__account' (model has ForeignKey to CompanyProfile which has OneToOne to Account)
  - 'user__account' (model has ForeignKey to User which has ForeignKey to Account)
  - 'pk' (for core.Account itself: show only the current user's account)

Superusers bypass queryset scoping and see all objects.
Company admins (account owner, no sub_user in session) see all account records.
Team members see only records they created (created_by=user) when the model has created_by.
"""
from django.contrib import admin
from django.contrib.auth import get_permission_codename
from django.core.exceptions import PermissionDenied

from .models import Account
from .ownership import is_company_admin


def _model_has_created_by(model):
    """True if model has a created_by field (FK to User)."""
    try:
        return model._meta.get_field('created_by') is not None
    except Exception:
        return False


def get_account_for_admin_request(request):
    """
    Return the Account for the current user in admin, or None for superuser.

    Aligns with main app: resolves account from request.user.account, or from
    ownership (owner_id=user.id), and backfills owner_id when the account has no owner
    so company admins are never restricted by missing owner_id.
    """
    if not getattr(request, 'user', None) or request.user.is_anonymous:
        return None
    if request.user.is_superuser:
        return None
    account = getattr(request.user, 'account', None)
    if account is None:
        account = Account.objects.filter(owner_id=request.user.id).first()
        if account:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            User.objects.filter(pk=request.user.id).update(account_id=account.pk)
    if account is not None:
        owner_id = Account.objects.filter(pk=account.pk).values_list('owner_id', flat=True).first()
        if owner_id is None:
            Account.objects.filter(pk=account.pk).update(owner_id=request.user.id)
    return account


class AccountScopedAdmin(admin.ModelAdmin):
    """
    ModelAdmin that:
    1. Gates module/view/add/change/delete by Django model permissions.
    2. Restricts get_queryset to the current user's account when not superuser.
    3. For non-admin users (team members), further restricts to created_by=request.user when model has created_by.
    """

    # Subclasses must set this to the lookup path to Account, or 'pk' for Account model.
    account_scope_lookup = None

    def _account_for_request(self, request):
        """Return the account for the current user, or None if not applicable (e.g. superuser)."""
        return get_account_for_admin_request(request)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        account = self._account_for_request(request)
        if account is None:
            # Superuser: full queryset. Non-superuser with no account: show nothing (avoid leaking data).
            if not getattr(request, 'user', None) or request.user.is_anonymous or request.user.is_superuser:
                return qs
            return qs.none()
        lookup = getattr(self, 'account_scope_lookup', None)
        if not lookup:
            return qs
        if lookup == 'pk':
            qs = qs.filter(pk=account.pk)
        else:
            qs = qs.filter(**{lookup: account})
        # Per-team-member isolation: non-admin users see only their own records (model must have created_by)
        if not request.user.is_superuser and not is_company_admin(request.user, request) and _model_has_created_by(self.model):
            qs = qs.filter(created_by=request.user)
        return qs

    def has_module_permission(self, request):
        if not request.user.is_active:
            return False
        if request.user.is_superuser:
            return True
        opts = self.model._meta
        codename = get_permission_codename('view', opts)
        perm = f'{opts.app_label}.{codename}'
        return request.user.has_perm(perm)

    def has_view_permission(self, request, obj=None):
        if not request.user.is_active:
            return False
        if request.user.is_superuser:
            return True
        opts = self.model._meta
        codename = get_permission_codename('view', opts)
        return request.user.has_perm(f'{opts.app_label}.{codename}')

    def has_add_permission(self, request):
        if not request.user.is_active:
            return False
        if request.user.is_superuser:
            return True
        opts = self.model._meta
        codename = get_permission_codename('add', opts)
        return request.user.has_perm(f'{opts.app_label}.{codename}')

    def has_change_permission(self, request, obj=None):
        if not request.user.is_active:
            return False
        if request.user.is_superuser:
            return True
        opts = self.model._meta
        codename = get_permission_codename('change', opts)
        return request.user.has_perm(f'{opts.app_label}.{codename}')

    def has_delete_permission(self, request, obj=None):
        if not request.user.is_active:
            return False
        if request.user.is_superuser:
            return True
        opts = self.model._meta
        codename = get_permission_codename('delete', opts)
        return request.user.has_perm(f'{opts.app_label}.{codename}')
