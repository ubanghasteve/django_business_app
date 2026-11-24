from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required, permission_required
from apps.core.mixins import ReadOnlyProtectionMixin
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.cache import never_cache
from django.contrib.auth.views import LoginView, LogoutView, PasswordResetView
from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView, ListView, TemplateView
from django.utils.decorators import method_decorator
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.http import require_POST
from datetime import timedelta
from .forms import UserRegistrationForm, UserLoginForm, UserProfileForm, SetPasswordForm, SubUserForm, AccountGroupForm
from .models import User, UserSession, UserActivity, SubUser, AccountGroup
from .security_utils import (
    create_user_session, end_user_session, get_client_ip,
    get_active_sessions, terminate_session, get_user_activity_summary,
    force_logout_all_account_sessions, get_account_and_session_user_ids,
)
from .services import (
    assign_user_to_account_group,
    remove_user_from_account_group,
    ensure_new_user_has_account_and_default_role,
)
from .permission_boundaries import get_account_groups_assigner_may_assign
from .default_role import DEFAULT_ONBOARDING_ROLE_NAME
from .permission_labels import (
    get_permissions_grouped_by_module,
    get_role_permissions_display,
)


class CustomLoginView(LoginView):
    """Custom login view using email authentication with security tracking"""
    form_class = UserLoginForm
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True
    success_url = reverse_lazy('core:dashboard')

    @method_decorator(ensure_csrf_cookie)
    def get(self, request, *args, **kwargs):
        """Ensure CSRF cookie is set when loading login page (helps with back button/cached form)"""
        response = super().get(request, *args, **kwargs)
        response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response['Pragma'] = 'no-cache'
        return response

    def get_context_data(self, **kwargs):
        """Pass flag so login template can show 'You were logged out by an administrator'."""
        from django.core.cache import cache
        from .security_utils import FORCE_LOGOUT_CACHE_KEY

        context = super().get_context_data(**kwargs)
        # Show message when redirected with ?reason=admin_logout or when session was in force-logout cache
        context['show_admin_logout_message'] = self.request.GET.get('reason') == 'admin_logout'
        if not context['show_admin_logout_message']:
            try:
                session_key = self.request.session.session_key
                if session_key:
                    force_logout_keys = cache.get(FORCE_LOGOUT_CACHE_KEY) or set()
                    if session_key in force_logout_keys:
                        force_logout_keys.discard(session_key)
                        cache.set(FORCE_LOGOUT_CACHE_KEY, force_logout_keys, timeout=600)
                        context['show_admin_logout_message'] = True
            except Exception:
                pass
        return context

    def form_valid(self, form):
        user = form.get_user()
        # Use Django's built-in login + redirect so session/cookie behavior is standard.
        response = super().form_valid(form)

        # Clear stale sub_user_id; set sub_user_id when logged in as team member (linked_user).
        if 'sub_user_id' in self.request.session:
            del self.request.session['sub_user_id']
        sub_user = getattr(user, 'linked_subuser', None)
        if sub_user:
            self.request.session['sub_user_id'] = str(sub_user.id)
            # CRITICAL: Ensure linked team member's Django User always points to the
            # same tenant Account as the account owner so company context (logo,
            # profile, etc.) is resolved correctly for team members.
            owner_account = getattr(getattr(sub_user, 'account_owner', None), 'account', None)
            if owner_account and user.account_id != owner_account.id:
                user.account = owner_account
                # This will not create a new Account because account_id is set; the
                # post_save signal respects explicit account assignments.
                user.save(update_fields=['account'])

        # Security tracking only (must not call request.session.create() or replace session).
        try:
            client_ip = self.request.POST.get('client_ip', '').strip()
            client_device_type = self.request.POST.get('device_type_hint', '').strip()
            gps_location = None
            geo_lat = self.request.POST.get('geo_latitude', '').strip()
            geo_lon = self.request.POST.get('geo_longitude', '').strip()
            if geo_lat and geo_lon:
                try:
                    gps_location = {
                        'latitude': float(geo_lat),
                        'longitude': float(geo_lon),
                        'city': self.request.POST.get('geo_city', '').strip(),
                        'region': self.request.POST.get('geo_region', '').strip(),
                        'country': self.request.POST.get('geo_country', '').strip(),
                        'accuracy': float(self.request.POST.get('geo_accuracy', '0') or '0'),
                    }
                except (ValueError, TypeError):
                    gps_location = None
            session = create_user_session(
                self.request,
                self.request.user,
                client_reported_ip=client_ip or None,
                gps_location=gps_location,
                sub_user=sub_user,
                client_device_type=client_device_type or None,
            )
            who_logged = f"{sub_user.full_name} (team member)" if sub_user else (self.request.user.get_full_name() or self.request.user.email)
            from .security_utils import get_account_for_activity
            account = get_account_for_activity(request=self.request, user=self.request.user)
            UserActivity.log_activity(
                user=self.request.user,
                session=session,
                sub_user=sub_user,
                account=account,
                activity_type='LOGIN',
                description=f"{who_logged} logged in from {session.device_info} ({session.location_info})",
                ip_address=session.ip_address,
                user_agent=session.user_agent,
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Failed to create security session: {e}")

        messages.success(self.request, 'You have been logged in successfully.')
        # Force password change on first login (e.g. after HR created portal with temp password).
        if getattr(user, 'force_password_change', False):
            from django.urls import reverse
            response['Location'] = reverse('accounts:password_change_required')
        else:
            # Employee portal only (no full HR): send them to their HR & Staff dashboard.
            if user.has_perm('hr_staff.view_own_hr_dashboard') and not user.has_perm('hr_staff.view_hr_dashboard'):
                from django.urls import reverse
                response['Location'] = reverse('hr_staff:employee_portal_dashboard')
        # Prevent browser caching - ensures session cookie is always fresh in Chrome
        response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'
        return response

    def form_invalid(self, form):
        # Log failed login attempt
        try:
            email = form.data.get('username', '')
            UserActivity.log_activity(
                user=None,
                activity_type='LOGIN_FAILED',
                description=f"Failed login attempt for email: {email}",
                ip_address=get_client_ip(self.request),
                user_agent=self.request.META.get('HTTP_USER_AGENT', ''),
                extra_data={'attempted_email': email},
                risk_level='MEDIUM',
            )
        except Exception:
            pass
        
        messages.error(self.request, 'Invalid email or password.')
        return super().form_invalid(form)


class CustomLogoutView(LogoutView):
    """Custom logout view with security tracking"""
    next_page = reverse_lazy('core:landing_page')
    template_name = None  # Don't render a template, just redirect

    def get(self, request, *args, **kwargs):
        """Handle GET requests for logout"""
        self._end_security_session(request)
        messages.success(request, 'You have been logged out successfully.')
        return self.logout(request)

    def post(self, request, *args, **kwargs):
        """Handle POST requests for logout"""
        self._end_security_session(request)
        messages.success(request, 'You have been logged out successfully.')
        return self.logout(request)

    def _end_security_session(self, request):
        """End the security session and log the logout"""
        try:
            if request.user.is_authenticated:
                end_user_session(request, request.user)
            # Clear team member session
            if 'sub_user_id' in request.session:
                del request.session['sub_user_id']
        except Exception:
            pass

    def logout(self, request):
        """Perform the actual logout"""
        from django.contrib.auth import logout
        logout(request)
        return redirect(self.next_page)


class RegisterView(CreateView):
    """User registration view"""
    model = User
    form_class = UserRegistrationForm
    template_name = 'accounts/register.html'
    success_url = reverse_lazy('accounts:login')

    def form_valid(self, form):
        user = form.save()
        ensure_new_user_has_account_and_default_role(user)
        messages.success(
            self.request,
            f'Account created successfully for {user.email}. You can now log in.'
        )
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)


@login_required
def profile_view(request):
    """View user profile"""
    # Get theme colors from company profile
    from apps.core.utils import get_company_context
    company_context = get_company_context(request.user, request)
    # Role names for this user (from AccountGroup, scoped to user's account)
    user_role_names = []
    if getattr(request.user, 'account_id', None):
        user_role_names = list(
            AccountGroup.objects.filter(
                account_id=request.user.account_id,
                group__in=request.user.groups.all(),
            ).values_list('role_name', flat=True).order_by('role_name')
        )
    # Optional linked HR Employee profile so we can show employment details on the profile page
    try:
        from apps.hr_staff.querysets import get_linked_employee_for_user
        linked_employee = get_linked_employee_for_user(request.user)
    except Exception:
        linked_employee = None
    context = {
        'user': request.user,
        'user_role_names': user_role_names,
        'employee': linked_employee,
        'title': 'My Profile',
        'theme_primary_color': company_context.get('theme_primary_color', '#e91e63'),
        'theme_secondary_color': company_context.get('theme_secondary_color', '#f8f9fa'),
    }
    return render(request, 'accounts/profile_view.html', context)


@login_required
@never_cache
def password_change_required(request):
    """
    Shown when user.force_password_change is True (e.g. first login after HR created portal account).
    User must set a new password; we never ask for the temp password. On success clear the flag.
    """
    if not getattr(request.user, 'force_password_change', False):
        return redirect('core:dashboard')
    if request.method == 'POST':
        form = SetPasswordForm(request.POST)
        if form.is_valid():
            request.user.set_password(form.cleaned_data['new_password1'])
            request.user.force_password_change = False
            request.user.save(update_fields=['password', 'force_password_change'])
            messages.success(request, 'Your password has been set. You can now use it to log in.')
            if request.user.has_perm('hr_staff.view_own_hr_dashboard') and not request.user.has_perm('hr_staff.view_hr_dashboard'):
                return redirect('hr_staff:employee_portal_dashboard')
            return redirect('core:dashboard')
    else:
        form = SetPasswordForm()
    return render(request, 'accounts/password_change_required.html', {'form': form})


@method_decorator(login_required, name='dispatch')
class ProfileEditView(ReadOnlyProtectionMixin, UpdateView):
    """Edit user profile view"""
    model = User
    form_class = UserProfileForm
    template_name = 'accounts/profile_edit.html'
    success_url = reverse_lazy('accounts:profile')

    def get_object(self):
        return self.request.user

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Get theme colors from company profile
        from apps.core.utils import get_company_context
        company_context = get_company_context(self.request.user, self.request)
        context['theme_primary_color'] = company_context.get('theme_primary_color', '#e91e63')
        context['theme_secondary_color'] = company_context.get('theme_secondary_color', '#f8f9fa')
        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        # Pass linked Employee into the form so it can keep HR profile fields in sync
        try:
            from apps.hr_staff.querysets import get_linked_employee_for_user
            kwargs['linked_employee'] = get_linked_employee_for_user(self.request.user)
        except Exception:
            pass
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, 'Your profile has been updated successfully!')
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)


# Keep the old ProfileView for backward compatibility
@method_decorator(login_required, name='dispatch')
class ProfileView(ReadOnlyProtectionMixin, UpdateView):
    """User profile view (legacy)"""
    model = User
    form_class = UserProfileForm
    template_name = 'accounts/profile_edit.html'
    success_url = reverse_lazy('accounts:profile')

    def get_object(self):
        return self.request.user

    def form_valid(self, form):
        messages.success(self.request, 'Your profile has been updated successfully.')
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)


@login_required
def dashboard(request):
    """Dashboard view for authenticated users"""
    context = {
        'user': request.user,
        'title': 'Dashboard'
    }
    return render(request, 'accounts/dashboard.html', context)


def register_view(request):
    """Function-based registration view"""
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            ensure_new_user_has_account_and_default_role(user)
            messages.success(
                request,
                f'Account created successfully for {user.email}. You can now log in.'
            )
            return redirect('accounts:login')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = UserRegistrationForm()
    
    return render(request, 'accounts/register.html', {'form': form})


def login_view(request):
    """Function-based login view"""
    if request.method == 'POST':
        form = UserLoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, 'You have been logged in successfully.')
            next_url = request.GET.get('next', 'dashboard')
            return redirect(next_url)
        else:
            messages.error(request, 'Invalid email or password.')
    else:
        form = UserLoginForm()
    
    return render(request, 'accounts/login.html', {'form': form})


def logout_view(request):
    """Function-based logout view that handles all request methods with security tracking"""
    if request.user.is_authenticated:
        # End security session and log LOGOUT (always logs at least one activity)
        try:
            end_user_session(request, request.user)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("Error in end_user_session on logout: %s", e)
        # Clear team member session
        if 'sub_user_id' in request.session:
            try:
                del request.session['sub_user_id']
            except KeyError:
                pass
        logout(request)
        messages.success(request, 'You have been logged out successfully.')
    return redirect('core:landing_page')


class CustomPasswordResetView(PasswordResetView):
    """Custom password reset view that provides better user feedback"""
    template_name = 'accounts/password_reset_form.html'
    email_template_name = 'accounts/password_reset_email.html'
    success_url = reverse_lazy('accounts:password_reset_done')
    
    def form_valid(self, form):
        """Process the form and provide appropriate feedback"""
        email = form.cleaned_data['email']
        
        # Check if user exists
        try:
            user = User.objects.get(email=email)
            # User exists, proceed with normal password reset
            messages.success(
                self.request,
                f'Password reset instructions have been sent to {email}. '
                'Please check your inbox and spam folder.'
            )
            return super().form_valid(form)
        except User.DoesNotExist:
            # User doesn't exist, provide helpful message
            messages.info(
                self.request,
                f'No account found with email {email}. '
                'Please check your email address or register for a new account.'
            )
            # Still redirect to done page but with different message
            return redirect(self.success_url)
    
    def form_invalid(self, form):
        """Handle form errors"""
        messages.error(self.request, 'Please enter a valid email address.')
        return super().form_invalid(form)


# =============================================================================
# SECURITY DASHBOARD VIEWS
# =============================================================================

def _can_view_activity_log(user):
    """Allow view_activity_log (preferred) or legacy view_useractivity."""
    return (
        user.has_perm('accounts.view_activity_log') or
        user.has_perm('accounts.view_useractivity')
    )


@login_required
@never_cache
def security_dashboard(request):
    """
    Security dashboard showing user sessions, activities, and security overview.
    All data is scoped to the current account (request.user.account)—tenant-safe.
    Requires view_activity_log or view_useractivity.
    """
    if not _can_view_activity_log(request.user):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied('You do not have permission to view the security dashboard.')
    from apps.core.utils import get_company_context
    
    user = request.user
    account, account_user_ids = get_account_and_session_user_ids(request)
    if not account:
        account = getattr(user, 'account_id', None) and user.account
        account_user_ids = list(User.objects.filter(account=account).values_list('pk', flat=True)) if account else [user.pk]
    company_context = get_company_context(user, request)
    
    thirty_days_ago = timezone.now() - timedelta(days=30)
    
    # account_user_ids from get_account_and_session_user_ids (owner + account users + team linked_users)
    
    # Accurate full counts for dashboard cards (all account sessions)
    active_sessions_count = UserSession.objects.filter(
        user_id__in=account_user_ids,
        is_active=True
    ).count()
    
    logins_count_30d = UserSession.objects.filter(
        user_id__in=account_user_ids,
        login_time__gte=thirty_days_ago
    ).count()
    
    # Activity counts: filter by account when set (tenant-safe)
    if account:
        activity_base = UserActivity.objects.filter(account=account)
    else:
        activity_base = UserActivity.objects.filter(user=user)
    
    suspicious_count = (
        activity_base.filter(is_suspicious=True).count() +
        UserSession.objects.filter(user_id__in=account_user_ids, is_suspicious=True).count()
    )
    
    # Lists for display: all account sessions (owner + team members) so team logins/logouts are visible
    active_sessions = UserSession.objects.filter(
        user_id__in=account_user_ids,
        is_active=True
    ).select_related('user', 'sub_user').order_by('-last_activity')[:10]
    
    recent_sessions = UserSession.objects.filter(
        user_id__in=account_user_ids,
        login_time__gte=thirty_days_ago
    ).select_related('user', 'sub_user').order_by('-login_time')[:20]
    
    seven_days_ago = timezone.now() - timedelta(days=7)
    recent_activities = (activity_base.filter(timestamp__gte=seven_days_ago)
                         .order_by('-timestamp')[:50])
    
    suspicious_activities = (activity_base.filter(is_suspicious=True)
                             .order_by('-timestamp')[:10])
    
    suspicious_sessions = UserSession.objects.filter(
        user_id__in=account_user_ids,
        is_suspicious=True
    ).select_related('user', 'sub_user').order_by('-login_time')[:10]
    
    # Activity summary (account-scoped when possible)
    activity_summary = get_user_activity_summary(user, days=30, account=account)
    
    # Significant activities count (last 30 days, excluding PAGE_VIEW) for dashboard display
    significant_activities_count_30d = (activity_base.filter(timestamp__gte=thirty_days_ago)
                                        .exclude(activity_type='PAGE_VIEW').count())
    
    # Build breakdown by type (type_code, display_name, count) for template links
    activity_type_display = dict(getattr(UserActivity, 'ACTIVITY_TYPES', []))
    activity_breakdown = [
        (k, activity_type_display.get(k, k.replace('_', ' ').title()), v)
        for k, v in sorted(activity_summary.get('by_type', {}).items(), key=lambda x: -x[1])
    ]
    
    # Activities per day (last 30 days) for daily breakdown
    from django.db.models import Count
    from django.db.models.functions import TruncDate
    from collections import defaultdict
    activities_per_day = (
        activity_base.filter(timestamp__gte=thirty_days_ago)
        .annotate(date=TruncDate('timestamp'))
        .values('date')
        .annotate(count=Count('id'))
        .order_by('-date')[:30]
    )
    
    # Breakdown by type per day (date, list of (type_code, display_name, count)) for clickable badges
    per_day_by_type = (
        activity_base.filter(timestamp__gte=thirty_days_ago)
        .annotate(date=TruncDate('timestamp'))
        .values('date', 'activity_type')
        .annotate(count=Count('id'))
        .order_by('-date')
    )
    by_day = defaultdict(list)
    for row in per_day_by_type:
        date_val = row['date']
        type_code = row['activity_type']
        count = row['count']
        display_name = activity_type_display.get(type_code, type_code.replace('_', ' ').title())
        by_day[date_val].append((type_code, display_name, count))
    activity_breakdown_per_day = []
    for date_val in sorted(by_day.keys(), reverse=True)[:30]:
        breakdown = sorted(by_day[date_val], key=lambda x: -x[2])
        activity_breakdown_per_day.append((date_val, breakdown))
    
    current_session_id = request.session.get('security_session_id')
    sub_users = user.sub_users.all().order_by('full_name')
    
    context = {
        'title': 'Security Dashboard',
        'sub_users': sub_users,
        'activities_per_day': activities_per_day,
        'active_sessions_count': active_sessions_count,
        'logins_count_30d': logins_count_30d,
        'active_sessions': active_sessions,
        'recent_sessions': recent_sessions,
        'recent_activities': recent_activities,
        'suspicious_activities': suspicious_activities,
        'suspicious_sessions': suspicious_sessions,
        'suspicious_count': suspicious_count,
        'activity_summary': activity_summary,
        'significant_activities_count_30d': significant_activities_count_30d,
        'activity_breakdown': activity_breakdown,
        'activity_breakdown_per_day': activity_breakdown_per_day,
        'current_session_id': current_session_id,
        'last_updated': timezone.now(),
        'theme_primary_color': company_context.get('theme_primary_color', '#e91e63'),
        'theme_secondary_color': company_context.get('theme_secondary_color', '#f8f9fa'),
    }
    
    return render(request, 'accounts/security_dashboard.html', context)


# =============================================================================
# TEAM MEMBERS (SUBUSERS) - Multiple users, same account, individual tracking
# Only staff can manage team members (create, edit, delete, assign passwords).
# =============================================================================

def _get_request_account(request):
    """Get the current account for tenant scope. Prefer request.company.account, fallback request.user.account."""
    if getattr(request, 'company', None) and hasattr(request.company, 'account') and request.company.account_id:
        return request.company.account
    return getattr(request.user, 'account', None)


@login_required
@permission_required('accounts.view_subuser', raise_exception=True)
@never_cache
def subuser_list(request):
    """Manage team members who can log in to this account with their own password.
    Visibility is company-wide: all SubUsers belonging to request.company.account are shown.
    Optional search is applied inside the tenant-scoped queryset only, so data isolation and
    role-based access control remain enforced by the existing filters and permissions.
    """
    account = _get_request_account(request)
    if not account:
        return HttpResponseForbidden('You must belong to an account to view team members.')
    # Company-wide: all SubUsers for this account (account_owner belongs to this account)
    base_qs = (
        SubUser.objects.filter(account_owner__account=account)
        .select_related('account_owner')
        .order_by('full_name')
    )

    search_query = (request.GET.get('search') or '').strip()
    if search_query:
        from django.db.models import Q
        # Case-insensitive partial match on name or email within the current account only.
        base_qs = base_qs.filter(
            Q(full_name__icontains=search_query)
            | Q(email__icontains=search_query)
        )

    sub_users = base_qs
    # Use request.company (set by middleware) to avoid duplicate get_company_profile_for_user
    company = getattr(request, 'company', None)
    if company:
        theme_primary = getattr(company, 'primary_color', None) or '#e91e63'
        theme_secondary = getattr(company, 'secondary_color', None) or '#f8f9fa'
    else:
        from apps.core.utils import get_company_context
        company_context = get_company_context(request.user, request)
        theme_primary = company_context.get('theme_primary_color', '#e91e63')
        theme_secondary = company_context.get('theme_secondary_color', '#f8f9fa')

    context = {
        'title': 'Team Members',
        'sub_users': sub_users,
        'theme_primary_color': theme_primary,
        'theme_secondary_color': theme_secondary,
        'search_query': search_query,
        'total_count': base_qs.count(),
    }
    return render(request, 'accounts/subuser_list.html', context)


@login_required
@permission_required('accounts.add_subuser', raise_exception=True)
@ensure_csrf_cookie
def subuser_create(request):
    """Add a new team member. New SubUser is tied to account.owner so they appear in company-wide list."""
    account = _get_request_account(request)
    if not account:
        return HttpResponseForbidden('You must belong to an account to add team members.')
    # SubUser must belong to the account owner so they appear in company-wide team list
    account_owner_user = account.owner
    assignable_roles = get_account_groups_assigner_may_assign(account, request.user)
    if not assignable_roles.exists():
        messages.warning(
            request,
            'Create at least one role in Roles & Permissions before adding team members.'
        )
    if request.method == 'POST':
        role_id = request.POST.get('role')
        if role_id:
            try:
                role_id_int = int(role_id)
                if role_id_int not in assignable_roles.values_list('pk', flat=True):
                    return HttpResponseForbidden('You may not assign this role.')
            except (ValueError, TypeError):
                return HttpResponseForbidden('Invalid role.')
        form = SubUserForm(
            request.POST,
            account_owner=account_owner_user,
            assigner=request.user,
            creating=True
        )
        if form.is_valid():
            role = form.cleaned_data.get('role')
            if role and role.account_id != account.pk:
                return HttpResponseForbidden('Invalid role for this account.')
            if role and role.pk not in assignable_roles.values_list('pk', flat=True):
                return HttpResponseForbidden('You may not assign this role.')
            form.save()
            messages.success(request, f'Team member {form.cleaned_data["full_name"]} added. They can now log in with their email and the password you set.')
            return redirect('accounts:subuser_list')
    else:
        form = SubUserForm(account_owner=account_owner_user, assigner=request.user, creating=True)

    from apps.core.utils import get_company_context
    company_context = get_company_context(request.user, request)
    context = {
        'title': 'Add Team Member',
        'form': form,
        'theme_primary_color': company_context.get('theme_primary_color', '#e91e63'),
    }
    return render(request, 'accounts/subuser_form.html', context)


@login_required
@permission_required('accounts.change_subuser', raise_exception=True)
@ensure_csrf_cookie
def subuser_edit(request, subuser_id):
    """Edit a team member. Access by company scope: any SubUser in request.company.account."""
    account = _get_request_account(request)
    if not account:
        return HttpResponseForbidden('You must belong to an account to edit team members.')
    try:
        sub_user = SubUser.objects.get(id=subuser_id, account_owner__account=account)
    except SubUser.DoesNotExist:
        messages.error(request, 'Team member not found.')
        return redirect('accounts:subuser_list')

    if request.method == 'POST':
        form = SubUserForm(
            request.POST,
            instance=sub_user,
            account_owner=sub_user.account_owner,
            assigner=request.user,
            creating=False
        )
        if form.is_valid():
            role = form.cleaned_data.get('role')
            if role and (role.account_id != account.pk or role.pk not in get_account_groups_assigner_may_assign(account, request.user).values_list('pk', flat=True)):
                return HttpResponseForbidden('You may not assign this role.')
            form.save()
            messages.success(request, f'Team member {sub_user.full_name} updated.')
            return redirect('accounts:subuser_list')
    else:
        form = SubUserForm(
            instance=sub_user,
            account_owner=sub_user.account_owner,
            assigner=request.user,
            creating=False
        )

    from apps.core.utils import get_company_context
    company_context = get_company_context(request.user, request)
    context = {
        'title': 'Edit Team Member',
        'form': form,
        'sub_user': sub_user,
        'theme_primary_color': company_context.get('theme_primary_color', '#e91e63'),
    }
    return render(request, 'accounts/subuser_form.html', context)


@login_required
@permission_required('accounts.delete_subuser', raise_exception=True)
@require_POST
def subuser_delete(request, subuser_id):
    """Remove a team member. Access by company scope: any SubUser in request.company.account.
    Also deletes the linked Django User so they are removed from the account/auth user table."""
    account = _get_request_account(request)
    if not account:
        return HttpResponseForbidden('You must belong to an account to remove team members.')
    try:
        sub_user = SubUser.objects.get(id=subuser_id, account_owner__account=account)
        name = sub_user.full_name
        linked_user = getattr(sub_user, 'linked_user', None)
        if linked_user and getattr(account, 'owner_id', None) == linked_user.id:
            messages.error(request, 'Cannot remove the account owner.')
            return redirect('accounts:subuser_list')
        if linked_user:
            linked_user.delete()
        sub_user.delete()
        messages.success(request, f'Team member {name} removed.')
    except SubUser.DoesNotExist:
        messages.error(request, 'Team member not found.')
    return redirect('accounts:subuser_list')


# =============================================================================
# ACCOUNT ROLES (GROUPS & PERMISSIONS) - Per-account role management
# =============================================================================


@login_required
@permission_required('auth.view_group', raise_exception=True)
def account_role_list(request):
    """
    List all roles (AccountGroup) for the current user's account.
    Company-scoped; uses _get_request_account so team members see same list as owner.
    Permissions are displayed using the same labels and grouping as Create/Edit Role pages.
    """
    account = _get_request_account(request)
    if not account:
        return HttpResponseForbidden('You must belong to an account to view roles.')
    # Base tenant-scoped queryset: roles for the current account only
    roles_qs = (
        AccountGroup.objects.filter(account=account)
        .select_related('group')
        .order_by('role_name')
    )

    # Optional search within this account's roles only (data isolation preserved)
    search_query = (request.GET.get('search') or '').strip()
    if search_query:
        # Search strictly by role name (case-insensitive, partial match) within this account only.
        # We intentionally do NOT search by permission name/codename here, as requested.
        roles_qs = roles_qs.filter(role_name__icontains=search_query)

    roles = roles_qs
    # Attach display_grouped, display_grouped_full, and permission_more_count for each role (same labels as Create/Edit)
    # Load permissions explicitly per role so the list always reflects DB (avoids prefetch cache issues)
    for role in roles:
        perms_list = list(
            role.group.permissions.select_related('content_type').all()
        )
        display_grouped, more_count = get_role_permissions_display(perms_list, max_visible=5)
        role.display_grouped = display_grouped
        role.permission_more_count = more_count
        role.display_grouped_full = get_permissions_grouped_by_module(perms_list)
    context = {
        'title': 'Roles & Permissions',
        'roles': roles,
        'search_query': search_query,
        'total_count': roles_qs.count(),
    }
    return render(request, 'accounts/role_list.html', context)


@login_required
@permission_required('auth.add_group', raise_exception=True)
def account_role_create(request):
    """
    Create a new tenant-scoped role for the current account.
    """
    account = _get_request_account(request)
    if not account:
        return HttpResponseForbidden('You must belong to an account to create roles.')

    if request.method == 'POST':
        form = AccountGroupForm(request.POST, account=account, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Role created successfully.')
            return redirect('accounts:role_list')
    else:
        # Optional: pre-fill role name and checkboxes from query (e.g. ?role_name=Company+Read+Only or ?role_name=HR&full_hr_staff=1)
        initial = {}
        if request.GET.get('role_name'):
            initial['role_name'] = request.GET.get('role_name', '').strip()
            if initial['role_name'].lower() == 'company read only':
                initial['full_company_visibility'] = True
        if request.GET.get('full_hr_staff') == '1' or (request.GET.get('full_hr_staff') or '').lower() == 'true':
            initial['full_hr_staff_role'] = True
            if not initial.get('role_name'):
                initial['role_name'] = 'HR'
        form = AccountGroupForm(account=account, user=request.user, initial=initial)

    # Build grouped permissions with human-readable labels for display
    permissions_qs = form.fields['permissions'].queryset
    grouped_permissions = get_permissions_grouped_by_module(permissions_qs)
    if request.method == 'POST':
        selected_permission_ids = set(int(x) for x in request.POST.getlist('permissions') if x.isdigit())
    else:
        initial = form.fields['permissions'].initial
        selected_permission_ids = set(initial) if initial is not None else set()

    context = {
        'title': 'Create Role',
        'form': form,
        'grouped_permissions': grouped_permissions,
        'selected_permission_ids': selected_permission_ids,
    }
    return render(request, 'accounts/role_form.html', context)


@login_required
@permission_required('auth.change_group', raise_exception=True)
def account_role_edit(request, role_id: int):
    """
    Edit an existing tenant-scoped role for the current account.
    """
    account = _get_request_account(request)
    if not account:
        return HttpResponseForbidden('You must belong to an account to edit roles.')
    role = get_object_or_404(AccountGroup, pk=role_id, account=account)

    if request.method == 'POST':
        form = AccountGroupForm(request.POST, instance=role, account=account, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Role updated successfully.')
            return redirect('accounts:role_list')
    else:
        form = AccountGroupForm(instance=role, account=account, user=request.user)

    # Build grouped permissions with human-readable labels for display
    permissions_qs = form.fields['permissions'].queryset
    grouped_permissions = get_permissions_grouped_by_module(permissions_qs)
    if request.method == 'POST':
        selected_permission_ids = set(int(x) for x in request.POST.getlist('permissions') if x.isdigit())
    else:
        initial = form.fields['permissions'].initial
        selected_permission_ids = set(initial) if initial is not None else set()

    context = {
        'title': 'Edit Role',
        'form': form,
        'role': role,
        'grouped_permissions': grouped_permissions,
        'selected_permission_ids': selected_permission_ids,
    }
    return render(request, 'accounts/role_form.html', context)


@login_required
@permission_required('auth.delete_group', raise_exception=True)
@require_POST
def account_role_delete(request, role_id: int):
    """
    Delete an AccountGroup and its underlying Group for the current account.
    Removes the group from all users first, then deletes AccountGroup and Group
    so the role no longer appears anywhere (e.g. Add Team Member dropdown).
    """
    from .services import remove_group_from_all_users_and_delete
    account = _get_request_account(request)
    if not account:
        return HttpResponseForbidden('You must belong to an account to delete roles.')
    role = get_object_or_404(AccountGroup, pk=role_id, account=account)
    role_name = role.role_name
    remove_group_from_all_users_and_delete(role)
    messages.success(request, f'Role "{role_name}" deleted.')
    return redirect('accounts:role_list')


def _get_account_member_user_ids(account):
    """
    Authoritative list of user IDs who are valid members of this account for role display:
    - Account owner
    - linked_user of each active SubUser under this account (account_owner.account == account).
    Excludes deleted/inactive SubUsers so the role members page never shows stale entries.
    """
    owner_id = getattr(account, 'owner_id', None)
    if not owner_id:
        return set()
    # Live query: active SubUsers for this account with a linked_user
    team_user_ids = set(
        SubUser.objects.filter(
            account_owner__account=account,
            is_active=True,
        ).exclude(
            linked_user_id__isnull=True,
        ).values_list('linked_user_id', flat=True).distinct()
    )
    return {owner_id} | team_user_ids


@login_required
@permission_required('auth.change_group', raise_exception=True)
def account_role_members(request, role_id: int):
    """
    Manage which users in the current account belong to a given role.
    Membership list reflects current DB state: live query for role.group.user_set
    so removed members disappear immediately. No cached querysets.
    """
    account = _get_request_account(request)
    if not account:
        return HttpResponseForbidden('You must belong to an account to manage role members.')
    role = get_object_or_404(AccountGroup, pk=role_id, account=account)

    member_ids = _get_account_member_user_ids(account)
    all_users = User.objects.filter(pk__in=member_ids, is_active=True).order_by('first_name', 'last_name', 'email')
    # Source of truth: current members from role's group (live query, no cache)
    current_member_ids = list(role.group.user_set.values_list('pk', flat=True))

    if request.method == 'POST':
        from django.core.exceptions import PermissionDenied
        from .permission_boundaries import role_permissions_are_subset_of_user

        if not role_permissions_are_subset_of_user(role, request.user):
            raise PermissionDenied(
                'You cannot assign users to this role because it grants permissions you do not have.'
            )

        is_default_role = role.role_name == DEFAULT_ONBOARDING_ROLE_NAME
        selected_ids = request.POST.getlist('user_ids')
        selected_ids = [int(uid) for uid in selected_ids] if selected_ids else []

        current_member_ids_set = set(current_member_ids)
        for user in all_users:
            is_selected = user.id in selected_ids
            is_member = user.id in current_member_ids_set

            if is_selected and not is_member:
                # Adding user to this role. Only superusers may assign elevated roles.
                if not is_default_role and not request.user.is_superuser:
                    raise PermissionDenied(
                        'Only a superuser may assign users to roles other than the default onboarding role.'
                    )
                assign_user_to_account_group(user, role)
            elif not is_selected and is_member:
                # Removing user from this role. Only superusers may remove from default role.
                if is_default_role and not request.user.is_superuser:
                    raise PermissionDenied(
                        'Only a superuser may remove a user from the default onboarding role.'
                    )
                remove_user_from_account_group(user, role)

        messages.success(request, 'Role members updated successfully.')
        return redirect('accounts:role_members', role_id=role.id)

    context = {
        'title': f'Members of {role.role_name}',
        'role': role,
        'all_users': all_users,
        'current_member_ids': current_member_ids,
    }
    return render(request, 'accounts/role_members.html', context)


@login_required
@permission_required('accounts.view_usersession', raise_exception=True)
def session_history(request):
    """
    View all login sessions for the account (owner + team members). Company-scoped.
    """
    from apps.core.utils import get_company_context
    account = _get_request_account(request)
    company_context = get_company_context(request.user, request)
    if not account:
        return HttpResponseForbidden('You must belong to an account to view sessions.')
    account_user_ids = list(User.objects.filter(account=account).values_list('pk', flat=True))
    sessions = UserSession.objects.filter(user_id__in=account_user_ids).select_related('user', 'sub_user').order_by('-login_time')
    
    # Filter by status if provided
    status_filter = request.GET.get('status', '')
    if status_filter == 'active':
        sessions = sessions.filter(is_active=True)
    elif status_filter == 'ended':
        sessions = sessions.filter(is_active=False)
    elif status_filter == 'suspicious':
        sessions = sessions.filter(is_suspicious=True)
    
    # Simple pagination
    page = int(request.GET.get('page', 1))
    per_page = 25
    total = sessions.count()
    sessions = sessions[(page-1)*per_page:page*per_page]
    
    context = {
        'title': 'Session History',
        'sessions': sessions,
        'status_filter': status_filter,
        'page': page,
        'per_page': per_page,
        'total': total,
        'total_pages': (total + per_page - 1) // per_page,
        'theme_primary_color': company_context.get('theme_primary_color', '#e91e63'),
        'theme_secondary_color': company_context.get('theme_secondary_color', '#f8f9fa'),
    }
    
    return render(request, 'accounts/session_history.html', context)


@login_required
def activity_log(request):
    """
    View all activities for the current account (tenant-safe).
    Filter by account so owner and team members see the same account's activity log.
    Requires view_activity_log or view_useractivity.
    """
    if not _can_view_activity_log(request.user):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied('You do not have permission to view the activity log.')
    from apps.core.utils import get_company_context
    
    user = request.user
    account = getattr(user, 'account_id', None) and user.account
    company_context = get_company_context(user, request)
    
    # Root queryset: tenant-safe (account or single-user)
    if account:
        root_qs = UserActivity.objects.filter(account=account)
    else:
        root_qs = UserActivity.objects.filter(user=user)
    
    # Filter by type if provided
    activity_type = request.GET.get('type', '')
    activities_qs = root_qs
    if activity_type:
        activities_qs = activities_qs.filter(activity_type=activity_type)
    
    # Significant only: exclude PAGE_VIEW so you see only logins, creates, updates, deletes, etc.
    significant_only = request.GET.get('significant_only', '') == '1'
    if significant_only:
        activities_qs = activities_qs.exclude(activity_type='PAGE_VIEW')
    
    # Filter by app if provided
    app_filter = request.GET.get('app', '')
    if app_filter:
        activities_qs = activities_qs.filter(app_name=app_filter)
    
    # Filter by date range
    # Default to last 7 days when no explicit range is provided, to keep pages light
    days = request.GET.get('days', '') or '7'
    if days:
        try:
            days_int = int(days)
            start_date = timezone.now() - timedelta(days=days_int)
            activities_qs = activities_qs.filter(timestamp__gte=start_date)
        except ValueError:
            days = ''
    
    # Filter by specific date (e.g. from Security Dashboard "Activities per day" links)
    date_filter = request.GET.get('date', '')
    date_filter_display = ''
    if date_filter:
        try:
            from datetime import datetime as dt
            filter_date = dt.strptime(date_filter, '%Y-%m-%d').date()
            activities_qs = activities_qs.filter(timestamp__date=filter_date)
            date_filter_display = filter_date.strftime('%d %b %Y')
        except (ValueError, TypeError):
            date_filter = ''
    
    # Simple pagination (newest first) with select_related for user/session.
    # We intentionally avoid an expensive COUNT here; instead, fetch one extra
    # row to determine if there is a "next" page.
    page = max(int(request.GET.get('page', 1) or 1), 1)
    per_page = 15  # small page size keeps DOM light and scrolling smooth
    start = (page - 1) * per_page
    end = start + per_page + 1  # fetch one extra row to detect has_next
    page_slice = (
        activities_qs
        .select_related('user', 'sub_user', 'session')
        .order_by('-timestamp')[start:end]
    )
    activities = list(page_slice[:per_page])
    has_next = len(page_slice) > per_page
    has_prev = page > 1
    
    # Get unique activity types and apps for filters from a bounded scope
    filter_scope = root_qs
    if days:
        try:
            days_int = int(days)
            fs_start = timezone.now() - timedelta(days=days_int)
            filter_scope = filter_scope.filter(timestamp__gte=fs_start)
        except ValueError:
            pass
    if date_filter:
        try:
            from datetime import datetime as dt
            filter_date = dt.strptime(date_filter, '%Y-%m-%d').date()
            filter_scope = filter_scope.filter(timestamp__date=filter_date)
        except (ValueError, TypeError):
            pass
    if significant_only:
        filter_scope = filter_scope.exclude(activity_type='PAGE_VIEW')
    
    all_types = filter_scope.values_list('activity_type', flat=True).distinct().order_by('activity_type')
    all_apps = filter_scope.exclude(app_name='').values_list('app_name', flat=True).distinct().order_by('app_name')
    
    context = {
        'title': 'Activity Log',
        'activities': activities,
        'activity_type': activity_type,
        'significant_only': significant_only,
        'app_filter': app_filter,
        'days': days,
        'date_filter': date_filter,
        'date_filter_display': date_filter_display,
        'all_types': list(all_types),
        'all_apps': list(all_apps),
        'page': page,
        'per_page': per_page,
        'has_next': has_next,
        'has_prev': has_prev,
        'theme_primary_color': company_context.get('theme_primary_color', '#e91e63'),
        'theme_secondary_color': company_context.get('theme_secondary_color', '#f8f9fa'),
    }
    
    return render(request, 'accounts/activity_log.html', context)


@require_POST
@login_required
@permission_required('accounts.change_usersession', raise_exception=True)
def terminate_session_view(request, session_id):
    """
    Terminate a specific session (remote logout).
    """
    try:
        success = terminate_session(session_id, request.user)
        if success:
            messages.success(request, 'Session terminated successfully.')
        else:
            messages.error(request, 'Could not terminate session.')
    except Exception as e:
        messages.error(request, f'Error terminating session: {str(e)}')
    
    # Return JSON for AJAX requests
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': success})
    
    return redirect('accounts:security_dashboard')


@require_POST
@login_required
@permission_required('accounts.change_usersession', raise_exception=True)
def terminate_all_sessions(request):
    """
    Force-logout ALL active sessions for the entire account (company).
    Only the current request's session (this browser/device) stays active.
    All other sessions are terminated—including other users and the same
    user's sessions on other browsers or devices—so they must log in again.
    """
    count = force_logout_all_account_sessions(request, exclude_current=True)
    messages.success(
        request,
        f'All other sessions have been terminated. {count} session(s) logged out immediately. '
        'Affected users will see the login page on their next request.'
    )
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'count': count})
    # Redirect to a page the user can access: security dashboard if they have permission,
    # otherwise main dashboard (avoids 403 "Account Not Yet Activated" for users with
    # change_usersession but not view_activity_log / view_useractivity).
    if _can_view_activity_log(request.user):
        return redirect('accounts:security_dashboard')
    return redirect('core:dashboard')


@login_required
@permission_required('accounts.view_usersession', raise_exception=True)
def session_detail(request, session_id):
    """
    View details of a specific session.
    """
    from apps.core.utils import get_company_context
    
    try:
        session = UserSession.objects.get(id=session_id, user=request.user)
    except UserSession.DoesNotExist:
        messages.error(request, 'Session not found.')
        return redirect('accounts:security_dashboard')
    
    company_context = get_company_context(request.user, request)
    
    # Get activities for this session
    activities = UserActivity.objects.filter(session=session).order_by('-timestamp')
    
    context = {
        'title': 'Session Details',
        'session': session,
        'activities': activities,
        'theme_primary_color': company_context.get('theme_primary_color', '#e91e63'),
        'theme_secondary_color': company_context.get('theme_secondary_color', '#f8f9fa'),
    }
    
    return render(request, 'accounts/session_detail.html', context)


@login_required
def activity_detail(request, activity_id):
    """
    View detailed information about a specific activity.
    Access only if the activity belongs to the current account (tenant-safe).
    Requires view_activity_log or view_useractivity.
    """
    if not _can_view_activity_log(request.user):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied('You do not have permission to view activity details.')
    from apps.core.utils import get_company_context
    
    account = getattr(request.user, 'account_id', None) and request.user.account
    try:
        # Tenant-safe: activity must belong to current account (or current user if no account)
        if account:
            activity = UserActivity.objects.get(id=activity_id, account=account)
        else:
            activity = UserActivity.objects.get(id=activity_id, user=request.user)
    except UserActivity.DoesNotExist:
        messages.error(request, 'Activity not found.')
        return redirect('accounts:activity_log')
    
    company_context = get_company_context(request.user, request)
    
    # Parse changes for display
    changes_display = []
    if activity.changes:
        for field, values in activity.changes.items():
            changes_display.append({
                'field': field.replace('_', ' ').title(),
                'old_value': values.get('old', 'N/A'),
                'new_value': values.get('new', 'N/A'),
            })
    
    # Parse deleted data for display
    deleted_data_display = []
    if activity.deleted_data:
        for field, value in activity.deleted_data.items():
            if value is not None and value != '':
                deleted_data_display.append({
                    'field': field.replace('_', ' ').title(),
                    'value': value,
                })
    
    # Get object URL if available
    object_link = activity.get_object_link()
    
    # Check if the object still exists (for non-delete activities)
    object_exists = False
    if activity.activity_type != 'DELETE' and object_link:
        object_exists = True  # We'll let the template handle 404s
    
    context = {
        'title': 'Activity Details',
        'activity': activity,
        'changes_display': changes_display,
        'deleted_data_display': deleted_data_display,
        'object_link': object_link,
        'object_exists': object_exists,
        'theme_primary_color': company_context.get('theme_primary_color', '#e91e63'),
        'theme_secondary_color': company_context.get('theme_secondary_color', '#f8f9fa'),
    }
    
    return render(request, 'accounts/activity_detail.html', context)


# =============================================================================
# ADMIN SECURITY VIEWS - For staff/admin users to monitor all users
# =============================================================================

@login_required
@permission_required('accounts.view_useractivity', raise_exception=True)
def admin_security_overview(request):
    """
    Admin view showing all users' sessions and activities.
    Controlled by Django permissions rather than is_staff.
    """
    from apps.core.utils import get_company_context
    from django.db.models import Count, Max, Q
    
    company_context = get_company_context(request.user, request)
    
    # Get all currently active sessions
    active_sessions = UserSession.objects.filter(
        is_active=True
    ).select_related('user').order_by('-last_activity')
    
    # Get active users count
    active_users = active_sessions.values('user').distinct().count()
    
    # Get sessions by device type
    sessions_by_device = active_sessions.values('device_type').annotate(
        count=Count('id')
    ).order_by('-count')
    
    # Get sessions by country
    sessions_by_country = active_sessions.exclude(country='').values('country').annotate(
        count=Count('id')
    ).order_by('-count')[:10]
    
    # Get activity by app (last 24 hours)
    one_day_ago = timezone.now() - timedelta(hours=24)
    activity_by_app = UserActivity.objects.filter(
        timestamp__gte=one_day_ago
    ).exclude(app_name='').values('app_name').annotate(
        count=Count('id'),
        unique_users=Count('user', distinct=True)
    ).order_by('-count')
    
    # Get recent activities across all users
    recent_activities = UserActivity.objects.select_related(
        'user', 'session'
    ).order_by('-timestamp')[:100]
    
    # Get suspicious sessions
    suspicious_sessions = UserSession.objects.filter(
        is_suspicious=True
    ).select_related('user').order_by('-login_time')[:20]
    
    # Get failed login attempts
    failed_logins = UserActivity.objects.filter(
        activity_type='LOGIN_FAILED',
        timestamp__gte=one_day_ago
    ).order_by('-timestamp')[:50]
    
    # Get users currently on each app
    users_per_app = get_users_per_app()
    
    context = {
        'title': 'Security Overview (Admin)',
        'active_sessions': active_sessions,
        'active_users': active_users,
        'sessions_by_device': sessions_by_device,
        'sessions_by_country': sessions_by_country,
        'activity_by_app': activity_by_app,
        'recent_activities': recent_activities,
        'suspicious_sessions': suspicious_sessions,
        'failed_logins': failed_logins,
        'users_per_app': users_per_app,
        'theme_primary_color': company_context.get('theme_primary_color', '#e91e63'),
        'theme_secondary_color': company_context.get('theme_secondary_color', '#f8f9fa'),
    }
    
    return render(request, 'accounts/admin_security_overview.html', context)


def get_users_per_app():
    """
    Get currently active users for each app based on recent activity.
    Returns dict of app_name -> list of user info
    """
    # Consider a user "active" on an app if they accessed it in the last 5 minutes
    five_minutes_ago = timezone.now() - timedelta(minutes=5)
    
    recent_app_activity = UserActivity.objects.filter(
        timestamp__gte=five_minutes_ago,
        user__isnull=False
    ).exclude(app_name='').select_related('user', 'session').order_by('-timestamp')
    
    users_per_app = {}
    seen = set()  # Track user-app combinations
    
    for activity in recent_app_activity:
        key = (activity.user_id, activity.app_name)
        if key not in seen:
            seen.add(key)
            app = activity.app_name
            if app not in users_per_app:
                users_per_app[app] = []
            
            users_per_app[app].append({
                'user': activity.user,
                'email': activity.user.email,
                'name': activity.user.get_full_name(),
                'last_activity': activity.timestamp,
                'action': activity.description,
                'device': activity.session.device_info if activity.session else 'Unknown',
                'ip_address': activity.ip_address,
            })
    
    return users_per_app


@login_required
@permission_required('accounts.view_useractivity', raise_exception=True)
def admin_user_activities(request, user_id):
    """
    Admin view to see a specific user's activities.
    Controlled by Django permissions rather than is_staff.
    """
    from apps.core.utils import get_company_context
    
    try:
        target_user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        messages.error(request, 'User not found.')
        return redirect('accounts:admin_security_overview')
    
    company_context = get_company_context(request.user, request)
    
    # Get user's sessions
    sessions = UserSession.objects.filter(user=target_user).order_by('-login_time')[:50]
    
    # Get user's activities
    activities = UserActivity.objects.filter(user=target_user).order_by('-timestamp')
    
    # Filter by date if provided
    days = request.GET.get('days', '7')
    try:
        days_int = int(days)
        start_date = timezone.now() - timedelta(days=days_int)
        activities = activities.filter(timestamp__gte=start_date)
    except ValueError:
        pass
    
    # Pagination
    page = int(request.GET.get('page', 1))
    per_page = 50
    total = activities.count()
    activities = activities[(page-1)*per_page:page*per_page]
    
    context = {
        'title': f'User Activities - {target_user.get_full_name()}',
        'target_user': target_user,
        'sessions': sessions,
        'activities': activities,
        'days': days,
        'page': page,
        'per_page': per_page,
        'total': total,
        'total_pages': (total + per_page - 1) // per_page,
        'theme_primary_color': company_context.get('theme_primary_color', '#e91e63'),
        'theme_secondary_color': company_context.get('theme_secondary_color', '#f8f9fa'),
    }
    
    return render(request, 'accounts/admin_user_activities.html', context)


@login_required
@permission_required('accounts.view_useractivity', raise_exception=True)
def live_users(request):
    """
    API endpoint to get currently active users.
    Returns JSON data for real-time updates.
    Controlled by Django permissions rather than is_staff.
    """
    users_per_app = get_users_per_app()
    
    # Format for JSON response
    result = {}
    for app, users in users_per_app.items():
        result[app] = [
            {
                'email': u['email'],
                'name': u['name'],
                'last_activity': u['last_activity'].isoformat(),
                'action': u['action'],
                'device': u['device'],
                'ip': u['ip_address'],
            }
            for u in users
        ]
    
    return JsonResponse({
        'users_per_app': result,
        'timestamp': timezone.now().isoformat(),
    })
