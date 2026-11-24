from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.views.decorators.cache import never_cache
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.core.cache import cache
from django.views.decorators.cache import cache_page
from django.core.exceptions import PermissionDenied
import json

from .models import Account, CompanyProfile, BankAccount
from .forms import CompanyProfileForm, BankAccountForm
from .utils import get_currency_info
from .ownership import for_user_queryset, is_company_admin
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from django.db.models import Sum, F, Case, When, Value, Q
from django.db.models.functions import Least
from django.db.models.fields import DecimalField


def _get_account_id_for_dashboard(user, request=None):
    """Get account_id for company-scoped dashboard. Same resolution as for_user_queryset (get_account_for_user)."""
    from .ownership import get_account_for_user
    account = get_account_for_user(user)
    return account.pk if account else None


def _core_owner_or_perm(request, view_perm=None, change_perm=None, add_perm=None, delete_perm=None):
    """
    True if request.user is superuser, the account owner (full access), or has the given permission.
    Superuser is never restricted; company admin (account owner) is never restricted for core features.
    """
    if getattr(request.user, 'is_superuser', False):
        return True
    if getattr(request.user, 'is_staff', False):
        return True
    # Account owner (company admin): always full access — DB check bypasses session/perm cache.
    # Allow owner regardless of is_approved for company profile; owner must always access their profile.
    account = getattr(request.user, 'account', None)
    if account is not None and getattr(account, 'owner_id', None) == request.user.id:
        return True
    # Fallback: user owns an account — handles request.user.account=None or stale relation
    if Account.objects.filter(owner_id=request.user.id).exists():
        return True
    from apps.accounts.rbac import is_account_owner
    if is_account_owner(request):
        return True
    if view_perm and request.user.has_perm(view_perm):
        return True
    if change_perm and request.user.has_perm(change_perm):
        return True
    if add_perm and request.user.has_perm(add_perm):
        return True
    if delete_perm and request.user.has_perm(delete_perm):
        return True
    return False


def get_cached_dashboard_stats(user, cache_timeout=0, request=None):
    """
    Get dashboard statistics. Optionally cached for faster loading.
    Per-team-member isolation: company admin sees all account records; team members
    see only their own. Cache key includes user when not admin so stats are per-user.
    Use cache_timeout=0 (default) for real-time accuracy; set >0 to cache.
    """
    account_id = _get_account_id_for_dashboard(user, request)
    if not account_id:
        return {
            'monthly_revenue': 0,
            'monthly_invoice_count': 0,
            'today_revenue': 0,
            'today_invoice_count': 0,
            'outstanding_invoices': 0,
            'refund_due': 0,
            'total_invoices': 0,
            'total_quotations': 0,
            'total_waybills': 0,
            'total_clients': 0,
            'invoice_status_breakdown': {'unpaid': 0, 'partial': 0, 'paid': 0},
            'revenue_trend_labels': [],
            'revenue_trend_data': [],
            'histogram_labels': [],
            'histogram_data': [],
        }
    admin = is_company_admin(user, request)
    cache_key = f'dashboard_stats_account_{account_id}' if admin else f'dashboard_stats_account_{account_id}_user_{user.pk}'
    if cache_timeout > 0:
        cached_stats = cache.get(cache_key)
        if cached_stats:
            return cached_stats

    from apps.invoices.models import Invoice
    from apps.quotations.models import Quotation
    from apps.waybills.models import Waybill
    from apps.clients.models import Client
    from datetime import datetime

    now = timezone.now()
    today = now.date()
    current_month = now.month
    current_year = now.year
    start_of_month = datetime(current_year, current_month, 1).date()

    # Visibility-scoped: admin sees all account; team member sees only own (for_user_queryset)
    invoices = for_user_queryset(Invoice, user, request, account_lookup='account')
    quotations = for_user_queryset(Quotation, user, request, account_lookup='account')
    waybills = for_user_queryset(Waybill, user, request, account_lookup='account')
    clients = for_user_queryset(Client, user, request, account_lookup='company__account')

    # Revenue = capped at grand_total per invoice (same logic as invoice app)
    invoices_capped = invoices.annotate(rev_cap=Least(F('amount_paid'), F('grand_total')))
    # Outstanding = only positive balance_due (what customers still owe)
    outstanding_invoices = invoices.aggregate(
        s=Sum(Case(When(balance_due__gt=0, then=F('balance_due')), default=Value(Decimal('0')), output_field=DecimalField()))
    )['s'] or 0
    # Refund due to customer (overpayments)
    refund_due = invoices.aggregate(
        s=Sum(Case(When(amount_paid__gt=F('grand_total'), then=F('amount_paid') - F('grand_total')), default=Value(Decimal('0')), output_field=DecimalField()))
    )['s'] or 0

    # Monthly statistics (current month) — use capped revenue
    monthly_invoices = invoices_capped.filter(invoice_date__gte=start_of_month)
    monthly_revenue = monthly_invoices.aggregate(s=Sum('rev_cap'))['s'] or 0
    monthly_invoice_count = invoices.filter(invoice_date__gte=start_of_month).count()

    # Today's statistics — use capped revenue
    today_invoices = invoices_capped.filter(invoice_date=today)
    today_revenue = today_invoices.aggregate(s=Sum('rev_cap'))['s'] or 0
    today_invoice_count = invoices.filter(invoice_date=today).count()

    # Last 6 months revenue (capped) for Revenue Trend chart
    revenue_trend_labels = []
    revenue_trend_data = []
    for i in range(5, -1, -1):
        # month_offset: 5 months ago, 4, 3, 2, 1, current
        year = current_year
        month = current_month - i
        while month < 1:
            month += 12
            year -= 1
        month_start = datetime(year, month, 1).date()
        if month == 12:
            month_end = datetime(year, 12, 31).date()
        else:
            month_end = datetime(year, month + 1, 1).date() - timedelta(days=1)
        rev = invoices_capped.filter(invoice_date__gte=month_start, invoice_date__lte=month_end).aggregate(s=Sum('rev_cap'))['s'] or 0
        revenue_trend_labels.append(month_start.strftime('%b'))
        revenue_trend_data.append(float(rev))

    # Other statistics
    total_invoices = invoices.count()
    total_quotations = quotations.count()
    total_waybills = waybills.count()
    total_clients = clients.count()

    # Status breakdown
    invoice_status_breakdown = {
        'unpaid': invoices.filter(status='unpaid').count(),
        'partial': invoices.filter(status='partial').count(),
        'paid': invoices.filter(status='paid').count(),
    }

    # Histogram: invoice count by amount buckets (grand_total)
    histogram_buckets = [
        (Decimal('0'), Decimal('10000'), '0 - 10k'),
        (Decimal('10000'), Decimal('50000'), '10k - 50k'),
        (Decimal('50000'), Decimal('100000'), '50k - 100k'),
        (Decimal('100000'), Decimal('500000'), '100k - 500k'),
        (Decimal('500000'), None, '500k+'),
    ]
    histogram_labels = []
    histogram_data = []
    for low, high, label in histogram_buckets:
        q = Q(grand_total__gte=low)
        if high is not None:
            q &= Q(grand_total__lt=high)
        else:
            q &= Q(grand_total__isnull=False)  # 500k+ no upper bound
        histogram_labels.append(label)
        histogram_data.append(invoices.filter(q).count())

    stats = {
        'monthly_revenue': monthly_revenue,
        'monthly_invoice_count': monthly_invoice_count,
        'today_revenue': today_revenue,
        'today_invoice_count': today_invoice_count,
        'outstanding_invoices': outstanding_invoices,
        'refund_due': refund_due,
        'total_invoices': total_invoices,
        'total_quotations': total_quotations,
        'total_waybills': total_waybills,
        'total_clients': total_clients,
        'invoice_status_breakdown': invoice_status_breakdown,
        'revenue_trend_labels': revenue_trend_labels,
        'revenue_trend_data': revenue_trend_data,
        'histogram_labels': histogram_labels,
        'histogram_data': histogram_data,
    }
    
    # Cache the stats only when cache_timeout > 0 (real-time by default)
    if cache_timeout > 0:
        cache.set(cache_key, stats, cache_timeout)
    
    return stats


def get_recent_activities(user, request=None):
    """Get recent activities for the dashboard. Visibility-scoped: admin sees all account; team member sees own.
    Only includes activity types the user has permission to see (prevents permission leak).
    """
    activities = []
    account_id = _get_account_id_for_dashboard(user, request)
    if not account_id:
        return []
    if user.has_perm('invoices.view_invoice'):
        try:
            from apps.invoices.models import Invoice
            recent_invoices = for_user_queryset(Invoice, user, request, account_lookup='account').order_by('-created_at')[:3]
            for invoice in recent_invoices:
                activities.append({
                    'type': 'invoice',
                    'icon': 'fa-receipt',
                    'title': f'Invoice #{invoice.invoice_number} created',
                    'description': f'Invoice for {invoice.client_name or "Unknown Client"}',
                    'url': f'/invoices/{invoice.id}/',
                    'timestamp': invoice.created_at,
                    'amount': invoice.grand_total,
                })
        except ImportError:
            pass
    if user.has_perm('quotations.view_quotation'):
        try:
            from apps.quotations.models import Quotation
            recent_quotations = for_user_queryset(Quotation, user, request, account_lookup='account').order_by('-created_at')[:2]
            for quotation in recent_quotations:
                activities.append({
                    'type': 'quotation',
                    'icon': 'fa-file-invoice',
                    'title': f'Quotation #{quotation.quotation_number} created',
                    'description': f'Quotation for {quotation.client.name if quotation.client else "Unknown Client"}',
                    'url': f'/quotations/{quotation.id}/',
                    'timestamp': quotation.created_at,
                    'amount': quotation.grand_total,
                })
        except ImportError:
            pass
    if user.has_perm('clients.view_client'):
        try:
            from apps.clients.models import Client
            recent_clients = for_user_queryset(Client, user, request, account_lookup='company__account').order_by('-created_at')[:2]
            for client in recent_clients:
                activities.append({
                    'type': 'client',
                    'icon': 'fa-user-plus',
                    'title': f'New client added: {client.name}',
                    'description': f'Client contact: {client.email}',
                    'url': f'/clients/{client.id}/',
                    'timestamp': client.created_at,
                    'amount': None,
                })
        except ImportError:
            pass
    if user.has_perm('waybills.view_waybill'):
        try:
            from apps.waybills.models import Waybill
            recent_waybills = for_user_queryset(Waybill, user, request, account_lookup='account').order_by('-created_at')[:2]
            for waybill in recent_waybills:
                client_name = "Unknown Client"
                if waybill.custom_data and 'receiver_info' in waybill.custom_data:
                    client_name = waybill.custom_data['receiver_info'].get('receiver_name', 'Unknown Client')
                activities.append({
                    'type': 'waybill',
                    'icon': 'fa-truck',
                    'title': f'Waybill #{waybill.waybill_number} created',
                    'description': f'Waybill for {client_name}',
                    'url': f'/waybills/{waybill.id}/',
                    'timestamp': waybill.created_at,
                    'amount': None,
                })
        except ImportError:
            pass
    activities.sort(key=lambda x: x['timestamp'], reverse=True)
    return activities[:5]


def landing_page(request):
    """Landing page for non-authenticated users"""
    return render(request, 'core/landing_page.html')


@login_required
@never_cache
def dashboard(request):
    """
    Main dashboard view with real-time statistics.
    
    PERFORMANCE OPTIMIZATIONS:
    - Database queries are cached for 60 seconds
    - Bank accounts use select_related to avoid N+1 queries
    - Recent activities are fetched efficiently
    """
    from .utils import get_company_profile_for_user
    company_profile = get_company_profile_for_user(request.user, request)
    if not company_profile:
        messages.warning(request, 'Please complete your company profile first.')
        return redirect('core:company_profile')
    # Get cached statistics (company-scoped; same for owner and team members)
    stats = get_cached_dashboard_stats(request.user, request=request)
    
    # Extract stats
    monthly_revenue = stats['monthly_revenue']
    monthly_invoice_count = stats['monthly_invoice_count']
    outstanding_invoices = stats['outstanding_invoices']
    total_clients = stats['total_clients']
    
    # Calculate progress percentage (example: 100k monthly goal)
    monthly_goal = 100000
    progress_percentage = min(100, (monthly_revenue / monthly_goal) * 100) if monthly_goal > 0 else 0
    
    # Calculate time saved (estimate)
    estimated_time_saved_per_invoice = 0.5  # hours
    time_saved_this_week = monthly_invoice_count * estimated_time_saved_per_invoice / 4
    
    # Calculate login streak from UserActivity model
    try:
        from .models import UserActivity
        login_streak = UserActivity.get_user_streak(request.user)
        # Record dashboard view activity (async would be even better)
        UserActivity.record_activity(
            user=request.user,
            activity_type='dashboard_view',
            description='Dashboard viewed'
        )
    except (ImportError, AttributeError):
        login_streak = 7  # Fallback if model doesn't exist yet
    
    # Today's focus (dynamic)
    if outstanding_invoices > 0:
        today_focus = "Invoice Follow-up"
    elif total_clients < 5:
        today_focus = "Client Acquisition"
    else:
        today_focus = "Growing Revenue"
    
    # Use prefetch_related for bank accounts to avoid extra queries
    bank_accounts = company_profile.bank_accounts.all()
    user = request.user
    # Only pass stats the user has permission to see (prevents permission leak for team members)
    can_view_invoice = user.has_perm('invoices.view_invoice')
    can_view_client = user.has_perm('clients.view_client')
    can_view_quotation = user.has_perm('quotations.view_quotation')
    can_view_waybill = user.has_perm('waybills.view_waybill')
    can_view_document = user.has_perm('documents.view_document')
    can_view_tax_report = user.has_perm('documents.view_tax_report')
    total_documents = 0
    if can_view_document:
        from apps.documents.models import Document
        total_documents = Document.objects.filter(company=company_profile).count()
    # Full display name (first + last) for welcome; fallback to email
    user_display_name = (user.get_full_name() or '').strip() or user.email or 'User'

    # Business Overview chart: only include segments for modules the user can view (RBAC)
    chart_overview_labels = []
    chart_overview_data = []
    if can_view_invoice:
        chart_overview_labels.append('Invoices')
        chart_overview_data.append(stats['total_invoices'])
    if can_view_quotation:
        chart_overview_labels.append('Quotations')
        chart_overview_data.append(stats['total_quotations'])
    if can_view_waybill:
        chart_overview_labels.append('Waybills')
        chart_overview_data.append(stats['total_waybills'])

    context = {
        'user_display_name': user_display_name,
        'company_profile': company_profile,
        'bank_accounts': bank_accounts,
        'total_bank_accounts': len(bank_accounts),  # Use len() to avoid another query
        'currency_symbol': getattr(company_profile, 'currency_symbol', None) or '₦',

        # Real-time statistics
        'today_focus': today_focus,
        'progress_percentage': round(progress_percentage, 1),
        'time_saved_this_week': round(time_saved_this_week, 1),
        'login_streak': login_streak,

        # Financial metrics (only pass if user has permission; avoid leaking to restricted roles)
        'monthly_revenue': stats['monthly_revenue'] if can_view_invoice else 0,
        'today_revenue': stats['today_revenue'] if can_view_invoice else 0,
        'outstanding_invoices': stats['outstanding_invoices'] if can_view_invoice else 0,
        'refund_due': stats.get('refund_due', 0) if can_view_invoice else 0,

        # Count metrics (only pass if user has permission)
        'total_invoices': stats['total_invoices'] if can_view_invoice else 0,
        'monthly_invoice_count': stats['monthly_invoice_count'] if can_view_invoice else 0,
        'today_invoice_count': stats['today_invoice_count'] if can_view_invoice else 0,
        'total_quotations': stats['total_quotations'] if can_view_quotation else 0,
        'total_waybills': stats['total_waybills'] if can_view_waybill else 0,
        'total_clients': stats['total_clients'] if can_view_client else 0,
        'total_documents': total_documents if can_view_document else 0,
        'can_view_document': can_view_document,
        'can_view_tax_report': can_view_tax_report,

        # Status breakdowns (only pass if user can view invoices)
        'invoice_status_breakdown': stats['invoice_status_breakdown'] if can_view_invoice else {'unpaid': 0, 'partial': 0, 'paid': 0},
        'invoice_status_pie_labels_json': json.dumps(['Unpaid', 'Partial', 'Paid']) if can_view_invoice else '[]',
        'invoice_status_pie_data_json': json.dumps([
            int(stats['invoice_status_breakdown'].get('unpaid', 0)),
            int(stats['invoice_status_breakdown'].get('partial', 0)),
            int(stats['invoice_status_breakdown'].get('paid', 0)),
        ]) if can_view_invoice else '[]',

        # Chart data (RBAC: revenue trend only if can view invoices; overview only permitted segments)
        'revenue_trend_labels': stats.get('revenue_trend_labels', []) if can_view_invoice else [],
        'revenue_trend_data': stats.get('revenue_trend_data', []) if can_view_invoice else [],
        'revenue_trend_labels_json': json.dumps(stats.get('revenue_trend_labels', []) if can_view_invoice else []),
        'revenue_trend_data_json': json.dumps(stats.get('revenue_trend_data', []) if can_view_invoice else []),
        'chart_overview_labels': chart_overview_labels,
        'chart_overview_data': chart_overview_data,
        'chart_overview_labels_json': json.dumps(chart_overview_labels),
        'chart_overview_data_json': json.dumps([int(x) for x in chart_overview_data]),
        'histogram_labels_json': json.dumps(stats.get('histogram_labels', []) if can_view_invoice else []),
        'histogram_data_json': json.dumps([int(x) for x in (stats.get('histogram_data', []) if can_view_invoice else [])]),

        # Recent activities (company-scoped)
        'recent_activities': get_recent_activities(request.user, request=request),
    }
    return render(request, 'core/dashboard.html', context)


@login_required
def company_profile_view(request):
    """Company profile view and edit. Superuser/staff/owner always have full access; team members need permissions."""
    from .utils import get_company_profile_for_user
    from apps.accounts.rbac import is_account_owner
    # Ensure new registrants have account linked (fixes registration edge cases)
    account_id = getattr(request.user, 'account_id', None)
    if not account_id:
        owned = Account.objects.filter(owner_id=request.user.id).first()
        if owned:
            from django.contrib.auth import get_user_model
            get_user_model().objects.filter(pk=request.user.id).update(account_id=owned.id)
            request.user.account_id = owned.id
            request.user.account = owned
    # Immediate bypass: account owner (user owns any account) — always allow
    if not (getattr(request.user, 'is_superuser', False) or getattr(request.user, 'is_staff', False)):
        if Account.objects.filter(owner_id=request.user.id).exists():
            pass  # Account owner: allow through
        else:
            account_id = getattr(request.user, 'account_id', None)
            if account_id:
                owner_id = Account.objects.filter(pk=account_id).values_list('owner_id', flat=True).first()
                if owner_id is None:
                    Account.objects.filter(pk=account_id).update(owner_id=request.user.id)
                else:
                    if not _core_owner_or_perm(request, view_perm='core.view_companyprofile', change_perm='core.change_companyprofile'):
                        raise PermissionDenied('You do not have permission to access company profile.')
            elif not _core_owner_or_perm(request, view_perm='core.view_companyprofile', change_perm='core.change_companyprofile'):
                raise PermissionDenied('You do not have permission to access company profile.')
    company_profile = get_company_profile_for_user(request.user, request)
    is_team_member = not is_account_owner(request)
    created = company_profile is None

    # Team members: never show create form — only view or read-only message (superuser/staff can create)
    if is_team_member and created and not (getattr(request.user, 'is_superuser', False) or getattr(request.user, 'is_staff', False)):
        context = {
            'company_profile': None,
            'created': False,
            'is_team_member': True,
            'read_only_message': 'Company profile has not been set up yet. Contact your account owner to complete setup.',
        }
        return render(request, 'core/company_profile.html', context)

    if request.method == 'POST':
        # Allow POST: superuser/staff/approved account owner always; team member needs change_companyprofile
        if not _core_owner_or_perm(request, change_perm='core.change_companyprofile'):
            raise PermissionDenied('You do not have permission to edit the company profile.')
        # Team members cannot create; only owners or superuser/staff can POST create
        if is_team_member and created and not (getattr(request.user, 'is_superuser', False) or getattr(request.user, 'is_staff', False)):
            raise PermissionDenied('Only the account owner can create the company profile.')
        # Block cross-company modification for non–superuser/staff (superuser/staff may update any).
        # Account owner can ALWAYS edit their company profile (no restriction after approval/Company Admin).
        user_is_account_owner = Account.objects.filter(owner_id=request.user.id).exists()
        if not user_is_account_owner and not (getattr(request.user, 'is_superuser', False) or getattr(request.user, 'is_staff', False)):
            if not created and company_profile:
                profile_account_id = getattr(company_profile, 'account_id', None)
                user_account_id = getattr(request.user, 'account_id', None)
                profile_belongs_to_user = getattr(company_profile, 'user_id', None) == request.user.id
                if profile_account_id != user_account_id:
                    # Allow if user owns the profile's account, or profile has no account but belongs to this user
                    is_owner_of_profile_account = (
                        profile_account_id is not None
                        and Account.objects.filter(pk=profile_account_id).values_list('owner_id', flat=True).first() == request.user.id
                    )
                    if not is_owner_of_profile_account and not (profile_account_id is None and profile_belongs_to_user):
                        raise PermissionDenied('You cannot modify another account\'s company profile.')
        form = CompanyProfileForm(request.POST, request.FILES, instance=company_profile)
        if form.is_valid():
            # Delete old files if new ones are uploaded
            if company_profile and 'logo' in request.FILES:
                company_profile.delete_old_logo()
            if company_profile and 'signature' in request.FILES:
                company_profile.delete_old_signature()

            company_profile = form.save(commit=False)
            company_profile.user = request.user if is_account_owner(request) else company_profile.user
            # CRITICAL: Set account for tenant scoping so owner can always edit after approval.
            profile_account_id = getattr(company_profile, 'account_id', None)
            if profile_account_id and Account.objects.filter(pk=profile_account_id).values_list('owner_id', flat=True).first() == request.user.id:
                company_profile.account_id = profile_account_id
            elif getattr(request.user, 'account_id', None):
                company_profile.account = request.user.account
            else:
                # Account owner may have no request.user.account_id yet: use the account they own
                owned = Account.objects.filter(owner_id=request.user.id).first()
                if owned:
                    company_profile.account_id = owned.pk
            company_profile.save()

            if created:
                messages.success(request, 'Company profile created successfully!')
            else:
                messages.success(request, 'Company profile updated successfully!')

            return redirect('core:dashboard')
    else:
        form = CompanyProfileForm(instance=company_profile)

    # Save button: superuser/staff/account owner always; team member only when they have change permission
    show_save_button = (
        getattr(request.user, 'is_superuser', False) or getattr(request.user, 'is_staff', False)
        or (created and is_account_owner(request))
        or (not created and (is_account_owner(request) or request.user.has_perm('core.change_companyprofile')))
    )
    context = {
        'form': form,
        'company_profile': company_profile,
        'created': created,
        'is_team_member': is_team_member,
        'show_save_button': show_save_button,
    }
    return render(request, 'core/company_profile.html', context)


@login_required
def bank_accounts_view(request):
    """Bank accounts management. Account owner always has full access; team members need permissions."""
    from apps.accounts.rbac import is_account_owner
    if not _core_owner_or_perm(request, view_perm='core.view_companyprofile', change_perm='core.change_companyprofile', add_perm='core.add_bankaccount', delete_perm='core.delete_bankaccount'):
        raise PermissionDenied('You do not have permission to access bank accounts.')
    from .utils import get_company_profile_for_user
    company_profile = get_company_profile_for_user(request.user, request)
    if not company_profile:
        messages.error(request, 'Please complete your company profile first.')
        return redirect('core:company_profile')
    
    bank_accounts = company_profile.bank_accounts.all()
    
    if request.method == 'POST':
        if not (getattr(request.user, 'is_superuser', False) or is_account_owner(request) or request.user.has_perm('core.add_bankaccount')):
            raise PermissionDenied('You do not have permission to add bank accounts.')
        form = BankAccountForm(request.POST)
        if form.is_valid():
            bank_account = form.save(commit=False)
            bank_account.company = company_profile
            
            # Check if account number already exists for this company
            existing_account = BankAccount.objects.filter(
                company=company_profile,
                account_number=bank_account.account_number
            ).first()
            
            if existing_account:
                messages.error(request, f'A bank account with number {bank_account.account_number} already exists for your company.')
                return redirect('core:bank_accounts')
            
            try:
                bank_account.save()
                messages.success(request, 'Bank account added successfully!')
                return redirect('core:bank_accounts')
            except Exception as e:
                messages.error(request, 'Error saving bank account. Please try again.')
                return redirect('core:bank_accounts')
    else:
        form = BankAccountForm()
    
    # Superuser/account owner always has full access; team members need explicit permissions
    is_superuser = getattr(request.user, 'is_superuser', False)
    can_add_bank_account = is_superuser or is_account_owner(request) or request.user.has_perm('core.add_bankaccount')
    can_change_bank_account = is_superuser or is_account_owner(request) or request.user.has_perm('core.change_bankaccount')
    can_delete_bank_account = is_superuser or is_account_owner(request) or request.user.has_perm('core.delete_bankaccount')
    
    context = {
        'form': form,
        'bank_accounts': bank_accounts,
        'company_profile': company_profile,
        'can_add_bank_account': can_add_bank_account,
        'can_change_bank_account': can_change_bank_account,
        'can_delete_bank_account': can_delete_bank_account,
    }
    
    return render(request, 'core/bank_accounts.html', context)


@login_required
def edit_bank_account(request, pk):
    """Edit bank account. Superuser/account owner always allowed; team members need change_bankaccount."""
    from apps.accounts.rbac import is_account_owner
    if not (getattr(request.user, 'is_superuser', False) or is_account_owner(request) or request.user.has_perm('core.change_bankaccount')):
        raise PermissionDenied('You do not have permission to edit bank accounts.')
    from .utils import get_company_profile_for_user
    company = get_company_profile_for_user(request.user, request)
    if not company:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()
    bank_account = get_object_or_404(BankAccount, pk=pk, company=company)
    
    if request.method == 'POST':
        form = BankAccountForm(request.POST, instance=bank_account)
        if form.is_valid():
            form.save()
            messages.success(request, 'Bank account updated successfully!')
            return redirect('core:bank_accounts')
    else:
        form = BankAccountForm(instance=bank_account)
    
    context = {
        'form': form,
        'bank_account': bank_account,
        'edit_mode': True,
    }
    
    return render(request, 'core/bank_account_form.html', context)


@login_required
def delete_bank_account(request, pk):
    """Delete bank account. Superuser/account owner always allowed; team members need delete_bankaccount."""
    from apps.accounts.rbac import is_account_owner
    if not (getattr(request.user, 'is_superuser', False) or is_account_owner(request) or request.user.has_perm('core.delete_bankaccount')):
        raise PermissionDenied('You do not have permission to delete bank accounts.')
    from .utils import get_company_profile_for_user
    company = get_company_profile_for_user(request.user, request)
    if not company:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()
    bank_account = get_object_or_404(BankAccount, pk=pk, company=company)
    
    if request.method == 'POST':
        bank_account.delete()
        messages.success(request, 'Bank account deleted successfully!')
        return redirect('core:bank_accounts')
    
    context = {
        'bank_account': bank_account,
    }
    
    return render(request, 'core/confirm_delete.html', context)


@login_required
@require_http_methods(["POST"])
def set_default_bank_account(request, pk):
    """Set default bank account via AJAX. Superuser/account owner always allowed; team members need change_bankaccount."""
    from apps.accounts.rbac import is_account_owner
    if not (getattr(request.user, 'is_superuser', False) or is_account_owner(request) or request.user.has_perm('core.change_bankaccount')):
        return JsonResponse({'success': False, 'error': 'You do not have permission to change bank account settings.'}, status=403)
    from .utils import get_company_profile_for_user
    company = get_company_profile_for_user(request.user, request)
    if not company:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()
    bank_account = get_object_or_404(BankAccount, pk=pk, company=company)
    
    # Update all accounts to not default, then set this one as default
    BankAccount.objects.filter(company=bank_account.company).update(is_default=False)
    bank_account.is_default = True
    bank_account.save()
    
    return JsonResponse({'success': True, 'message': 'Default bank account updated successfully!'})


@csrf_exempt
@require_http_methods(["POST"])
def update_currency(request):
    """Update company currency settings. Superuser/account owner always allowed; team members need change_companyprofile."""
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': 'Authentication required'})
    from apps.accounts.rbac import is_account_owner
    if not (getattr(request.user, 'is_superuser', False) or is_account_owner(request) or request.user.has_perm('core.change_companyprofile')):
        return JsonResponse({'success': False, 'error': 'You do not have permission to change company settings.'}, status=403)
    
    try:
        # Parse JSON data
        data = json.loads(request.body)
        currency_code = data.get('currency_code')
        
        if not currency_code:
            return JsonResponse({'success': False, 'error': 'Currency code is required'})
        
        # Validate currency code
        currency_info = get_currency_info(currency_code)
        if not currency_info:
            return JsonResponse({'success': False, 'error': f'Invalid currency code: {currency_code}'})
        
        from .utils import get_company_profile_for_user
        company_profile = get_company_profile_for_user(request.user, request)
        if not company_profile:
            return JsonResponse({'success': False, 'error': 'Company profile not found. Please complete your company profile first.'})
        
        # Store old currency for comparison
        old_currency = company_profile.currency_symbol
        
        # Update company profile currency
        company_profile.currency_code = currency_code
        company_profile.currency_symbol = currency_info['symbol']
        company_profile.save()
        
        # Update accounting transactions if currency changed
        transactions_updated = 0
        job_orders_updated = 0
        if old_currency != currency_info['symbol']:
            try:
                from apps.accounting.models import Transaction
                # Update all transactions for this company
                transactions_updated = Transaction.objects.filter(
                    company=company_profile
                ).update(currency=currency_info['symbol'])
            except ImportError:
                # Accounting app might not be installed
                pass
            except Exception as transaction_error:
                # Log transaction update error but don't fail the currency update
                print(f"Warning: Failed to update transactions: {transaction_error}")
                pass
            
            # Update job orders if currency changed (scope by account for team members)
            try:
                from apps.job_orders.models import Product, Order
                account_id = getattr(company_profile, 'account_id', None)
                if account_id:
                    products = Product.objects.filter(created_by__account_id=account_id)
                    for product in products:
                        product.save()  # Trigger save to update currency displays
                        job_orders_updated += 1
                    orders = Order.objects.filter(customer__account_id=account_id)
                    for order in orders:
                        order.save()  # Trigger save to update currency displays
                        job_orders_updated += 1
                else:
                    products = Product.objects.filter(created_by__company_profile=company_profile)
                    for product in products:
                        product.save()
                        job_orders_updated += 1
                    orders = Order.objects.filter(customer__company_profile=company_profile)
                    for order in orders:
                        order.save()
                        job_orders_updated += 1
                    
            except ImportError:
                # Job orders app might not be installed
                pass
            except Exception as job_order_error:
                # Log job order update error but don't fail the currency update
                print(f"Warning: Failed to update job orders: {job_order_error}")
                pass
        
        return JsonResponse({
            'success': True,
            'currency_code': currency_code,
            'currency_symbol': currency_info['symbol'],
            'transactions_updated': transactions_updated,
            'job_orders_updated': job_orders_updated,
            'message': f'Currency updated to {currency_code} ({currency_info["symbol"]}). {transactions_updated} transactions and {job_orders_updated} job orders updated.'
        })
        
    except json.JSONDecodeError as e:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data provided'})
    except Exception as e:
        # Log the full error for debugging
        import traceback
        print(f"Currency update error: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        return JsonResponse({'success': False, 'error': f'Failed to update currency: {str(e)}'})
