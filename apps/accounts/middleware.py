"""
Security Middleware for Activity Tracking.

This middleware tracks user activities, page views, and updates session last activity.
Provides comprehensive tracking across ALL apps in the system.

Enhanced Features:
- Stores current request/user in thread-local storage for model-level tracking
- Captures detailed information about objects being accessed
- Generates direct URLs to accessed objects
"""

import re
import logging
from django.utils import timezone
from django.conf import settings

logger = logging.getLogger(__name__)


# Import thread-local helpers for request/user storage
def _get_thread_local_helpers():
    """Lazy import to avoid circular imports."""
    from .activity_tracking import set_current_request, set_current_user
    return set_current_request, set_current_user


class ActivityTrackingMiddleware:
    """
    Middleware to track user activities for security and audit purposes.
    
    Features:
    - Updates session last_activity timestamp
    - Logs page views for authenticated users
    - Tracks CRUD operations based on HTTP method and URL patterns
    - Tracks activity across ALL apps in the system
    """
    
    # URL patterns to exclude from tracking
    EXCLUDED_PATTERNS = [
        r'^/static/',
        r'^/media/',
        r'^/favicon\.ico',
        r'^/__debug__/',
        r'^/api/health',
        r'\.js$',
        r'\.css$',
        r'\.png$',
        r'\.jpg$',
        r'\.jpeg$',
        r'\.gif$',
        r'\.ico$',
        r'\.woff',
        r'\.woff2$',
        r'\.ttf$',
        r'\.svg$',
        r'\.map$',
        r'\.eot$',
    ]
    
    # Complete mapping of all URL patterns to app names and display names
    # Format: url_pattern: (app_name, display_name, model_name)
    APP_URL_MAPPING = {
        # Core/Dashboard
        'dashboard': ('core', 'Dashboard', 'Dashboard'),
        'landing': ('core', 'Landing Page', 'Page'),
        
        # Accounting
        'accounting': ('accounting', 'Accounting', 'Account'),
        'chart-of-accounts': ('accounting', 'Chart of Accounts', 'Account'),
        'journal': ('accounting', 'Journal', 'JournalEntry'),
        'ledger': ('accounting', 'Ledger', 'LedgerEntry'),
        'trial-balance': ('accounting', 'Trial Balance', 'Report'),
        'balance-sheet': ('accounting', 'Balance Sheet', 'Report'),
        'income-statement': ('accounting', 'Income Statement', 'Report'),
        'profit-loss': ('accounting', 'Profit & Loss', 'Report'),
        
        # Accounts/Users
        'auth': ('accounts', 'Authentication', 'User'),
        'profile': ('accounts', 'Profile', 'User'),
        'security': ('accounts', 'Security', 'Session'),
        'login': ('accounts', 'Login', 'User'),
        'logout': ('accounts', 'Logout', 'User'),
        'register': ('accounts', 'Registration', 'User'),
        'password': ('accounts', 'Password', 'User'),
        
        # Clients
        'clients': ('clients', 'Clients', 'Client'),
        'customer': ('clients', 'Customers', 'Client'),
        'customers': ('clients', 'Customers', 'Client'),
        
        # Expenses
        'expenses': ('expenses', 'Expenses', 'Expense'),
        'expense': ('expenses', 'Expenses', 'Expense'),
        'expense-categories': ('expenses', 'Expense Categories', 'Category'),
        'expense-reports': ('expenses', 'Expense Reports', 'Report'),
        
        # Inventory
        'inventory': ('inventory', 'Inventory', 'Inventory'),
        'stock': ('inventory', 'Stock', 'Stock'),
        'products': ('inventory', 'Products', 'Product'),
        'items': ('inventory', 'Items', 'Item'),
        
        # Invoices
        'invoices': ('invoices', 'Invoices', 'Invoice'),
        'invoice': ('invoices', 'Invoices', 'Invoice'),
        
        # Job Orders
        'job-orders': ('job_orders', 'Job Orders', 'JobOrder'),
        'job_orders': ('job_orders', 'Job Orders', 'JobOrder'),
        'joborders': ('job_orders', 'Job Orders', 'JobOrder'),
        'jobs': ('job_orders', 'Jobs', 'JobOrder'),
        
        # Quotations
        'quotations': ('quotations', 'Quotations', 'Quotation'),
        'quotation': ('quotations', 'Quotations', 'Quotation'),
        'quotes': ('quotations', 'Quotes', 'Quotation'),
        
        # Receipts
        'receipts': ('receipts', 'Receipts', 'Receipt'),
        'receipt': ('receipts', 'Receipts', 'Receipt'),
        'payments': ('receipts', 'Payments', 'Payment'),
        
        # Waybills
        'waybills': ('waybills', 'Waybills', 'Waybill'),
        'waybill': ('waybills', 'Waybills', 'Waybill'),
        'delivery': ('waybills', 'Delivery', 'Waybill'),
        'deliveries': ('waybills', 'Deliveries', 'Waybill'),
        
        # Admin
        'admin': ('admin', 'Admin Panel', 'Admin'),
        
        # API
        'api': ('api', 'API', 'Endpoint'),
    }
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.compiled_patterns = [re.compile(p) for p in self.EXCLUDED_PATTERNS]
    
    def __call__(self, request):
        # Store request/user in thread-local storage for model-level tracking
        try:
            set_current_request, set_current_user = _get_thread_local_helpers()
            set_current_request(request)
            if hasattr(request, 'user') and request.user.is_authenticated:
                set_current_user(request.user)
        except Exception:
            pass
        
        # Process request
        self._process_request(request)
        
        # Get response
        response = self.get_response(request)
        
        # Process response
        self._process_response(request, response)
        
        # Clear thread-local storage
        try:
            set_current_request, set_current_user = _get_thread_local_helpers()
            set_current_request(None)
            set_current_user(None)
        except Exception:
            pass
        
        return response
    
    def _should_track(self, path):
        """Check if this request should be tracked."""
        for pattern in self.compiled_patterns:
            if pattern.search(path):
                return False
        return True
    
    def _process_request(self, request):
        """Process the incoming request."""
        # Store request start time for duration tracking
        request._activity_start_time = timezone.now()
    
    def _process_response(self, request, response):
        """Process the response and log activity."""
        # Only track for authenticated users
        if not hasattr(request, 'user') or not request.user.is_authenticated:
            return
        
        # Check if we should track this request
        if not self._should_track(request.path):
            return
        
        # Skip if disabled in settings
        if getattr(settings, 'DISABLE_ACTIVITY_TRACKING', False):
            return
        
        try:
            # Update session last_activity
            self._update_session_activity(request)
            
            # Log significant activities (successful responses)
            if response.status_code < 400:
                self._log_activity(request, response)
        except Exception as e:
            # Don't let tracking errors break the application
            logger.error(f"Activity tracking error: {e}")
    
    def _update_session_activity(self, request):
        """Update the last_activity timestamp for the user's session."""
        from .models import UserSession
        
        session_id = request.session.get('security_session_id')
        if session_id:
            try:
                UserSession.objects.filter(id=session_id).update(
                    last_activity=timezone.now()
                )
            except Exception:
                pass
    
    # URL patterns for detail views - maps app_label to URL pattern
    # Format: 'app_label': ('url_namespace', 'view_name', 'pk_param')
    # These MUST match the actual URL patterns in each app's urls.py
    DETAIL_URL_PATTERNS = {
        # Invoices: path('<int:pk>/', views.invoice_detail, name='detail')
        'invoices': ('invoices', 'detail', 'pk'),
        # Receipts: path('<int:receipt_id>/', views.receipt_detail_view, name='detail')
        'receipts': ('receipts', 'detail', 'receipt_id'),
        # Quotations: path('<int:pk>/', views.quotation_detail, name='quotation_detail')
        'quotations': ('quotations', 'quotation_detail', 'pk'),
        # Expenses: path('<uuid:pk>/', views.ExpenseDetailView.as_view(), name='detail') - uses UUID
        'expenses': ('expenses', 'detail', 'pk'),
        # Clients: path('<int:pk>/', views.client_detail, name='client_detail')
        'clients': ('clients', 'client_detail', 'pk'),
        # Inventory: path('detail/<int:pk>/', views.inventory_detail, name='detail')
        'inventory': ('inventory', 'detail', 'pk'),
        # Expense: path('detail/<int:pk>/', views.expense_detail, name='detail')
        'expense': ('expense', 'detail', 'pk'),
        # Waybills: path('<int:pk>/', views.waybill_detail, name='detail')
        'waybills': ('waybills', 'detail', 'pk'),
        # Job Orders: path('<int:pk>/', views.product_detail, name='product_detail')
        'job_orders': ('job_orders', 'product_detail', 'pk'),
    }
    
    # Apps that should NOT have detail URLs generated
    # These are system apps or apps without object detail views
    EXCLUDED_APPS_FOR_DETAIL_URL = [
        'accounts', 'auth', 'core', 'admin', 'api', 'security',
        'dashboard', 'login', 'logout', 'register', 'password',
    ]
    
    def _get_object_detail_url(self, app_name, object_id):
        """
        Generate the detail URL for an object based on app name and object ID.
        Returns the URL to view the specific object.
        """
        from django.urls import reverse, NoReverseMatch
        import uuid as uuid_module
        
        if not app_name or not object_id:
            return ''
        
        app_label = app_name.lower()
        
        # Skip URL generation for excluded apps
        if app_label in self.EXCLUDED_APPS_FOR_DETAIL_URL:
            return ''
        
        # Determine if object_id is a UUID or integer
        is_uuid = self._is_uuid(str(object_id))
        
        # Check if we have a known URL pattern
        if app_label in self.DETAIL_URL_PATTERNS:
            namespace, view_name, pk_param = self.DETAIL_URL_PATTERNS[app_label]
            try:
                # Use appropriate type for the ID
                if is_uuid:
                    # For UUID, keep as string or convert to UUID object
                    try:
                        pk_value = uuid_module.UUID(str(object_id))
                    except ValueError:
                        pk_value = object_id
                else:
                    # Try integer first
                    try:
                        pk_value = int(object_id)
                    except (ValueError, TypeError):
                        pk_value = object_id
                
                return reverse(f'{namespace}:{view_name}', kwargs={pk_param: pk_value})
            except (NoReverseMatch, ValueError) as e:
                logger.debug(f"NoReverseMatch for {namespace}:{view_name} with {pk_param}={pk_value}: {e}")
        
        # Try common URL patterns
        if not is_uuid:
            try:
                object_id_int = int(object_id)
                common_patterns = [
                    (f'{app_label}:detail', {'pk': object_id_int}),
                    (f'{app_label}:detail', {'id': object_id_int}),
                    (f'{app_label}:{app_label}_detail', {'pk': object_id_int}),
                    (f'{app_label}:view', {'pk': object_id_int}),
                ]
                
                for pattern, kwargs in common_patterns:
                    try:
                        return reverse(pattern, kwargs=kwargs)
                    except (NoReverseMatch, ValueError):
                        continue
                
                # Fallback: construct URL manually for known apps only
                if app_label in self.DETAIL_URL_PATTERNS:
                    return f'/{app_label}/{object_id_int}/'
            except (ValueError, TypeError):
                pass
        else:
            # For UUIDs, try to construct URL for apps that use UUIDs (like expenses)
            try:
                pk_value = uuid_module.UUID(str(object_id))
                common_uuid_patterns = [
                    (f'{app_label}:detail', {'pk': pk_value}),
                ]
                
                for pattern, kwargs in common_uuid_patterns:
                    try:
                        return reverse(pattern, kwargs=kwargs)
                    except (NoReverseMatch, ValueError):
                        continue
            except ValueError:
                pass
        
        return ''
    
    def _log_activity(self, request, response):
        """Log the user activity."""
        from .models import UserActivity, UserSession
        from .security_utils import get_client_ip
        
        # Determine activity type based on HTTP method and URL
        activity_type = self._determine_activity_type(request, response)
        
        # Get app info from URL
        app_name, display_name, model_name, object_id = self._parse_url(request.path)
        
        # Skip logging simple page views for non-app pages
        if activity_type == 'PAGE_VIEW' and not app_name:
            return
        
        # For CREATE/UPDATE operations with redirect response, try to extract the object URL from redirect
        # This captures the object's detail URL after the operation
        object_url = ''
        if activity_type in ['CREATE', 'UPDATE'] and response.status_code in [301, 302, 303]:
            redirect_url = response.get('Location', '')
            if redirect_url:
                # The redirect URL is typically the detail page of the object
                # Use this as the object_url for reliable navigation
                object_url = redirect_url
                
                # Also try to extract the object_id from the redirect URL
                redirect_app, redirect_display, redirect_model, redirect_id = self._parse_url(redirect_url)
                if redirect_id:
                    # For CREATE, we didn't have the ID before - update it now
                    if not object_id:
                        object_id = redirect_id
                    # Update description with actual object ID
                    if activity_type == 'CREATE':
                        description = f"Created {model_name} #{object_id} in {display_name}"
                    else:
                        description = f"Updated {model_name} #{object_id} in {display_name}"
                else:
                    description = self._create_description(request, activity_type, display_name, model_name, object_id)
            else:
                description = self._create_description(request, activity_type, display_name, model_name, object_id)
                # Fallback to generating URL if we have object_id
                if object_id:
                    object_url = self._get_object_detail_url(app_name, object_id)
        else:
            # Create description
            description = self._create_description(request, activity_type, display_name, model_name, object_id)
            
            # Generate proper object detail URL for non-CREATE/UPDATE operations
            if object_id and activity_type != 'DELETE':
                object_url = self._get_object_detail_url(app_name, object_id)
        
        # Get session if available (verify it belongs to current user)
        session = None
        session_id = request.session.get('security_session_id')
        if session_id:
            try:
                session = UserSession.objects.get(id=session_id, user=request.user)
            except UserSession.DoesNotExist:
                pass
        
        # Get SubUser if team member is logged in (request.user is linked_user when SubUser logged in)
        sub_user = None
        sub_user_id = request.session.get('sub_user_id')
        if sub_user_id:
            from .models import SubUser
            try:
                sub_user = SubUser.objects.get(id=sub_user_id, linked_user=request.user)
            except (SubUser.DoesNotExist, ValueError):
                pass
        
        # Tenant: use request.company.account so logs are always for the current account
        from .security_utils import get_account_for_activity
        account = get_account_for_activity(request=request, user=request.user)

        # Log the activity
        UserActivity.log_activity(
            user=request.user,
            session=session,
            sub_user=sub_user,
            account=account,
            activity_type=activity_type,
            description=description,
            app_name=app_name,
            model_name=model_name,
            object_id=object_id,
            url_path=request.path,
            http_method=request.method,
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            object_url=object_url,
        )
    
    def _determine_activity_type(self, request, response):
        """Determine the type of activity based on request."""
        method = request.method
        path = request.path.lower()
        content_type = response.get('Content-Type', '')
        
        # Check for file downloads (PDF, Excel, etc.)
        if content_type:
            if 'application/pdf' in content_type:
                return 'FILE_DOWNLOAD'
            if 'application/vnd' in content_type or 'spreadsheet' in content_type:
                return 'EXPORT'
            if 'application/octet-stream' in content_type:
                return 'FILE_DOWNLOAD'
        
        # API operations
        if '/api/' in path:
            if method == 'POST':
                return 'CREATE'
            elif method in ['PUT', 'PATCH']:
                return 'UPDATE'
            elif method == 'DELETE':
                return 'DELETE'
            elif method == 'GET':
                return 'API_ACCESS'
        
        # Form submissions (POST requests)
        if method == 'POST':
            # Check URL patterns for action type
            if any(word in path for word in ['create', 'add', 'new', '/save']):
                return 'CREATE'
            elif any(word in path for word in ['edit', 'update', 'modify', 'change']):
                return 'UPDATE'
            elif any(word in path for word in ['delete', 'remove', 'destroy']):
                return 'DELETE'
            elif any(word in path for word in ['export', 'download']):
                return 'EXPORT'
            elif any(word in path for word in ['import', 'upload']):
                return 'FILE_UPLOAD'
            elif 'login' in path:
                return 'LOGIN'
            elif 'logout' in path:
                return 'LOGOUT'
            # Default POST as CREATE for data entry
            return 'CREATE'
        
        # Download/export in URL for GET
        if method == 'GET':
            if any(word in path for word in ['download', 'export', 'pdf', 'print']):
                return 'FILE_DOWNLOAD'
        
        # Default to page view for GET requests
        if method == 'GET':
            return 'PAGE_VIEW'
        
        return 'OTHER'
    
    def _parse_url(self, path):
        """
        Parse URL to extract app name, display name, model name, and object ID.
        Returns: (app_name, display_name, model_name, object_id)
        """
        app_name = ''
        display_name = ''
        model_name = ''
        object_id = ''
        
        # Clean the path
        path_lower = path.lower()
        path_parts = [p for p in path.strip('/').split('/') if p]
        
        if not path_parts:
            return app_name, display_name, model_name, object_id
        
        # Check each part against our mapping
        for part in path_parts:
            part_lower = part.lower()
            if part_lower in self.APP_URL_MAPPING:
                app_name, display_name, model_name = self.APP_URL_MAPPING[part_lower]
                
                # Find the index and look for object ID
                try:
                    idx = path_parts.index(part)
                    # Look for numeric or UUID ID after the app name
                    for i in range(idx + 1, len(path_parts)):
                        potential_id = path_parts[i]
                        if potential_id.isdigit():
                            object_id = potential_id
                            break
                        elif self._is_uuid(potential_id):
                            object_id = potential_id
                            break
                        # Stop if we hit another known keyword
                        if potential_id.lower() in ['create', 'add', 'edit', 'update', 'delete', 'list', 'detail']:
                            break
                except (ValueError, IndexError):
                    pass
                break
        
        return app_name, display_name, model_name, object_id
    
    def _is_uuid(self, value):
        """Check if a value looks like a UUID."""
        uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        return bool(re.match(uuid_pattern, value.lower()))
    
    def _create_description(self, request, activity_type, display_name, model_name, object_id):
        """Create a human-readable description of the activity."""
        # Get the actual page/action from URL
        path_parts = request.path.strip('/').split('/')
        action_words = ['create', 'add', 'new', 'edit', 'update', 'delete', 'list', 'detail', 'view']
        
        action = ''
        for part in path_parts:
            if part.lower() in action_words:
                action = part.lower()
                break
        
        # Build description based on activity type
        if activity_type == 'PAGE_VIEW':
            if object_id:
                return f"Viewed {model_name} #{object_id} in {display_name}"
            elif action == 'list' or not action:
                return f"Viewed {display_name} list"
            else:
                return f"Viewed {display_name}"
        elif activity_type == 'CREATE':
            return f"Created new {model_name} in {display_name}"
        elif activity_type == 'UPDATE':
            if object_id:
                return f"Updated {model_name} #{object_id} in {display_name}"
            return f"Updated {model_name} in {display_name}"
        elif activity_type == 'DELETE':
            if object_id:
                return f"Deleted {model_name} #{object_id} from {display_name}"
            return f"Deleted {model_name} from {display_name}"
        elif activity_type == 'EXPORT':
            return f"Exported data from {display_name}"
        elif activity_type == 'FILE_DOWNLOAD':
            if object_id:
                return f"Downloaded {model_name} #{object_id} from {display_name}"
            return f"Downloaded file from {display_name}"
        elif activity_type == 'FILE_UPLOAD':
            return f"Uploaded file to {display_name}"
        elif activity_type == 'API_ACCESS':
            return f"API access to {display_name}"
        elif activity_type == 'LOGIN':
            return "User login"
        elif activity_type == 'LOGOUT':
            return "User logout"
        
        return f"Accessed {display_name or request.path}"


class SessionInvalidationMiddleware:
    """
    If the current session was invalidated (e.g. by "Log out all users"),
    the session row may have been deleted from the DB while the request
    still has an in-memory authenticated user. Detect that and redirect
    to login so no cached/stale session allows continued access.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.contrib.sessions.models import Session
        from django.conf import settings

        if request.user.is_authenticated and getattr(request.session, 'session_key', None):
            if not Session.objects.filter(session_key=request.session.session_key).exists():
                request.session.flush()
                from django.shortcuts import redirect
                from urllib.parse import quote
                login_url = getattr(settings, 'LOGIN_URL', '/auth/login/')
                next_url = request.path
                if request.GET:
                    next_url += '?' + request.GET.urlencode()
                return redirect(f'{login_url}?reason=admin_logout&next={quote(next_url, safe="/")}')
        return self.get_response(request)
