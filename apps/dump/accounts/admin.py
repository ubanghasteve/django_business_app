from django.contrib import admin
from django.contrib.auth import get_permission_codename
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django.contrib.auth.models import Group
from django.db import transaction
from django import forms
from django.utils.html import format_html

from apps.core.admin_base import AccountScopedAdmin, get_account_for_admin_request
from apps.core.models import Account
from .models import User, SubUser, UserSession, UserActivity, AccountGroup


class UserCreationForm(forms.ModelForm):
    """Form for creating new users"""
    password1 = forms.CharField(label='Password', widget=forms.PasswordInput)
    password2 = forms.CharField(label='Password confirmation', widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ('email', 'first_name', 'last_name', 'phone')

    def clean_password2(self):
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Passwords don't match")
        return password2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class UserChangeForm(forms.ModelForm):
    """Form for updating users"""
    password = ReadOnlyPasswordHashField()

    class Meta:
        model = User
        fields = ('email', 'password', 'first_name', 'last_name', 'phone', 'is_active', 'is_staff', 'is_superuser')

    def clean_password(self):
        return self.initial["password"]


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = UserChangeForm
    add_form = UserCreationForm

    list_display = ('email', 'first_name', 'last_name', 'account', 'is_staff', 'is_active', 'date_joined')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'date_joined', 'account')
    fieldsets = (
        (None, {'fields': ('email', 'password', 'change_password_link')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'phone')}),
        ('Account', {'fields': ('account',)}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name', 'phone', 'password1', 'password2'),
        }),
    )
    search_fields = ('email', 'first_name', 'last_name')
    ordering = ('email',)
    filter_horizontal = ('groups', 'user_permissions',)
    list_select_related = ('account',)

    def has_module_permission(self, request):
        if not request.user.is_active:
            return False
        if request.user.is_superuser:
            return True
        opts = self.model._meta
        codename = get_permission_codename('view', opts)
        return request.user.has_perm(f'{opts.app_label}.{codename}')

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

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        account = get_account_for_admin_request(request)
        if account is not None:
            return qs.filter(account=account)
        return qs.none()

    def delete_queryset(self, request, queryset):
        """Override to break User↔Account circular FK before bulk delete (SQLite IntegrityError fix)."""
        with transaction.atomic():
            user_ids = list(queryset.values_list('pk', flat=True))
            Account.objects.filter(owner_id__in=user_ids).update(owner=None)
            User.objects.filter(pk__in=user_ids).update(account=None)
            super().delete_queryset(request, queryset)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == 'groups':
            # Restrict to groups that belong to the target user's account so the
            # enforce_account_group_membership signal never sees invalid groups.
            account = None
            object_id = (
                request.resolver_match.kwargs.get('object_id')
                if getattr(request, 'resolver_match', None) and request.resolver_match
                else None
            )
            if object_id:
                try:
                    user_being_edited = self.get_queryset(request).get(pk=object_id)
                    account = getattr(user_being_edited, 'account', None)
                except (ValueError, User.DoesNotExist, TypeError):
                    pass
            if account is None and not request.user.is_superuser:
                account = get_account_for_admin_request(request)
            if account is not None:
                # Ensure account has at least the default role so superuser can assign groups.
                from .services import get_or_create_default_onboarding_role
                get_or_create_default_onboarding_role(account)
                # For approved accounts, ensure Company Admin group exists so it appears in the
                # Groups dropdown. Use get_all_permission_codenames() so Company Admin gets
                # every permission in the DB (including messaging and any future apps).
                if getattr(account, 'is_approved', False) and request.user.is_superuser:
                    from .models import AccountGroup
                    from .default_role import COMPANY_ADMIN_ROLE_NAME
                    from .services import (
                        create_account_group,
                        update_account_group_permissions,
                        get_all_permission_codenames,
                    )
                    company_admin_codenames = get_all_permission_codenames()
                    auth_role_codenames = ['auth.view_group', 'auth.add_group', 'auth.change_group', 'auth.delete_group']
                    for codename in auth_role_codenames:
                        if codename not in company_admin_codenames:
                            company_admin_codenames.append(codename)
                    ag = AccountGroup.objects.filter(
                        account=account,
                        role_name=COMPANY_ADMIN_ROLE_NAME,
                    ).select_related('group').first()
                    if not ag:
                        create_account_group(
                            account=account,
                            role_name=COMPANY_ADMIN_ROLE_NAME,
                            permission_codenames=company_admin_codenames,
                        )
                    else:
                        update_account_group_permissions(ag, company_admin_codenames)
                if request.user.is_superuser:
                    kwargs['queryset'] = Group.objects.filter(
                        account_group__account=account
                    ).distinct()
                else:
                    from .permission_boundaries import get_groups_assigner_may_assign
                    kwargs['queryset'] = get_groups_assigner_may_assign(account, request.user)
            else:
                # Superuser on add form: no target account yet; avoid assigning invalid groups
                kwargs['queryset'] = Group.objects.none()
        if db_field.name == 'user_permissions' and not request.user.is_superuser:
            from .permission_boundaries import get_permissions_user_may_assign
            kwargs['queryset'] = get_permissions_user_may_assign(request.user)
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            readonly.append('account')
        if obj is not None:
            readonly.append('change_password_link')
        return readonly

    def change_password_link(self, obj):
        if obj is None or not obj.pk:
            return ''
        # Relative URL: from .../user/<id>/change/ to .../user/<id>/password/
        return format_html(
            '<a class="button" href="../password/">Change password</a>',
        )
    change_password_link.short_description = 'Set / change password'

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'account' and not request.user.is_superuser:
            account = get_account_for_admin_request(request)
            if account is not None:
                kwargs['queryset'] = db_field.related_model.objects.filter(pk=account.pk)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        # CRITICAL: Never assign users to superuser's account. Superusers approve/activate
        # company accounts; approval must not make companies behave as superuser's tenants.
        # Only non-superusers (account owners) may auto-assign new users to their account.
        account = get_account_for_admin_request(request) if not request.user.is_superuser else None
        if (
            not change
            and not getattr(obj, 'account_id', None)
            and account is not None
            and not request.user.is_superuser
        ):
            obj.account = account
        super().save_model(request, obj, form, change)


@admin.register(AccountGroup)
class AccountGroupAdmin(AccountScopedAdmin):
    """Admin for account-scoped roles (wraps Django Group)."""
    account_scope_lookup = 'account'
    list_display = ('role_name', 'account', 'group')
    list_filter = ('account',)
    search_fields = ('role_name', 'account__name')
    raw_id_fields = ('account', 'group')
    ordering = ('account', 'role_name')

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'account' and not request.user.is_superuser:
            account = get_account_for_admin_request(request)
            if account is not None:
                kwargs['queryset'] = db_field.related_model.objects.filter(pk=account.pk)
        if db_field.name == 'group':
            # Only show Groups not yet linked to an AccountGroup (avoids IntegrityError)
            kwargs['queryset'] = Group.objects.filter(account_group__isnull=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(SubUser)
class SubUserAdmin(AccountScopedAdmin):
    """Admin for team members (SubUsers) — scoped to account owner's account."""
    account_scope_lookup = 'account_owner__account'
    list_display = ('email', 'full_name', 'account_owner', 'is_active', 'created_at')
    list_filter = ('is_active', 'account_owner')
    search_fields = ('email', 'full_name', 'account_owner__email')
    readonly_fields = ('password_hash', 'created_at', 'updated_at')
    raw_id_fields = ('account_owner',)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'account_owner' and not request.user.is_superuser:
            account = getattr(request.user, 'account', None)
            if account is not None:
                kwargs['queryset'] = User.objects.filter(account=account)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(UserSession)
class UserSessionAdmin(AccountScopedAdmin):
    """Admin for user sessions — scoped to user's account."""
    account_scope_lookup = 'user__account'
    list_display = (
        'user', 'sub_user', 'device_display', 'ip_address', 'location_display', 
        'login_time', 'logout_time', 'is_active', 'is_suspicious'
    )
    list_filter = ('is_active', 'is_suspicious', 'device_type', 'country', 'login_time')
    search_fields = ('user__email', 'ip_address', 'city', 'country', 'browser_name', 'device_brand')
    readonly_fields = (
        'id', 'user', 'sub_user', 'session_key', 'device_type', 'device_brand', 'device_model',
        'browser_name', 'browser_version', 'os_name', 'os_version', 'user_agent',
        'ip_address', 'city', 'region', 'country', 'country_code', 
        'latitude', 'longitude', 'tz_name', 'isp',
        'login_time', 'logout_time', 'last_activity', 'is_suspicious', 'suspicious_reason'
    )
    ordering = ('-login_time',)
    date_hierarchy = 'login_time'
    
    fieldsets = (
        ('Session Info', {
            'fields': ('id', 'user', 'sub_user', 'session_key', 'is_active', 'login_time', 'logout_time', 'last_activity')
        }),
        ('Device Information', {
            'fields': ('device_type', 'device_brand', 'device_model', 'browser_name', 'browser_version', 'os_name', 'os_version')
        }),
        ('Network & Location', {
            'fields': ('ip_address', 'city', 'region', 'country', 'country_code', 'tz_name', 'isp', 'latitude', 'longitude')
        }),
        ('Security', {
            'fields': ('is_suspicious', 'suspicious_reason'),
            'classes': ('collapse',),
        }),
        ('User Agent', {
            'fields': ('user_agent',),
            'classes': ('collapse',),
        }),
    )
    
    def device_display(self, obj):
        """Display device info with icon"""
        if obj.device_type == 'Mobile':
            icon = '📱'
        elif obj.device_type == 'Tablet':
            icon = '📲'
        else:
            icon = '💻'
        return f"{icon} {obj.device_info}"
    device_display.short_description = 'Device'
    
    def location_display(self, obj):
        """Display location info"""
        return obj.location_info
    location_display.short_description = 'Location'
    
    def has_add_permission(self, request):
        return False  # Sessions should only be created by the system
    
    def has_change_permission(self, request, obj=None):
        return False  # Sessions should not be modified
    
    actions = ['mark_as_suspicious', 'terminate_sessions']
    
    @admin.action(description='Mark selected sessions as suspicious')
    def mark_as_suspicious(self, request, queryset):
        queryset.update(is_suspicious=True)
    
    @admin.action(description='Terminate selected sessions')
    def terminate_sessions(self, request, queryset):
        from django.utils import timezone
        queryset.filter(is_active=True).update(
            is_active=False,
            logout_time=timezone.now()
        )


@admin.register(UserActivity)
class UserActivityAdmin(AccountScopedAdmin):
    """Admin for user activities — scoped to user's account."""
    account_scope_lookup = 'user__account'
    list_display = (
        'timestamp', 'user', 'sub_user', 'activity_type_display', 'description_short',
        'app_name', 'ip_address', 'risk_display'
    )
    list_filter = ('activity_type', 'risk_level', 'is_suspicious', 'app_name', 'timestamp')
    search_fields = ('user__email', 'description', 'app_name', 'ip_address', 'url_path')
    readonly_fields = (
        'id', 'user', 'sub_user', 'session', 'activity_type', 'description',
        'app_name', 'model_name', 'object_id', 'object_repr',
        'url_path', 'http_method', 'ip_address', 'user_agent',
        'extra_data', 'timestamp', 'is_suspicious', 'risk_level'
    )
    ordering = ('-timestamp',)
    date_hierarchy = 'timestamp'
    
    fieldsets = (
        ('Activity Info', {
            'fields': ('id', 'user', 'session', 'activity_type', 'description', 'timestamp')
        }),
        ('Target', {
            'fields': ('app_name', 'model_name', 'object_id', 'object_repr')
        }),
        ('Request Details', {
            'fields': ('url_path', 'http_method', 'ip_address'),
            'classes': ('collapse',),
        }),
        ('Security', {
            'fields': ('is_suspicious', 'risk_level'),
        }),
        ('Additional Data', {
            'fields': ('extra_data', 'user_agent'),
            'classes': ('collapse',),
        }),
    )
    
    def activity_type_display(self, obj):
        """Display activity type with color"""
        colors = {
            'LOGIN': 'green',
            'LOGOUT': 'gray',
            'LOGIN_FAILED': 'red',
            'CREATE': 'blue',
            'UPDATE': 'orange',
            'DELETE': 'red',
            'PAGE_VIEW': 'lightgray',
        }
        color = colors.get(obj.activity_type, 'black')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_activity_type_display()
        )
    activity_type_display.short_description = 'Activity Type'
    
    def description_short(self, obj):
        """Truncate description for display"""
        return obj.description[:50] + '...' if len(obj.description) > 50 else obj.description
    description_short.short_description = 'Description'
    
    def risk_display(self, obj):
        """Display risk level with color"""
        colors = {
            'LOW': 'green',
            'MEDIUM': 'orange',
            'HIGH': 'red',
            'CRITICAL': 'darkred',
        }
        color = colors.get(obj.risk_level, 'gray')
        if obj.is_suspicious:
            return format_html(
                '<span style="color: {}; font-weight: bold;">⚠️ {}</span>',
                color,
                obj.risk_level
            )
        return format_html(
            '<span style="color: {};">{}</span>',
            color,
            obj.risk_level
        )
    risk_display.short_description = 'Risk'
    
    def has_add_permission(self, request):
        return False  # Activities should only be created by the system
    
    def has_change_permission(self, request, obj=None):
        return False  # Activities should not be modified
    
    actions = ['mark_as_suspicious']
    
    @admin.action(description='Mark selected activities as suspicious')
    def mark_as_suspicious(self, request, queryset):
        queryset.update(is_suspicious=True, risk_level='HIGH')
