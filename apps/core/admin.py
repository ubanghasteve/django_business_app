from django.contrib import admin
from django.db import connection, connections, transaction
from django.db.models import F
from django.utils.html import format_html

from .admin_base import AccountScopedAdmin, get_account_for_admin_request
from .models import Account, CompanyProfile, BankAccount


def _delete_account_dependents(using, account_ids):
    """
    Delete all model rows that reference the given account IDs so Account can be
    deleted without FK violations. Order avoids cross-app FK dependencies.
    """
    from django.apps import apps
    # Models that have FK to core.Account (app_label, model_name).
    # CompanyProfile is already deleted when we delete User (user CASCADE).
    account_dependent_models = [
        ('accounts', 'AccountGroup'),
        ('accounts', 'SecurityActivity'),
        ('core', 'CompanyProfile'),  # in case any remain without user
        ('job_orders', 'Product'),
        ('requisitions', 'Requisition'),
        ('invoices', 'Invoice'),
        ('receipts', 'Receipt'),
        ('waybills', 'Waybill'),
        ('quotations', 'Quotation'),
        ('messaging', 'Conversation'),
        ('messaging', 'UserPresence'),
        ('inventory', 'Inventory'),
    ]
    for app_label, model_name in account_dependent_models:
        try:
            model = apps.get_model(app_label, model_name)
            if hasattr(model, 'account_id') or hasattr(model, 'account'):
                model.objects.using(using).filter(account_id__in=account_ids).delete()
        except LookupError:
            pass


class AccountScopeListFilter(admin.SimpleListFilter):
    """Filter Account list to primary only (one per owner) or all (including duplicates)."""
    title = 'scope'
    parameter_name = 'scope'

    def lookups(self, request, model_admin):
        return (
            ('primary', 'Primary only (one per owner)'),
            ('all', 'All (including duplicates)'),
        )

    def queryset(self, request, queryset):
        # Filtering is done in AccountAdmin.get_queryset; this just defines the URL param and choices.
        return queryset


def _apply_account_approval_changes(account, became_approved):
    """
    Apply approval/disapproval: account-scoped Company Admin group only.
    - On approval: get_or_create Company Admin for this account, set full perms from template, add ONLY owner.
    - On disapproval: remove owner from Company Admin; ensure owner remains in Company Profile Viewer.
    Isolation: group.account == user.account enforced by services. No shared groups.
    """
    from django.contrib.auth import get_user_model
    from apps.accounts.models import AccountGroup
    from apps.accounts.default_role import COMPANY_ADMIN_ROLE_NAME
    from apps.accounts.services import (
        create_account_group,
        update_account_group_permissions,
        assign_user_to_account_group,
        remove_user_from_account_group,
        get_or_create_default_onboarding_role,
        get_all_permission_codenames,
        _clear_user_permission_cache,
        sync_requisition_permissions_to_company_admin,
        sync_inventory_permissions_to_company_admin,
    )

    User = get_user_model()
    owner = account.owner
    if not owner:
        return

    # Ensure owner is linked to this account so assign_user_to_account_group succeeds (e.g. after cleanup or old data).
    if owner.account_id != account.id:
        User.objects.filter(pk=owner.pk).update(account_id=account.id)
        owner.account_id = account.id
        owner.account = account

    # Company Admin gets ALL permissions in the app (full access to every feature)
    company_admin_codenames = get_all_permission_codenames()
    # Ensure role-management permissions are always included (Create Role, Manage roles, etc.)
    auth_role_codenames = ['auth.view_group', 'auth.add_group', 'auth.change_group', 'auth.delete_group']
    for codename in auth_role_codenames:
        if codename not in company_admin_codenames:
            company_admin_codenames.append(codename)

    if became_approved:
        # Remove owner from default onboarding role so they rely solely on Company Admin
        default_ag = get_or_create_default_onboarding_role(account)
        remove_user_from_account_group(owner, default_ag)
        ag = AccountGroup.objects.filter(
            account=account,
            role_name=COMPANY_ADMIN_ROLE_NAME,
        ).select_related('group').first()
        if not ag:
            ag = create_account_group(
                account=account,
                role_name=COMPANY_ADMIN_ROLE_NAME,
                permission_codenames=company_admin_codenames,
            )
        else:
            update_account_group_permissions(ag, company_admin_codenames)
        assign_user_to_account_group(owner, ag)
        # Ensure all app permissions (including Requisitions and any future apps) are on Company Admin
        try:
            sync_requisition_permissions_to_company_admin()
        except Exception:
            pass
        try:
            sync_inventory_permissions_to_company_admin()
        except Exception:
            pass
        # Keep owner's company profile in sync: ensure profile.account_id = account (so they can edit after approval)
        from .models import CompanyProfile
        CompanyProfile.objects.filter(user_id=owner.pk).update(account_id=account.id)
    else:
        default_ag = get_or_create_default_onboarding_role(account)
        assign_user_to_account_group(owner, default_ag)
        company_admin_ag = AccountGroup.objects.filter(
            account=account,
            role_name=COMPANY_ADMIN_ROLE_NAME,
        ).first()
        if company_admin_ag:
            remove_user_from_account_group(owner, company_admin_ag)

    _clear_user_permission_cache(owner)


@admin.register(Account)
class AccountAdmin(AccountScopedAdmin):
    """Tenant account — staff see only their own. Superusers see ALL accounts by default so new registrations appear for approval."""
    account_scope_lookup = 'pk'
    list_display = ['name', 'owner', 'is_approved', 'is_active', 'created_at']
    list_filter = [AccountScopeListFilter, 'is_approved', 'is_active', 'created_at']
    ordering = ['-created_at']  # New registrations (pending approval) appear first
    search_fields = ['name', 'owner__email']
    readonly_fields = ['created_at', 'updated_at']
    raw_id_fields = ('owner',)
    fieldsets = (
        (None, {'fields': ('name', 'owner')}),
        ('Approval', {
            'fields': ('is_approved', 'is_active'),
            'description': 'Super admin: approve to unlock full access; disapprove for profile-only.',
        }),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # For superusers: default show ALL accounts so new registrations appear for approval.
        # Use Scope "Primary only" to hide duplicate/orphan accounts (one row per owner).
        if request.user.is_superuser and request.GET.get('scope') == 'primary':
            qs = qs.filter(owner__account_id=F('id'))
        return qs

    def save_model(self, request, obj, form, change):
        old_approved = None
        if change and obj.pk:
            old_approved = Account.objects.filter(pk=obj.pk).values_list('is_approved', flat=True).first()
        super().save_model(request, obj, form, change)
        if change and old_approved is not None and obj.is_approved != old_approved:
            _apply_account_approval_changes(obj, became_approved=obj.is_approved)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'owner' and not request.user.is_superuser:
            account = get_account_for_admin_request(request)
            if account is not None:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                kwargs['queryset'] = User.objects.filter(account=account)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def delete_queryset(self, request, queryset):
        """
        Avoid IntegrityError from circular FK (Account.owner -> User, User.account -> Account)
        and from dependent models. Delete users and all account-scoped dependents first,
        then delete Account. For SQLite, disable FK checks before the transaction so
        PRAGMA takes effect.
        """
        from django.contrib.auth import get_user_model
        User = get_user_model()
        account_ids = list(queryset.values_list('pk', flat=True))
        if not account_ids:
            super().delete_queryset(request, queryset)
            return

        using = getattr(queryset, 'db', None) or 'default'
        conn = connections[using]

        # SQLite: run PRAGMA before opening the transaction so FK checks are off for the whole flow.
        fk_checks_disabled = False
        if conn.vendor == 'sqlite':
            with conn.cursor() as cursor:
                cursor.execute("PRAGMA foreign_keys = OFF")
            fk_checks_disabled = True
        elif conn.vendor == 'mysql':
            with conn.cursor() as cursor:
                cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
            fk_checks_disabled = True

        try:
            with transaction.atomic(using=using):
                # Break circular FK: null owner then delete users (cascades to CompanyProfile, etc.).
                user_ids = list(User.objects.using(using).filter(account_id__in=account_ids).values_list('pk', flat=True))
                if user_ids:
                    Account.objects.using(using).filter(owner_id__in=user_ids).update(owner_id=None)
                User.objects.using(using).filter(account_id__in=account_ids).delete()

                # Explicitly delete all models that reference Account so order is correct on every backend.
                _delete_account_dependents(using, account_ids)

                super().delete_queryset(request, queryset)
        finally:
            if fk_checks_disabled:
                try:
                    with conn.cursor() as cursor:
                        if conn.vendor == 'sqlite':
                            cursor.execute("PRAGMA foreign_keys = ON")
                        elif conn.vendor == 'mysql':
                            cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
                except Exception:
                    pass


@admin.register(CompanyProfile)
class CompanyProfileAdmin(AccountScopedAdmin):
    account_scope_lookup = 'account'
    list_display = [
        'company_name', 'user', 'email', 'phone', 'currency_display',
        'has_logo', 'has_signature', 'created_at'
    ]
    list_filter = ['currency_code', 'created_at', 'updated_at']
    search_fields = ['company_name', 'user__username', 'email', 'phone']
    readonly_fields = ['created_at', 'updated_at', 'logo_preview', 'signature_preview']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('user', 'company_name', 'email', 'phone', 'website')
        }),
        ('Address Information', {
            'fields': ('address_line_1', 'address_line_2', 'city', 'state', 'postal_code', 'country'),
            'classes': ('collapse',)
        }),
        ('Business Information', {
            'fields': ('business_type', 'tax_id', 'registration_number'),
            'classes': ('collapse',)
        }),
        ('Visual Assets', {
            'fields': ('logo', 'logo_preview', 'signature', 'signature_preview', 'show_bank_details', 'show_signature'),
            'classes': ('collapse',)
        }),
        ('Financial Settings', {
            'fields': ('default_tax', 'currency_code', 'currency_symbol'),
            'classes': ('collapse',)
        }),
        ('Colors & Styling', {
            'fields': ('primary_color', 'secondary_color', 'accent_color', 'text_color'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def currency_display(self, obj):
        return f"{obj.currency_code} ({obj.currency_symbol})"
    currency_display.short_description = 'Currency'

    def has_logo(self, obj):
        if obj.logo:
            return format_html('<span style="color: green;">✓</span>')
        return format_html('<span style="color: red;">✗</span>')
    has_logo.short_description = 'Logo'

    def has_signature(self, obj):
        if obj.signature:
            return format_html('<span style="color: green;">✓</span>')
        return format_html('<span style="color: red;">✗</span>')
    has_signature.short_description = 'Signature'

    def logo_preview(self, obj):
        if obj.logo:
            return format_html(
                '<img src="{}" style="max-width: 200px; max-height: 100px;" />',
                obj.logo.url
            )
        return "No logo uploaded"
    logo_preview.short_description = 'Logo Preview'

    def signature_preview(self, obj):
        if obj.signature:
            return format_html(
                '<img src="{}" style="max-width: 200px; max-height: 100px;" />',
                obj.signature.url
            )
        return "No signature uploaded"
    signature_preview.short_description = 'Signature Preview'

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if request.user.is_superuser:
            return super().formfield_for_foreignkey(db_field, request, **kwargs)
        account = get_account_for_admin_request(request)
        if account is None:
            return super().formfield_for_foreignkey(db_field, request, **kwargs)
        if db_field.name == 'user':
            from django.contrib.auth import get_user_model
            User = get_user_model()
            kwargs['queryset'] = User.objects.filter(account=account)
        elif db_field.name == 'account':
            kwargs['queryset'] = Account.objects.filter(pk=account.pk)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class BankAccountInline(admin.TabularInline):
    model = BankAccount
    extra = 1
    fields = ['bank_name', 'account_name', 'account_number', 'is_default']


@admin.register(BankAccount)
class BankAccountAdmin(AccountScopedAdmin):
    account_scope_lookup = 'company__account'
    list_display = [
        'company', 'bank_name', 'account_name', 'account_number_masked',
        'is_default', 'created_at'
    ]
    list_filter = ['bank_name', 'is_default', 'created_at', 'updated_at']
    search_fields = [
        'company__company_name', 'bank_name', 'account_name', 'account_number'
    ]
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Bank Information', {
            'fields': ('company', 'bank_name', 'account_name', 'account_number', 'is_default')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def account_number_masked(self, obj):
        """Display masked account number for security"""
        if len(obj.account_number) > 4:
            return f"****{obj.account_number[-4:]}"
        return obj.account_number
    account_number_masked.short_description = 'Account Number'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('company', 'company__user', 'company__account')

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'company' and not request.user.is_superuser:
            account = get_account_for_admin_request(request)
            if account is not None:
                kwargs['queryset'] = CompanyProfile.objects.filter(account=account)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


# Update CompanyProfile admin to include bank accounts inline
CompanyProfileAdmin.inlines = [BankAccountInline]


# Custom admin site configuration
admin.site.site_header = "Multi-Purpose App Administration"
admin.site.site_title = "Multi-Purpose App Admin"
admin.site.index_title = "Welcome to Multi-Purpose App Administration"
