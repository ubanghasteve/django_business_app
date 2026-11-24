import calendar
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import models
from django.apps import apps
from django.utils import timezone as django_timezone


def get_business_local_date():
    """
    Return the current calendar date in the business timezone (Africa/Lagos).
    Use this for "Revenue Today" and other daily metrics so they reflect the
    user's local day, not server UTC (which can show yesterday's data).
    """
    tz = ZoneInfo("Africa/Lagos")
    return django_timezone.now().astimezone(tz).date()


def get_revenue_period_boundaries():
    """
    Return strict date boundaries for revenue period cards so each card shows
    only that period's data (week = current week Mon–Sun, month = current month,
    quarter = current quarter, year = current year). Uses business local date.
    Prevents month/quarter/year from showing the same total when filters lack
    upper bounds, and excludes future dates.
    Returns a dict: today, week_start, week_end, start_of_month, end_of_month,
    quarter_start, quarter_end, year_start, year_end.
    """
    today = get_business_local_date()
    # Week: Monday (0) through Sunday (6) of current week
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    # Month: first and last day of current month
    start_of_month = today.replace(day=1)
    _, last_day = calendar.monthrange(today.year, today.month)
    end_of_month = today.replace(day=last_day)
    # Quarter: Q1=Jan–Mar, Q2=Apr–Jun, Q3=Jul–Sep, Q4=Oct–Dec
    quarter = (today.month - 1) // 3 + 1
    quarter_start = date(today.year, (quarter - 1) * 3 + 1, 1)
    quarter_end_month = quarter * 3
    _, quarter_last_day = calendar.monthrange(today.year, quarter_end_month)
    quarter_end = date(today.year, quarter_end_month, quarter_last_day)
    # Year: Jan 1 – Dec 31
    year_start = date(today.year, 1, 1)
    year_end = date(today.year, 12, 31)
    return {
        'today': today,
        'week_start': week_start,
        'week_end': week_end,
        'start_of_month': start_of_month,
        'end_of_month': end_of_month,
        'quarter_start': quarter_start,
        'quarter_end': quarter_end,
        'year_start': year_start,
        'year_end': year_end,
    }


def apply_no_cache_headers(response):
    """Set no-cache headers so dynamic pages (lists, dashboards, detail) are never served from cache.
    Use on render()/redirect() responses for list, dashboard, detail, create, update, delete, print.
    Matches inventory/requisitions pattern: fixes stale data on normal refresh."""
    if response is None:
        return
    response['Cache-Control'] = (
        'no-store, no-cache, must-revalidate, max-age=0, private, no-transform'
    )
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    response['Vary'] = 'Cookie'


def get_currency_info(currency_code):
    """Get currency information including symbol"""
    currency_map = {
        'USD': {'symbol': '$', 'name': 'US Dollar'},
        'EUR': {'symbol': '€', 'name': 'Euro'},
        'GBP': {'symbol': '£', 'name': 'British Pound'},
        'JPY': {'symbol': '¥', 'name': 'Japanese Yen'},
        'CAD': {'symbol': 'C$', 'name': 'Canadian Dollar'},
        'AUD': {'symbol': 'A$', 'name': 'Australian Dollar'},
        'CHF': {'symbol': 'CHF', 'name': 'Swiss Franc'},
        'CNY': {'symbol': '¥', 'name': 'Chinese Yuan'},
        'INR': {'symbol': '₹', 'name': 'Indian Rupee'},
        'NGN': {'symbol': '₦', 'name': 'Nigerian Naira'},
        'ZAR': {'symbol': 'R', 'name': 'South African Rand'},
        'BRL': {'symbol': 'R$', 'name': 'Brazilian Real'},
        'KRW': {'symbol': '₩', 'name': 'South Korean Won'},
        'SGD': {'symbol': 'S$', 'name': 'Singapore Dollar'},
        'HKD': {'symbol': 'HK$', 'name': 'Hong Kong Dollar'},
        'MXN': {'symbol': '$', 'name': 'Mexican Peso'},
        'RUB': {'symbol': '₽', 'name': 'Russian Ruble'},
        'SEK': {'symbol': 'kr', 'name': 'Swedish Krona'},
        'NOK': {'symbol': 'kr', 'name': 'Norwegian Krone'},
        'DKK': {'symbol': 'kr', 'name': 'Danish Krone'},
    }
    
    return currency_map.get(currency_code.upper())


def get_available_currencies():
    """Get list of all available currencies"""
    currencies = []
    currency_codes = [
        'USD', 'EUR', 'GBP', 'JPY', 'CAD', 'AUD', 'CHF', 'CNY', 'INR', 'NGN',
        'ZAR', 'BRL', 'KRW', 'SGD', 'HKD', 'MXN', 'RUB', 'SEK', 'NOK', 'DKK'
    ]
    
    for code in currency_codes:
        info = get_currency_info(code)
        if info:
            currencies.append({
                'code': code,
                'symbol': info['symbol'],
                'name': info['name']
            })
    
    return currencies


def generate_auto_number(doc_type, company_profile, prefix=None):
    """
    Generate auto number for documents
    
    Args:
        doc_type (str): Type of document (invoice, quotation, receipt, etc.)
        company_profile: CompanyProfile instance
        prefix (str): Optional prefix for the number
    
    Returns:
        str: Generated auto number
    """
    current_year = datetime.now().year
    current_month = datetime.now().month
    
    # Default prefixes for different document types
    default_prefixes = {
        'invoice': 'INV',
        'quotation': 'QUO',
        'receipt': 'REC',
        'job_order': 'JO',
        'waybill': 'WB',
    }
    
    if not prefix:
        prefix = default_prefixes.get(doc_type.lower(), 'DOC')
    
    # Try to get the model for the document type
    try:
        if doc_type.lower() == 'invoice':
            model = apps.get_model('invoices', 'Invoice')
            filter_field = 'company'
        elif doc_type.lower() == 'quotation':
            model = apps.get_model('quotations', 'Quotation')
            filter_field = 'company'
        elif doc_type.lower() == 'receipt':
            model = apps.get_model('receipts', 'Receipt')
            filter_field = 'company'
        elif doc_type.lower() == 'job_order':
            model = apps.get_model('job_orders', 'JobOrder')
            filter_field = 'company'
        elif doc_type.lower() == 'waybill':
            model = apps.get_model('waybills', 'Waybill')
            filter_field = 'company'
        else:
            # Fallback for unknown document types
            model = None
    except LookupError:
        model = None
    
    # Generate the auto number
    if model:
        # Get the last document number for this company and year
        last_doc = model.objects.filter(
            **{filter_field: company_profile},
            created_at__year=current_year
        ).order_by('-id').first()
        
        if last_doc and hasattr(last_doc, 'number'):
            # Extract the sequence number from the last document
            match = re.search(r'(\d+)$', last_doc.number)
            if match:
                last_sequence = int(match.group(1))
                next_sequence = last_sequence + 1
            else:
                next_sequence = 1
        else:
            next_sequence = 1
    else:
        # Fallback: use current timestamp
        next_sequence = int(datetime.now().timestamp()) % 10000
    
    # Format: PREFIX-YYYY-MM-NNNN
    auto_number = f"{prefix}-{current_year}-{current_month:02d}-{next_sequence:04d}"
    
    return auto_number


def format_currency(amount, currency_symbol='$', decimal_places=2, pdf_safe=False):
    """
    Format amount as currency
    
    Args:
        amount (float/Decimal): Amount to format
        currency_symbol (str): Currency symbol
        decimal_places (int): Number of decimal places
        pdf_safe (bool): Whether to use PDF-safe formatting
    
    Returns:
        str: Formatted currency string
    """
    if amount is None:
        amount = 0
    
    # Handle problematic Unicode symbols for PDF generation
    if pdf_safe:
        symbol_fallbacks = {
            '₦': 'NGN',  # Nigerian Naira
            '₹': 'INR',  # Indian Rupee
            '₽': 'RUB',  # Russian Ruble
            '₩': 'KRW',  # South Korean Won
            '¥': 'JPY',  # Japanese Yen
        }
        
        # Use fallback if symbol is problematic for PDF
        if currency_symbol in symbol_fallbacks:
            currency_symbol = symbol_fallbacks[currency_symbol]
    
    # Format with commas and specified decimal places
    formatted_amount = f"{float(amount):,.{decimal_places}f}"
    
    return f"{currency_symbol}{formatted_amount}"


def validate_image_file(image_file, max_size_mb=5):
    """
    Validate uploaded image file
    
    Args:
        image_file: Uploaded file object
        max_size_mb (int): Maximum file size in MB
    
    Returns:
        tuple: (is_valid, error_message)
    """
    if not image_file:
        return True, None
    
    # Check file size
    max_size_bytes = max_size_mb * 1024 * 1024
    if image_file.size > max_size_bytes:
        return False, f"File size cannot exceed {max_size_mb}MB"
    
    # Check file extension
    valid_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
    file_extension = image_file.name.lower().split('.')[-1]
    if f'.{file_extension}' not in valid_extensions:
        return False, "File must be a JPG, PNG, GIF, or WebP image"
    
    # Check MIME type
    valid_mime_types = [
        'image/jpeg', 'image/png', 'image/gif', 'image/webp'
    ]
    if hasattr(image_file, 'content_type') and image_file.content_type not in valid_mime_types:
        return False, "Invalid image file type"
    
    return True, None


def clean_phone_number(phone_number):
    """
    Clean and format phone number
    
    Args:
        phone_number (str): Raw phone number
    
    Returns:
        str: Cleaned phone number
    """
    if not phone_number:
        return phone_number
    
    # Remove all non-digit characters except +
    cleaned = re.sub(r'[^\d+]', '', phone_number)
    
    # Ensure it starts with + if it doesn't have country code
    if not cleaned.startswith('+'):
        cleaned = f'+{cleaned}'
    
    return cleaned


def account_has_full_access(account):
    """
    True if the account has full (elevated) access for all users (owner and team members).

    When False, the account is "profile-only": both the owner and all team members are
    restricted to company profile / bank accounts (and auth). Used when:
    - account.is_approved is False (super admin disapproved), or
    - the account owner has only the Company Profile Viewer role (no elevated permissions).

    This ensures that downgrading the company to "Company Profile Viewer" (either via
    Account.is_approved or by removing the owner from Company Admin) affects team
    members too — they lose access to invoices, job orders, etc., until the company
    is brought back to full access.
    """
    if not account:
        return True
    if not getattr(account, 'is_approved', True):
        return False
    owner = getattr(account, 'owner', None)
    if not owner:
        return True
    from apps.core.feature_permissions import ELEVATED_PERMISSIONS
    return any(owner.has_perm(p) for p in ELEVATED_PERMISSIONS)


def get_account_users_for_filter(user):
    """
    Return User queryset for users in the same account (team members + owner).
    Used for admin-only "Created by" filter dropdowns. Returns empty queryset
    if user has no account. Does NOT affect isolation logic.
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()
    account = getattr(user, 'account_id', None) and getattr(user, 'account', None)
    if not account:
        return User.objects.none()
    return User.objects.filter(account=account).order_by('first_name', 'last_name', 'email')


def get_company_profile_for_user(user, request=None):
    """
    SINGLE SOURCE OF TRUTH for company context resolution.

    Returns the company profile for the given user. Works for:
    - Account owners: user.company_profile or account.company_profile
    - Team members (SubUser): account owner's company profile via user.account

    Team members NEVER get None when the account has a profile — they always
    see the same company (logo, details) as the account owner. This prevents
    team members from being treated as standalone accounts or seeing
    "create company" flows.

    Args:
        user: Authenticated User (owner or linked_user for SubUser)
        request: Optional request for sub_user_id session lookup (fallback)

    Returns:
        CompanyProfile or None (only when account has no profile at all)
    """
    if not user or not getattr(user, 'is_authenticated', True):
        return None

    # 1. Account owner: direct company_profile
    try:
        if hasattr(user, 'company_profile') and user.company_profile is not None:
            profile = user.company_profile
            if profile:
                return profile
    except Exception:
        pass

    # 2. Via account: works for BOTH owners and team members (linked_user)
    #    linked_user has account_id = account_owner.account_id from ensure_subuser_linked_user
    try:
        account_id = getattr(user, 'account_id', None)
        if account_id and hasattr(user, 'account'):
            account = user.account
            # Account.company_profile via CompanyProfile.account FK
            profile = getattr(account, 'company_profile', None)
            if profile:
                return profile
            # Fallback: account may have profile only via owner (legacy account=null)
            owner = getattr(account, 'owner', None)
            if owner and hasattr(owner, 'company_profile'):
                try:
                    return owner.company_profile
                except Exception:
                    pass
    except Exception:
        pass

    # 3. Team member fallback: resolve via session sub_user_id
    #    (e.g. before account_id is persisted on linked_user)
    if request and getattr(request, 'session', None):
        sub_user_id = request.session.get('sub_user_id')
        if sub_user_id:
            try:
                from apps.accounts.models import SubUser
                sub_user = SubUser.objects.select_related(
                    'account_owner', 'account_owner__account'
                ).filter(id=sub_user_id, linked_user=user).first()
                if sub_user and sub_user.account_owner_id:
                    owner = sub_user.account_owner
                    # Owner's company profile
                    try:
                        if hasattr(owner, 'company_profile') and owner.company_profile:
                            return owner.company_profile
                    except Exception:
                        pass
                    # Owner's account company profile
                    if owner.account_id:
                        try:
                            profile = getattr(owner.account, 'company_profile', None)
                            if profile:
                                return profile
                        except Exception:
                            pass
            except Exception:
                pass

    return None


def get_company_context(user, request=None):
    """
    Get company context for templates.
    Uses get_company_profile_for_user so team members (linked_user) get
    the account's company profile (logo, currency, etc.).
    Pass request when available so team members resolve via session if needed.

    Args:
        user: User instance
        request: Optional request for session-based company resolution (team members)

    Returns:
        dict: Company context data
    """
    company_profile = get_company_profile_for_user(user, request)
    if company_profile:
        return {
            'company_profile': company_profile,
            'company_logo': company_profile.logo.url if company_profile.logo else None,
            'company_signature': company_profile.signature.url if company_profile.signature else None,
            'currency_symbol': company_profile.currency_symbol,
            'currency_code': company_profile.currency_code,
            # Theme colors from company profile
            'theme_primary_color': getattr(company_profile, 'primary_color', '#1976d2') or '#1976d2',
            'theme_secondary_color': getattr(company_profile, 'secondary_color', '#f8f9fa') or '#f8f9fa',
            'theme_accent_color': getattr(company_profile, 'accent_color', '#e9ecef') or '#e9ecef',
            'theme_text_color': getattr(company_profile, 'text_color', '#333333') or '#333333',
        }
    return {
        'company_profile': None,
        'company_logo': None,
        'company_signature': None,
        'currency_symbol': '$',
        'currency_code': 'USD',
        'theme_primary_color': '#1976d2',
        'theme_secondary_color': '#f8f9fa',
        'theme_accent_color': '#e9ecef',
        'theme_text_color': '#333333',
    }


def calculate_percentage(amount, percentage):
    """
    Calculate percentage of an amount
    
    Args:
        amount (float/Decimal): Base amount
        percentage (float/Decimal): Percentage to calculate
    
    Returns:
        float: Calculated percentage amount
    """
    if not amount or not percentage:
        return 0
    
    return float(amount) * (float(percentage) / 100)


def apply_custom_charges(base_amount, custom_charges):
    """
    Apply custom charges to base amount
    
    Args:
        base_amount (float/Decimal): Base amount
        custom_charges (dict): Custom charges dictionary
    
    Returns:
        dict: Applied charges with totals
    """
    applied_charges = {}
    total_charges = 0
    
    if custom_charges and isinstance(custom_charges, dict):
        for charge_name, charge_value in custom_charges.items():
            try:
                charge_amount = float(charge_value)
                applied_charges[charge_name] = charge_amount
                total_charges += charge_amount
            except (ValueError, TypeError):
                # Skip invalid charge values
                continue
    
    return {
        'charges': applied_charges,
        'total_charges': total_charges,
        'final_amount': float(base_amount) + total_charges
    }
