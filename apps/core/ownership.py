"""
Per-team-member record isolation: ownership and row-level visibility.

BASELINE MODULE (STEP 2): Single source for tenant + creator visibility.
- No imports from app modules (invoices, expense_management, etc.); no circular dependencies.
- Safe defaults: request=None => treat as team member (restrict). Model without
  created_by => non-admin sees no records (restrict).

Visibility rules (queryset level only; RBAC is NOT modified):
- Company admin (account owner, no sub_user_id in session): sees ALL records for the account.
- Team members: see ONLY records they created (created_by=user).
- full_company_visibility (is_read_only_user): same row-level visibility as admin (READ only).
  This is VISIBILITY only—never implies create_employee_account, reset_employee_password,
  or view_employee_activity; authority to manage users requires explicit permissions.

Tenant scoping: account_lookup='account' for models with Account FK; use
account_lookup='company__account' for models scoped by CompanyProfile.

Use:
- TenantOwnedModel: abstract base; subclasses declare account/company + created_by + created_at.
- TenantOwnedManager + TenantOwnedQuerySet: .for_user(user, request), .visible_to(user, request).
- for_user_queryset(): FBV helper. VisibleToUserMixin: CBV. drf_filter_queryset_for_user(): DRF.
"""
from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


def _model_has_created_by(model):
    """True if model has a created_by field (FK to User). Safe for abstract/models with no such field."""
    try:
        return model._meta.get_field('created_by') is not None
    except Exception:
        return False

__all__ = [
    'is_company_admin',
    'get_account_for_user',
    'TenantOwnedQuerySet',
    'TenantOwnedManager',
    'TenantOwnedModel',
    'for_user_queryset',
    'VisibleToUserMixin',
    'drf_filter_queryset_for_user',
]


def is_company_admin(user, request=None):
    """
    True if the current actor is the company admin (account owner), so they
    can see and manage ALL records under the company.

    - Account owner (user.id == account.owner_id, and no sub_user_id in session): admin.
    - Team member (logged in as SubUser, or not the account owner): not admin.
    - When request is None (e.g. scripts, aggregation): treat as admin only if
      user is the account owner (by owner_id); otherwise False.

    Args:
        user: The authenticated User (owner or linked_user for SubUser).
        request: Optional; if provided, session is checked for sub_user_id.

    Returns:
        bool
    """
    if not user or not getattr(user, 'is_authenticated', True):
        return False
    account_id = getattr(user, 'account_id', None)
    if not account_id:
        return False
    from apps.core.models import Account
    account = Account.objects.filter(pk=account_id).first()
    if not account:
        return False
    owner_id = getattr(account, 'owner_id', None)
    # Impersonation: when owner is "logged in as" a team member, they are not treated as admin for visibility.
    if getattr(request, 'session', None) and request.session.get('sub_user_id'):
        return False
    # User is the account owner (or backfill so first user becomes owner)
    if owner_id is None:
        Account.objects.filter(pk=account_id).update(owner_id=user.id)
        return True
    return owner_id == user.id


def get_account_for_user(user):
    """
    Return the Account (tenant) for the given user. Used for scoping querysets.

    - Account owner: user.account.
    - Team member (linked_user): user.account, or fallback from linked_subuser.account_owner
      so team members always get an account (e.g. for messaging) even if signal did not set it.
    - Production-safe: also resolves by user.account_id (direct FK id) when relation access
      fails or is not loaded (e.g. different WSGI/ASGI worker, lazy loading).
    """
    if not user:
        return None
    acc = getattr(user, 'account', None)
    if acc is not None:
        return acc
    # Resolve by FK id when relation is not loaded (common on production with multiple workers)
    account_id = getattr(user, 'account_id', None)
    if account_id is not None:
        from apps.core.models import Account
        return Account.objects.filter(pk=account_id).first()
    # Fallback for team members whose User.account may not be set yet
    sub = getattr(user, 'linked_subuser', None)
    if sub and getattr(sub, 'account_owner', None):
        owner = sub.account_owner
        if owner is not None:
            acc = getattr(owner, 'account', None)
            if acc is not None:
                return acc
            oid = getattr(owner, 'account_id', None)
            if oid is not None:
                from apps.core.models import Account
                return Account.objects.filter(pk=oid).first()
    return None


class TenantOwnedQuerySet(models.QuerySet):
    """
    QuerySet mixin that adds visible_to(user, request) for row-level visibility.

    Model should have tenant (account or company) and optionally created_by.
    - Company admin (no sub_user_id): sees all records in the queryset.
    - Team member: sees only created_by=user; if model has no created_by, sees none.
    Tenant filtering is done by the manager/for_user_queryset; this only applies visibility.
    """

    def visible_to(self, user, request=None):
        """
        Restrict to records the user is allowed to see:
        - Company admin: all records (admin bypass).
        - Team member: only records they created (created_by=user).
        - If model has no created_by field, non-admin gets no records (safe default).

        Call after filtering by tenant, e.g.:
          Model.objects.filter(account=user.account).visible_to(user, request)
        or use the manager's for_user() which does both.
        """
        if not user or not getattr(user, 'is_authenticated', True):
            return self.none()
        if is_company_admin(user, request):
            return self
        # Company Read Only role: same visibility as Company Admin (all company records)
        from apps.core.mixins import is_read_only_user
        if is_read_only_user(user):
            return self
        # Team member: only own records; if model has no created_by, restrict to none
        if not _model_has_created_by(self.model):
            return self.none()
        return self.filter(created_by=user)


class TenantOwnedManager(models.Manager):
    """
    Manager for tenant + creator models. get_queryset() returns TenantOwnedQuerySet
    (visible_to available). Does NOT apply visibility by default.

    - for_user(user, request): returns queryset scoped to user's account and visibility
      (admin sees all, team member sees only created_by=user).
    - account_lookup: 'account' (default) or 'company__account' for CompanyProfile-scoped models.
    """

    account_lookup = 'account'  # override to 'company__account' for company-scoped models

    def get_queryset(self):
        return TenantOwnedQuerySet(self.model, using=self._db)

    def for_user(self, user, request=None):
        """
        Return queryset scoped to the user's account and visibility:
        - Same account (tenant) as user.account (or company.account).
        - If company admin: all such records. If team member: only created_by=user.
        """
        qs = self.get_queryset()
        account = get_account_for_user(user)
        if account is None:
            return qs.none()
        if self.account_lookup == 'account':
            qs = qs.filter(account=account)
        else:
            qs = qs.filter(**{self.account_lookup: account})
        return qs.visible_to(user, request)


class TenantOwnedModel(models.Model):
    """
    Abstract base (no fields) for tenant-owned records. Subclasses declare:
    - Tenant: account (FK to Account) or company (FK to CompanyProfile).
    - Creator: created_by (FK to User), optional but required for team-member filtering.
    - created_at (DateTimeField) recommended for auditing.

    Use TenantOwnedManager with account_lookup='account' or 'company__account'.
    Visibility: admin sees all; team member sees only created_by=user (enforced in
    TenantOwnedQuerySet.visible_to and for_user).
    """

    class Meta:
        abstract = True


def for_user_queryset(model_class, user, request=None, account_lookup='account'):
    """
    Helper for FBVs: return queryset scoped to tenant and visibility.

    - account_lookup: 'account' (default) or 'company__account' for CompanyProfile-scoped models.
    - Company admin: all records for the account. Team member: only created_by=user.
    - If model has no created_by, non-admin gets empty queryset (safe default).
    """
    account = get_account_for_user(user)
    if account is None:
        return model_class.objects.none()
    qs = model_class.objects.filter(**{account_lookup: account})
    if hasattr(qs, 'visible_to'):
        return qs.visible_to(user, request)
    if is_company_admin(user, request):
        return qs
    from apps.core.mixins import is_read_only_user
    if is_read_only_user(user):
        return qs
    if not _model_has_created_by(model_class):
        return model_class.objects.none()
    return qs.filter(created_by=user)


# ---------------------------------------------------------------------------
# CBV and DRF integration
# ---------------------------------------------------------------------------


class VisibleToUserMixin:
    """
    Mixin for Django class-based views (ListView, DetailView, etc.) that use
    tenant + created_by models. get_queryset() restricts to records visible to
    the current user (account scope + admin sees all, team member sees own).

    Requirements:
    - Model must have account (or company) + created_by.
    - Set .visibility_account_lookup = 'company__account' if the model uses
      company (CompanyProfile) instead of account.
    """
    visibility_account_lookup = 'account'

    def get_queryset(self):
        qs = super().get_queryset()
        user = getattr(self.request, 'user', None)
        if not user or not getattr(user, 'is_authenticated', True):
            return qs.none()
        model = getattr(qs, 'model', None)
        if model is None:
            return qs
        return for_user_queryset(
            model, user, self.request,
            account_lookup=getattr(self, 'visibility_account_lookup', 'account'),
        )


def drf_filter_queryset_for_user(queryset, request, account_lookup='account'):
    """
    Apply per-team-member visibility to a DRF queryset. Use in ViewSet.get_queryset()
    or filter_queryset(). Company admin sees all; team member sees only created_by=user.
    If model has no created_by, non-admin gets empty queryset (safe default).

    account_lookup: 'account' (default) or 'company__account'.
    """
    user = getattr(request, 'user', None)
    if not user or not getattr(user, 'is_authenticated', True):
        return queryset.none()
    account = get_account_for_user(user)
    if account is None:
        return queryset.none()
    qs = queryset.filter(**{account_lookup: account})
    if hasattr(qs, 'visible_to'):
        return qs.visible_to(user, request)
    if is_company_admin(user, request):
        return qs
    from apps.core.mixins import is_read_only_user
    if is_read_only_user(user):
        return qs
    if not _model_has_created_by(qs.model):
        return queryset.none()
    return qs.filter(created_by=user)
