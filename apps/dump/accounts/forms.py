from django import forms
from django.contrib.auth.forms import UserCreationForm as BaseUserCreationForm, AuthenticationForm
from django.contrib.auth import authenticate
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError

from apps.core.models import Account
from .models import User, SubUser, AccountGroup
from apps.hr_staff.models import Department
from .permission_boundaries import get_account_groups_assigner_may_assign
from .services import set_user_account_role
from .validators import NoRestrictionPasswordValidator


class SetPasswordForm(forms.Form):
    """Form for setting a new password (e.g. required on first login after HR-created temp password)."""
    new_password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter new password',
            'autocomplete': 'new-password',
        }),
        label='New password',
    )
    new_password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm new password',
            'autocomplete': 'new-password',
        }),
        label='Confirm new password',
    )

    def clean_new_password1(self):
        password1 = self.cleaned_data.get('new_password1')
        if password1:
            validator = NoRestrictionPasswordValidator()
            try:
                validator.validate(password1)
            except ValidationError as e:
                raise ValidationError(e.messages[0])
        return password1

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('new_password1') != cleaned.get('new_password2'):
            raise ValidationError('The two password fields did not match.')
        return cleaned


class UserRegistrationForm(BaseUserCreationForm):
    """Form for user registration"""
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your email address'
        })
    )
    first_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your first name'
        })
    )
    last_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your last name'
        })
    )
    phone = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your phone number'
        })
    )
    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter password'
        })
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm password'
        })
    )

    class Meta:
        model = User
        fields = ('email', 'first_name', 'last_name', 'phone', 'password1', 'password2')

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise ValidationError("A user with this email already exists.")
        return email

    def clean_password1(self):
        password1 = self.cleaned_data.get('password1')
        if password1:
            # Use our custom validator instead of Django's default
            validator = NoRestrictionPasswordValidator()
            try:
                validator.validate(password1)
            except ValidationError as e:
                raise ValidationError(e.messages[0])
        return password1

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.phone = self.cleaned_data.get('phone', '')
        user.account = None  # Signal ensure_user_has_account creates Account on first save (single source of truth)
        if commit:
            user.save()
            # Account is created and linked by post_save signal (ensure_user_has_account); do not create here to avoid duplicates.
        return user


class UserLoginForm(AuthenticationForm):
    """Form for user login with email"""
    username = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your email address',
            'autofocus': True
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your password'
        })
    )

    def clean(self):
        username = self.cleaned_data.get('username')
        password = self.cleaned_data.get('password')

        if username and password:
            self.user_cache = authenticate(
                self.request,
                username=username,
                password=password
            )
            if self.user_cache is None:
                raise ValidationError("Invalid email or password.")
            else:
                self.confirm_login_allowed(self.user_cache)

        return self.cleaned_data


class UserProfileForm(forms.ModelForm):
    """Form for updating user profile"""
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'readonly': True
        })
    )
    first_name = forms.CharField(
        max_length=30,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your first name'
        })
    )
    last_name = forms.CharField(
        max_length=30,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your last name'
        })
    )
    phone = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your phone number'
        })
    )
    profile_picture = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': 'image/*'
        })
    )
    bio = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Tell us a little about yourself...'
        })
    )
    location = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your location'
        })
    )
    website = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your website'
        })
    )
    birth_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )

    class Meta:
        model = User
        fields = ('email', 'first_name', 'last_name', 'phone', 'profile_picture', 'bio', 'location', 'website', 'birth_date')

    def __init__(self, *args, **kwargs):
        # Optional linked Employee record so we can mirror HR profile fields
        self.linked_employee = kwargs.pop('linked_employee', None)
        super().__init__(*args, **kwargs)
        # If user has a linked Employee and some user fields are empty, fall back to Employee data
        if self.linked_employee:
            emp = self.linked_employee
            if not self.initial.get('phone') and getattr(emp, 'phone', None):
                self.initial['phone'] = emp.phone
            if not self.initial.get('birth_date') and getattr(emp, 'date_of_birth', None):
                self.initial['birth_date'] = emp.date_of_birth
            # Extra HR fields exposed on the profile form and stored on Employee
            self.fields['emp_position'] = forms.CharField(
                required=False,
                label='Position / Job Title',
                widget=forms.TextInput(attrs={
                    'class': 'form-control',
                    'placeholder': 'e.g. Software Engineer',
                }),
            )
            self.fields['emp_street_address'] = forms.CharField(
                required=False,
                label='Street Address',
                widget=forms.TextInput(attrs={
                    'class': 'form-control',
                    'placeholder': '123 Main Street',
                }),
            )
            self.fields['emp_city'] = forms.CharField(
                required=False,
                label='City',
                widget=forms.TextInput(attrs={
                    'class': 'form-control',
                    'placeholder': 'City',
                }),
            )
            self.fields['emp_state_province'] = forms.CharField(
                required=False,
                label='State / Province',
                widget=forms.TextInput(attrs={
                    'class': 'form-control',
                    'placeholder': 'State / Province',
                }),
            )
            self.fields['emp_zip_code'] = forms.CharField(
                required=False,
                label='Zip / Postal Code',
                widget=forms.TextInput(attrs={
                    'class': 'form-control',
                    'placeholder': 'Postal code',
                }),
            )
            self.fields['emp_emergency_contact_name'] = forms.CharField(
                required=False,
                label='Emergency Contact Name',
                widget=forms.TextInput(attrs={
                    'class': 'form-control',
                    'placeholder': 'Contact name',
                }),
            )
            self.fields['emp_emergency_contact_phone'] = forms.CharField(
                required=False,
                label='Emergency Contact Phone',
                widget=forms.TextInput(attrs={
                    'class': 'form-control',
                    'placeholder': 'Contact phone',
                }),
            )
            # Department dropdown, scoped to the same account
            account_id = getattr(emp, 'account_id', None)
            dept_qs = Department.objects.filter(account_id=account_id).order_by('name') if account_id else Department.objects.none()
            self.fields['emp_department'] = forms.ModelChoiceField(
                required=False,
                label='Department',
                queryset=dept_qs,
                widget=forms.Select(attrs={'class': 'form-select'}),
            )
            # Prefill from the Employee record
            self.initial['emp_position'] = emp.position or ''
            self.initial['emp_street_address'] = emp.street_address or ''
            self.initial['emp_city'] = emp.city or ''
            self.initial['emp_state_province'] = emp.state_province or ''
            self.initial['emp_zip_code'] = emp.zip_code or ''
            self.initial['emp_emergency_contact_name'] = emp.emergency_contact_name or ''
            self.initial['emp_emergency_contact_phone'] = emp.emergency_contact_phone or ''
            if emp.department_id:
                self.initial['emp_department'] = emp.department_id

    def save(self, commit=True):
        user = super().save(commit=commit)
        # Keep linked Employee contact/personal fields in sync so HR view matches team profile
        emp = getattr(self, 'linked_employee', None)
        if emp:
            changed = False
            if user.phone and emp.phone != user.phone:
                emp.phone = user.phone
                changed = True
            if user.birth_date and emp.date_of_birth != user.birth_date:
                emp.date_of_birth = user.birth_date
                changed = True
            # Mirror bio so Employee detail shows the same description
            if user.bio and getattr(emp, 'bio', '') != user.bio:
                emp.bio = user.bio
                changed = True
            # Extra contact and emergency fields written back to Employee
            for attr, field_name in (
                ('position', 'emp_position'),
                ('street_address', 'emp_street_address'),
                ('city', 'emp_city'),
                ('state_province', 'emp_state_province'),
                ('zip_code', 'emp_zip_code'),
                ('emergency_contact_name', 'emp_emergency_contact_name'),
                ('emergency_contact_phone', 'emp_emergency_contact_phone'),
            ):
                if field_name in self.cleaned_data:
                    new_val = self.cleaned_data.get(field_name, '') or ''
                    if getattr(emp, attr, '') != new_val:
                        setattr(emp, attr, new_val)
                        changed = True
            # Department relation
            if 'emp_department' in self.cleaned_data:
                new_dept = self.cleaned_data.get('emp_department')
                if new_dept != getattr(emp, 'department', None):
                    emp.department = new_dept
                    changed = True
            if changed:
                # Use a broad save since multiple fields may have changed
                emp.save()
        return user


class SubUserForm(forms.ModelForm):
    """
    Form for creating/editing team members (SubUsers).

    Role is drawn from AccountGroup (Roles & Permissions); only roles
    assignable by the current user are shown. is_staff is no longer used
    for permissions—use the Role dropdown instead.
    """
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Leave blank to keep current password'
        }),
        help_text='Required when creating. Leave blank when editing to keep current password.'
    )
    role = forms.ModelChoiceField(
        queryset=AccountGroup.objects.none(),
        required=True,
        empty_label='Select a role…',
        widget=forms.Select(attrs={
            'class': 'form-select',
            'aria-label': 'Role',
        }),
        help_text='Permissions are determined by this role. Only roles you can assign are listed.',
    )

    class Meta:
        model = SubUser
        fields = ('email', 'full_name', 'is_active')
        widgets = {
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Login email (must be unique)'
            }),
            'full_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Full display name'
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, account_owner=None, assigner=None, creating=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.account_owner = account_owner
        self.assigner = assigner or account_owner
        self.creating = creating
        if account_owner and hasattr(account_owner, 'account') and account_owner.account_id and self.assigner:
            # Live query: only existing AccountGroups the assigner may assign. Deleted roles
            # are removed from DB (AccountGroup + Group deleted), so they never appear here.
            self.fields['role'].queryset = get_account_groups_assigner_may_assign(
                account_owner.account, self.assigner
            )
        if creating:
            self.fields['password'].required = True
            self.fields['password'].help_text = 'Team member will use this to log in. No format or length restrictions.'
        # Editing: set initial role from linked_user's current account group
        if self.instance and self.instance.pk and self.instance.linked_user_id:
            from .models import AccountGroup as AG
            ag = AG.objects.filter(
                account_id=self.account_owner.account_id,
                group__in=self.instance.linked_user.groups.all(),
            ).first()
            if ag:
                self.fields['role'].initial = ag.pk

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if not email:
            return email
        qs = SubUser.objects.filter(email__iexact=email)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError('A team member with this email already exists.')
        # Reject only if this email is used by a real account owner (User who owns an Account).
        # Team members use a linked_user (User) that does NOT own an account, so we allow that.
        # When editing, also allow the current team member's linked_user to keep the same email.
        user_qs = User.objects.filter(
            email__iexact=email,
            owned_accounts__isnull=False,
        )
        if self.instance and self.instance.pk and getattr(self.instance, 'linked_user_id', None):
            user_qs = user_qs.exclude(pk=self.instance.linked_user_id)
        if user_qs.exists():
            raise ValidationError('This email is used by an account owner. Use a different email.')
        return email

    def clean_role(self):
        """Ensure selected role is one the assigner may assign (permission safety)."""
        role = self.cleaned_data.get('role')
        if not role or not self.account_owner or not getattr(self.account_owner, 'account_id', None):
            return role
        assigner = self.assigner or self.account_owner
        allowed = get_account_groups_assigner_may_assign(self.account_owner.account, assigner)
        if role.pk not in allowed.values_list('pk', flat=True):
            raise ValidationError('You may not assign this role. Choose a role you are allowed to assign.')
        return role

    def save(self, commit=True):
        sub_user = super().save(commit=False)
        # Meta.fields no longer includes is_staff; keep it unchanged when editing
        if self.instance and self.instance.pk:
            sub_user.is_staff = self.instance.is_staff
        else:
            sub_user.is_staff = False
        if self.account_owner:
            sub_user.account_owner = self.account_owner
        password = self.cleaned_data.get('password', '').strip()
        if password:
            sub_user.password_hash = make_password(password)
        elif sub_user.pk:
            pass
        else:
            raise ValidationError('Password is required when creating a team member.')

        account = self.account_owner.account if self.account_owner else None
        role = self.cleaned_data.get('role')

        if commit:
            sub_user.save()
            # Ensure linked Django User exists and assign role
            user = getattr(sub_user, 'linked_user', None)
            if not user and account:
                raw_password = self.cleaned_data.get('password')
                if not raw_password:
                    raise ValidationError('Password is required when creating a team member.')
                parts = (sub_user.full_name or '').strip().split(None, 1)
                first_name = (parts[0] if parts else sub_user.email)[:30]
                last_name = ((parts[1] if len(parts) > 1 else '') or sub_user.email)[:30]
                # Reuse existing User with this email if they are not an account owner
                # (e.g. orphaned linked_user from a previously deleted team member).
                existing = User.objects.filter(email__iexact=sub_user.email).first()
                if existing and not existing.owned_accounts.exists():
                    user = existing
                    user.account = account
                    user.first_name = first_name
                    user.last_name = last_name
                    user.is_active = sub_user.is_active
                    user.set_password(raw_password)
                    user.save(update_fields=['account', 'first_name', 'last_name', 'is_active', 'password'])
                else:
                    user = User(
                        account=account,
                        email=sub_user.email,
                        first_name=first_name,
                        last_name=last_name,
                        is_active=sub_user.is_active,
                        is_staff=False,
                    )
                    user.set_password(raw_password)
                    user.save()
                sub_user.linked_user = user
                sub_user.save(update_fields=['linked_user'])
            elif user:
                # Keep linked User in sync with SubUser (company account owner / auth user)
                user.email = sub_user.email
                parts = (sub_user.full_name or '').strip().split(None, 1)
                user.first_name = (parts[0] if parts else sub_user.email)[:30]
                user.last_name = ((parts[1] if len(parts) > 1 else '') or sub_user.email)[:30]
                user.is_active = sub_user.is_active
                raw_password = self.cleaned_data.get('password', '').strip()
                if raw_password:
                    user.set_password(raw_password)
                update_fields = ['email', 'first_name', 'last_name', 'is_active']
                if raw_password:
                    update_fields.append('password')
                user.save(update_fields=update_fields)
            if user and account:
                set_user_account_role(user, role)
        return sub_user


class AccountGroupForm(forms.ModelForm):
    """
    Form for creating/editing tenant-scoped roles (AccountGroup).

    Exposes:
    - role_name: human-friendly role name within the account.
    - full_company_visibility: model field.
    - full_hr_staff_role: convenience checkbox; when checked, all HR & Staff permissions
      (that the assigner may assign) are added to the role.
    - permissions: Django auth permissions assigned to the underlying Group.

    Privilege escalation prevention: permissions queryset is restricted to
    get_permissions_user_may_assign(user). No user may assign a permission
    they don't have, or assign auth permission/group management (non-delegatable).
    """

    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.none(),  # Set in __init__ from assigner's allowed set
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        help_text='Select the actions this role is allowed to perform. You can only assign permissions you have.'
    )
    full_hr_staff_role = forms.BooleanField(
        required=False,
        initial=False,
        label='Full HR & Staff role',
        help_text='When checked, this role is granted all HR & Staff permissions (dashboard, employees, departments, leave). You can still add other app permissions below.'
    )

    class Meta:
        model = AccountGroup
        fields = ('role_name', 'full_company_visibility')

    def __init__(self, *args, account: Account | None = None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.account = account
        self._assigner = user
        from .permission_boundaries import get_permissions_user_may_assign
        allowed = get_permissions_user_may_assign(user) if user else Permission.objects.none()
        self.fields['permissions'].queryset = allowed
        if self.instance and self.instance.pk:
            self.fields['permissions'].initial = self.instance.group.permissions.values_list('pk', flat=True)
            # Pre-check "Full HR & Staff role" when editing if role has all assignable HR permissions
            hr_perms = allowed.filter(content_type__app_label='hr_staff')
            if hr_perms.exists():
                role_perm_ids = set(self.instance.group.permissions.values_list('pk', flat=True))
                if all(p.pk in role_perm_ids for p in hr_perms):
                    self.fields['full_hr_staff_role'].initial = True
        self.fields['full_company_visibility'].widget.attrs.setdefault('class', 'form-check-input')
        self.fields['full_hr_staff_role'].widget.attrs.setdefault('class', 'form-check-input')

    def clean_permissions(self):
        """Ensure selected permissions are only those the assigner may assign (backend enforcement)."""
        selected = self.cleaned_data.get('permissions') or []
        allowed_ids = set(self.fields['permissions'].queryset.values_list('pk', flat=True))
        for perm in selected:
            if perm.pk not in allowed_ids:
                raise ValidationError(
                    'You may not assign permissions you do not have, or superuser-only permissions.'
                )
        return selected

    def clean_role_name(self):
        role_name = (self.cleaned_data.get('role_name') or '').strip()
        if not role_name:
            raise ValidationError('Role name is required.')

        # Enforce uniqueness per account at the form level for better UX.
        account = self.account or getattr(self.instance, 'account', None)
        if not account:
            return role_name

        qs = AccountGroup.objects.filter(account=account, role_name__iexact=role_name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError('A role with this name already exists for this account.')
        return role_name

    def save(self, commit=True):
        """
        Persist AccountGroup and synchronize underlying Group permissions.
        When full_hr_staff_role is checked, merge in all HR & Staff permissions the assigner may assign.
        """
        from .services import create_account_group, update_account_group_permissions

        role_name = self.cleaned_data['role_name']
        permissions_qs = self.cleaned_data.get('permissions') or []
        # Build set of app_label.codename; when "Full HR & Staff role" is checked, add all assignable hr_staff
        permission_specs_set = set()
        for p in permissions_qs:
            permission_specs_set.add(f"{p.content_type.app_label}.{p.codename}")
        if self.cleaned_data.get('full_hr_staff_role'):
            allowed = self.fields['permissions'].queryset
            for p in allowed.filter(content_type__app_label='hr_staff').select_related('content_type'):
                permission_specs_set.add(f"{p.content_type.app_label}.{p.codename}")
        # CRITICAL: Pass app_label.codename, not codename alone. Multiple apps share model names.
        permission_specs = list(permission_specs_set)

        # New instance: create AccountGroup + Group using the service.
        if not self.instance.pk:
            if not self.account:
                raise ValidationError('Account context is required when creating a role.')
            account_group = create_account_group(
                account=self.account,
                role_name=role_name,
                permission_codenames=permission_specs,
            )
            account_group.full_company_visibility = self.cleaned_data.get('full_company_visibility', False)
            account_group.save(update_fields=['full_company_visibility'])
            self.instance = account_group
            return account_group

        # Existing instance: update role_name, full_company_visibility, and group permissions.
        self.instance.role_name = role_name
        self.instance.full_company_visibility = self.cleaned_data.get('full_company_visibility', False)
        if commit:
            self.instance.save(update_fields=['role_name', 'full_company_visibility'])
            update_account_group_permissions(self.instance, permission_specs)
        return self.instance
