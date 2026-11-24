"""
Performance Middleware for EcoKleenFarms
========================================

This middleware adds performance optimizations:
1. Cache-Control headers for better browser caching
2. ETag support for conditional requests
3. Preload headers for critical resources
4. Compression headers
"""

import hashlib
from django.utils.cache import patch_cache_control
from django.conf import settings
from django.shortcuts import redirect
from django.http import HttpResponseRedirect

from apps.core.utils import apply_no_cache_headers


class CanonicalHostMiddleware:
    """
    In DEBUG, redirect localhost to 127.0.0.1 so the session cookie works
    in both Cursor's browser and normal browsers (Chrome/Firefox).
    localhost and 127.0.0.1 are different origins, so cookies set on one
    are not sent to the other. Redirecting to one canonical host fixes login.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.DEBUG and request.get_host().startswith('localhost'):
            port = request.get_port()
            canonical_url = request.scheme + '://127.0.0.1'
            if port and port not in ('80', '443'):
                canonical_url += ':' + port
            canonical_url += request.get_full_path()
            return HttpResponseRedirect(canonical_url)
        return self.get_response(request)


class PerformanceMiddleware:
    """
    Middleware that adds performance-related HTTP headers.
    
    This helps the app load super fast even on slow connections by:
    - Setting proper cache headers so browsers cache static content
    - Adding preload hints for critical resources
    - Enabling conditional requests with ETags
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        
    def __call__(self, request):
        response = self.get_response(request)
        
        # Skip for admin, API endpoints, and messaging (real-time, must not cache)
        if (request.path.startswith('/admin/') or request.path.startswith('/api/') or
                request.path.startswith('/messaging/api/')):
            return response
        
        # Add cache control for static files
        if request.path.startswith('/static/') or request.path.startswith('/media/'):
            # Cache static files for 1 year (they have hash busting)
            patch_cache_control(
                response,
                max_age=31536000,  # 1 year
                public=True,
                immutable=True
            )
            return response
        
        # For authenticated HTML pages, use must-revalidate
        if hasattr(response, 'content') and 'text/html' in response.get('Content-Type', ''):
            path = request.path.rstrip('/') or '/'
            # Paths that must NEVER be cached: DynamicListNoCacheMiddleware sets no-store; do not overwrite
            no_cache_paths = ('/requisitions', '/staff-offences', '/inventory', '/expense', '/hr-staff', '/waybills', '/invoices', '/receipts', '/quotations')
            if any(path == p or path.startswith(p + '/') for p in no_cache_paths):
                return response
            # Paths that must always show fresh data (no ETag/304, no conditional cache)
            skip_etag = path.startswith('/job-orders')

            # Short cache with revalidation for dynamic pages
            patch_cache_control(
                response,
                max_age=0,
                must_revalidate=True,
                private=True
            )

            # Add ETag only for pages that may use 304 (skip for list/dynamic pages)
            if response.status_code == 200 and not skip_etag:
                content_hash = hashlib.md5(response.content).hexdigest()
                response['ETag'] = f'"{content_hash}"'

                # Check if client has cached version
                client_etag = request.META.get('HTTP_IF_NONE_MATCH', '')
                if client_etag == f'"{content_hash}"':
                    response.status_code = 304
                    response.content = b''

        return response


class JobOrderNoCacheMiddleware:
    """
    Ensures all /job-orders/* responses are never cached by browsers or proxies.
    Sets strong no-cache headers so job order list, detail, edit, and print pages
    always load fresh data and stay in sync after create/update/delete.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith('/job-orders'):
            response['Cache-Control'] = (
                'no-store, no-cache, must-revalidate, max-age=0, '
                'private, no-transform'
            )
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
            response['Vary'] = '*'  # Prevent proxies from serving cached copy
        return response


class RequisitionNoCacheMiddleware:
    """
    Ensures all /requisitions/* responses are never cached by browsers or proxies.
    List, detail, create, edit, delete, and print stay in sync so after any
    create/update/delete the list shows current data without multiple refreshes.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith('/requisitions'):
            response['Cache-Control'] = (
                'no-store, no-cache, must-revalidate, max-age=0, '
                'private, no-transform'
            )
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
            response['Vary'] = '*'
        return response


class DynamicListNoCacheMiddleware:
    """
    Same no-cache behavior as inventory/requisitions: list, dashboard, detail, create,
    update, delete, and print pages for these apps are never cached so a normal
    refresh always shows current data (no hard refresh needed).
    """
    NO_CACHE_PREFIXES = (
        '/inventory',
        '/expense',
        '/hr-staff',
        '/waybills',
        '/invoices',
        '/receipts',
        '/quotations',
        '/staff-offences',
        '/notifications',  # Real-time notification API - never cache, updates without page refresh
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        path = request.path
        if any(path == p or path.startswith(p + '/') for p in self.NO_CACHE_PREFIXES):
            apply_no_cache_headers(response)
        return response


class PreloadHeaderMiddleware:
    """
    Reserved for optional Link preload headers. Disabled to avoid browser
    "preloaded but not used" warnings: the page already loads CSS/JS via
    <link>/<script> with defer/async, so Link preload duplicates requests
    and is often not "used" within the load event window.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        
    def __call__(self, request):
        return self.get_response(request)


class SecurityHeadersMiddleware:
    """
    Adds security headers that also improve performance.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        
    def __call__(self, request):
        response = self.get_response(request)
        
        # Prevent MIME type sniffing (reduces parsing overhead)
        response['X-Content-Type-Options'] = 'nosniff'
        
        # Enable DNS prefetching
        response['X-DNS-Prefetch-Control'] = 'on'
        
        # Referrer policy (reduces header size)
        if 'Referrer-Policy' not in response:
            response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        
        return response


# -----------------------------------------------------------------------------
# Company context middleware: single source of truth for request.company
# -----------------------------------------------------------------------------

class CompanyContextMiddleware:
    """
    Attach request.company for every authenticated request.
    Uses get_company_profile_for_user(user, request) so team members (SubUser)
    resolve to the same company as the account owner.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            from apps.core.utils import get_company_profile_for_user
            request.company = get_company_profile_for_user(request.user, request)
        else:
            request.company = None
        return self.get_response(request)


# -----------------------------------------------------------------------------
# Account approval gate: unapproved accounts get profile-only access.
# Runs after CompanyContextMiddleware so request.company / user.account are available.
# -----------------------------------------------------------------------------

# Path prefixes allowed when account does NOT have full access (profile-only: owner and team members).
# Uses startswith; paths not matching any are blocked with 403.
# /dashboard/ allows all dashboard pages and APIs (company profile, bank accounts, stats, summaries).
_APPROVAL_ALLOWED_PATH_PREFIXES = (
    '/admin/',
    '/auth/',
    '/dashboard/',   # All dashboard routes: pages + api/dashboard/*, api/summaries/*
    '/static/',
    '/media/',
    '/favicon',
    '/sw.js',
    '/manifest.webmanifest',
    '/manifest.json',
)

# Exact paths (after stripping trailing slash) allowed when account is profile-only.
_APPROVAL_ALLOWED_EXACT = ('', '/', '/dashboard', '/dashboard/')


class AccountApprovalMiddleware:
    """
    Enforce account-level access: when the account does not have "full access", team
    members get profile-only access (no invoices, job orders, etc.). The account owner
    (company admin) always has full access — no approval gate.

    Full access for non-owners is True when: account.is_approved and the account owner
    has at least one elevated permission (e.g. Company Admin). When the company is
    downgraded to Company Profile Viewer, team members are restricted; the owner is not.

    - Superusers: bypass (full access).
    - Users without account: pass (edge case).
    - Account owner (request.user.id == account.owner_id): full access always.
    - User on account with owner_id unset: full access (legacy/fallback).
    - User with core.change_companyprofile (e.g. Company Admin role): full access always.
    - account_has_full_access(account): pass (normal permission flow).
    - Otherwise: allow only auth, admin, dashboard, company profile; block all business apps.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            return self.get_response(request)
        # Superuser and staff are never restricted (Django admin / support).
        if getattr(request.user, 'is_superuser', False):
            return self.get_response(request)
        if getattr(request.user, 'is_staff', False):
            return self.get_response(request)
        from apps.core.models import Account
        from apps.core.utils import account_has_full_access
        # Get account for this user.
        # Priority: fresh DB lookup > cached account > account_id fallback.
        account = getattr(request.user, 'account', None)
        account_id = getattr(request.user, 'account_id', None)
        if not account and account_id:
            account = Account.objects.filter(pk=account_id).first()
        # If no account, allow through (edge case; auth/user management will handle).
        if not account:
            return self.get_response(request)
        # Company has full access (approved + owner has elevated permissions).
        # This applies to ALL users including account owners — approval is required for everyone.
        if account_has_full_access(account):
            return self.get_response(request)
        # Account does NOT have full access. Only allow specific paths.
        path = request.path.rstrip('/') or '/'
        for prefix in _APPROVAL_ALLOWED_PATH_PREFIXES:
            if request.path.startswith(prefix):
                return self.get_response(request)
        if path in _APPROVAL_ALLOWED_EXACT:
            return self.get_response(request)
        # Block all other business app access with 403.
        from django.http import HttpResponseForbidden
        from django.template import loader
        from business_app.views import _is_company_team_member
        try:
            template = loader.get_template('403.html')
            context = {
                'exception': '',
                'is_company_team_member': _is_company_team_member(request),
            }
            return HttpResponseForbidden(template.render(context, request))
        except Exception:
            return HttpResponseForbidden(
                'Your company has profile-only access. You and your team cannot use business apps '
                '(invoices, job orders, etc.) until the company is given full access again by a super admin.'
            )


# -----------------------------------------------------------------------------
# Phase 7: Permission verification logging (runtime safety checks).
# Set PERMISSION_VERIFICATION_LOGGING = False in settings after validation to
# stop "Access granted" DEBUG logs; 403 WARNING logs remain for audit.
# -----------------------------------------------------------------------------

import logging

PERMISSION_VERIFICATION_LOGGER = 'security.permissions'

# Path prefixes for views that are behind permission_required (sensitive).
# When PERMISSION_VERIFICATION_LOGGING is True, we log DEBUG "Access granted" for these.
# URLs: auth/* from accounts app, dashboard/* from core, plus app roots.
_SENSITIVE_PATH_PREFIXES = (
    '/auth/security',
    '/auth/profile',
    '/dashboard/company-profile',
    '/dashboard/bank-accounts',
    '/invoices/',
    '/quotations/',
    '/waybills/',
    '/receipts/',
    '/clients/',
    '/inventory/',
    '/expense/',
    '/job-orders/',
    '/accounting/',
)


class PermissionVerificationMiddleware:
    """
    Logs permission-related access for verification and audit:
    - WARNING when access is denied (403): user, path, view name.
    - DEBUG when access is granted to sensitive paths (only if
      PERMISSION_VERIFICATION_LOGGING is True; disable after validation).
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self._log = logging.getLogger(PERMISSION_VERIFICATION_LOGGER)

    def __call__(self, request):
        response = self.get_response(request)
        self._log_response(request, response)
        return response

    def _log_response(self, request, response):
        path = request.path
        view_name = ''
        if getattr(request, 'resolver_match', None):
            view_name = getattr(request.resolver_match, 'view_name', '') or ''
        user_repr = self._user_repr(request)

        if response.status_code == 403:
            # Messaging 403 (e.g. left conversation) is expected; log at DEBUG to avoid red in terminal
            if '/messaging/api/' in path:
                self._log.debug(
                    'Permission denied | user=%s path=%s view=%s reason=403',
                    user_repr, path, view_name,
                    extra={'user': user_repr, 'path': path, 'view': view_name}
                )
            else:
                self._log.warning(
                    'Permission denied | user=%s path=%s view=%s reason=403',
                    user_repr, path, view_name,
                    extra={'user': user_repr, 'path': path, 'view': view_name}
                )
            return

        if response.status_code != 200:
            return

        if not getattr(settings, 'PERMISSION_VERIFICATION_LOGGING', False):
            return

        if not any(path.startswith(p) for p in _SENSITIVE_PATH_PREFIXES):
            return

        self._log.debug(
            'Access granted | user=%s path=%s view=%s',
            user_repr, path, view_name,
            extra={'user': user_repr, 'path': path, 'view': view_name}
        )

    @staticmethod
    def _user_repr(request):
        if not getattr(request, 'user', None):
            return 'anonymous'
        user = request.user
        if not user.is_authenticated:
            return 'anonymous'
        return getattr(user, 'email', None) or getattr(user, 'username', None) or f'id={user.pk}'


def log_permission_check(request, permission, granted, path=None, extra=None):
    """
    Optional: log a specific permission check (e.g. in a view that uses has_perm).
    Use for verification that access is granted/denied for the right reason.

    When PERMISSION_VERIFICATION_LOGGING is True, logs at DEBUG; when False,
    only logs at INFO when granted=False (denied) for audit.
    """
    log = logging.getLogger(PERMISSION_VERIFICATION_LOGGER)
    user_repr = PermissionVerificationMiddleware._user_repr(request)
    path = path or getattr(request, 'path', '')
    msg = 'Permission check | perm=%s user=%s path=%s result=%s'
    if granted:
        if getattr(settings, 'PERMISSION_VERIFICATION_LOGGING', False):
            log.debug(msg, permission, user_repr, path, 'granted', extra=extra or {})
    else:
        log.info(msg, permission, user_repr, path, 'denied', extra=extra or {})
