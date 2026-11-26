from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import never_cache
from django.utils import timezone
from django.db.models import Sum, Count, Q
from django.conf import settings
from datetime import datetime, timedelta
import json

from .models import CompanyProfile
from .ownership import for_user_queryset, is_company_admin
from .utils import get_company_context, get_company_profile_for_user, number_to_words
from apps.invoices.models import Invoice
from apps.quotations.models import Quotation
from apps.waybills.models import Waybill
from apps.clients.models import Client
from apps.inventory.models import Inventory
from decimal import Decimal


def _invoice_qs(request):
    """Visibility-scoped invoice queryset: admin sees all account invoices, team member sees own."""
    return for_user_queryset(Invoice, request.user, request, account_lookup='account')


def _quotation_qs(request):
    return for_user_queryset(Quotation, request.user, request, account_lookup='account')


def _waybill_qs(request):
    return for_user_queryset(Waybill, request.user, request, account_lookup='account')


def _inventory_qs(request):
    """Visibility-scoped: admin sees all account inventory; team member sees only own (created_by=request.user)."""
    return for_user_queryset(Inventory, request.user, request, account_lookup='account')


@login_required
@require_http_methods(["GET"])
def dashboard_stats(request):
    """Get real-time dashboard statistics"""
    company_profile = get_company_profile_for_user(request.user, request)
    if not company_profile:
        return JsonResponse({'error': 'Company profile not found'}, status=400)
    
    # Get current date and time
    now = timezone.now()
    today = now.date()
    current_month = now.month
    current_year = now.year
    
    # Calculate date ranges
    start_of_month = datetime(current_year, current_month, 1).date()
    start_of_week = today - timedelta(days=today.weekday())
    start_of_year = datetime(current_year, 1, 1).date()
    
    # Invoice Statistics (company-scoped)
    invoices = _invoice_qs(request)
    total_invoices = invoices.count()
    
    # Monthly invoice stats
    monthly_invoices = invoices.filter(invoice_date__gte=start_of_month)
    monthly_invoice_count = monthly_invoices.count()
    monthly_revenue = monthly_invoices.aggregate(
        total=Sum('grand_total')
    )['total'] or 0
    
    # Today's invoices
    today_invoices = invoices.filter(invoice_date=today)
    today_invoice_count = today_invoices.count()
    today_revenue = today_invoices.aggregate(
        total=Sum('grand_total')
    )['total'] or 0
    
    # Outstanding invoices
    outstanding_invoices = invoices.filter(
        status__in=['unpaid', 'partial']
    ).aggregate(
        total=Sum('balance_due')
    )['total'] or 0
    
    # Quotation Statistics (company-scoped)
    quotations = _quotation_qs(request)
    total_quotations = quotations.count()
    monthly_quotations = quotations.filter(quotation_date__gte=start_of_month).count()
    
    # Waybill Statistics (company-scoped)
    waybills = _waybill_qs(request)
    total_waybills = waybills.count()
    monthly_waybills = waybills.filter(waybill_date__gte=start_of_month).count()
    
    # Client Statistics (visibility-scoped: admin sees all, team member sees own)
    clients_qs = for_user_queryset(Client, request.user, request, account_lookup='company__account')
    total_clients = clients_qs.count()
    new_clients_this_month = clients_qs.filter(created_at__gte=start_of_month).count()
    
    # Inventory Statistics (company-scoped when account exists)
    try:
        inventory_items = _inventory_qs(request)
        total_inventory_items = inventory_items.count()
        low_stock_items = inventory_items.filter(
            Q(data__quantity__lte=5) | Q(data__Quantity__lte=5)
        ).count()
    except:
        total_inventory_items = 0
        low_stock_items = 0
    
    # Calculate progress percentage (based on monthly goals)
    # You can customize this logic based on your business goals
    monthly_goal = 100000  # Example: 100k monthly revenue goal
    progress_percentage = min(100, (monthly_revenue / monthly_goal) * 100) if monthly_goal > 0 else 0
    
    # Calculate time saved (estimate based on automation)
    # This is a rough estimate - you can make it more sophisticated
    estimated_time_saved_per_invoice = 0.5  # hours
    time_saved_this_week = monthly_invoice_count * estimated_time_saved_per_invoice / 4
    
    # Calculate login streak from UserActivity model
    try:
        from .models import UserActivity
        login_streak = UserActivity.get_user_streak(request.user)
    except ImportError:
        login_streak = 7  # Fallback if model doesn't exist yet
    
    # Permission-based filtering: only expose data the user is allowed to see (fix permission leak)
    user = request.user
    can_view_invoice = user.has_perm('invoices.view_invoice')
    can_view_quotation = user.has_perm('quotations.view_quotation')
    can_view_client = user.has_perm('clients.view_client')
    can_view_waybill = user.has_perm('waybills.view_waybill')
    can_view_inventory = user.has_perm('inventory.view_inventory')

    # Today's focus (use only data user can see)
    if can_view_invoice and outstanding_invoices > 0:
        today_focus = "Invoice Follow-up"
    elif can_view_client and new_clients_this_month < 2:
        today_focus = "Client Acquisition"
    elif can_view_inventory and low_stock_items > 0:
        today_focus = "Inventory Management"
    else:
        today_focus = "Growing Revenue"

    data = {
        'today_focus': today_focus,
        'progress_percentage': round(progress_percentage, 1) if can_view_invoice else 0,
        'time_saved_this_week': round(time_saved_this_week, 1) if can_view_invoice else 0,
        'login_streak': login_streak,
    }
    if can_view_invoice:
        data.update({
            'monthly_revenue': float(monthly_revenue),
            'today_revenue': float(today_revenue),
            'outstanding_invoices': float(outstanding_invoices),
            'total_invoices': total_invoices,
            'monthly_invoice_count': monthly_invoice_count,
            'today_invoice_count': today_invoice_count,
            'invoice_status_breakdown': {
                'unpaid': invoices.filter(status='unpaid').count(),
                'partial': invoices.filter(status='partial').count(),
                'paid': invoices.filter(status='paid').count(),
            },
            'recent_invoices': [
                {
                    'id': inv.id,
                    'number': inv.invoice_number,
                    'client': inv.client_name,
                    'amount': float(inv.grand_total),
                    'status': inv.status,
                    'date': inv.invoice_date.strftime('%Y-%m-%d')
                }
                for inv in invoices.order_by('-created_at')[:5]
            ],
        })
    else:
        data.update({
            'monthly_revenue': 0, 'today_revenue': 0, 'outstanding_invoices': 0,
            'total_invoices': 0, 'monthly_invoice_count': 0, 'today_invoice_count': 0,
            'invoice_status_breakdown': {'unpaid': 0, 'partial': 0, 'paid': 0},
            'recent_invoices': [],
        })
    if can_view_quotation:
        data.update({
            'total_quotations': total_quotations,
            'monthly_quotations': monthly_quotations,
            'quotation_status_breakdown': {
                'pending': quotations.filter(status='pending').count(),
                'accepted': quotations.filter(status='accepted').count(),
                'rejected': quotations.filter(status='rejected').count(),
            },
            'recent_quotations': [
                {
                    'id': q.id,
                    'number': q.quotation_number,
                    'client': q.client.name if q.client else 'No Client',
                    'amount': float(q.grand_total),
                    'status': q.status,
                    'date': q.quotation_date.strftime('%Y-%m-%d')
                }
                for q in quotations.order_by('-created_at')[:5]
            ],
        })
    else:
        data.update({
            'total_quotations': 0, 'monthly_quotations': 0,
            'quotation_status_breakdown': {'pending': 0, 'accepted': 0, 'rejected': 0},
            'recent_quotations': [],
        })
    if can_view_waybill:
        data['total_waybills'] = total_waybills
        data['monthly_waybills'] = monthly_waybills
    else:
        data['total_waybills'] = 0
        data['monthly_waybills'] = 0
    if can_view_client:
        data['total_clients'] = total_clients
        data['new_clients_this_month'] = new_clients_this_month
    else:
        data['total_clients'] = 0
        data['new_clients_this_month'] = 0
    if can_view_inventory:
        data['total_inventory_items'] = total_inventory_items
        data['low_stock_items'] = low_stock_items
    else:
        data['total_inventory_items'] = 0
        data['low_stock_items'] = 0

    return JsonResponse({'success': True, 'data': data})


@login_required
@require_http_methods(["GET"])
def dashboard_charts_data(request):
    """Get data for dashboard charts. Only returns data user has permission to see."""
    company_profile = get_company_profile_for_user(request.user, request)
    if not company_profile:
        return JsonResponse({'error': 'Company profile not found'}, status=400)
    can_view_invoice = request.user.has_perm('invoices.view_invoice')
    can_view_quotation = request.user.has_perm('quotations.view_quotation')
    if not can_view_invoice and not can_view_quotation:
        return JsonResponse({
            'success': True,
            'data': {'monthly_data': []},
        })
    account_id = getattr(request.user, 'account_id', None)
    if not account_id:
        return JsonResponse({'success': True, 'data': {'monthly_data': []}})
    now = timezone.now()
    monthly_data = []
    for i in range(12):
        date = now - timedelta(days=30*i)
        month_start = datetime(date.year, date.month, 1).date()
        if date.month == 12:
            month_end = datetime(date.year + 1, 1, 1).date() - timedelta(days=1)
        else:
            month_end = datetime(date.year, date.month + 1, 1).date() - timedelta(days=1)
        month_revenue = 0
        month_invoice_count = 0
        month_quotations = 0
        if can_view_invoice:
            month_invoices = for_user_queryset(Invoice, request.user, request, account_lookup='account').filter(
                invoice_date__gte=month_start,
                invoice_date__lte=month_end
            )
            month_revenue = (month_invoices.aggregate(total=Sum('grand_total'))['total'] or 0)
            month_invoice_count = month_invoices.count()
        if can_view_quotation:
            month_quotations = for_user_queryset(Quotation, request.user, request, account_lookup='account').filter(
                quotation_date__gte=month_start,
                quotation_date__lte=month_end
            ).count()
        monthly_data.append({
            'month': date.strftime('%b %Y'),
            'month_num': date.month,
            'year': date.year,
            'revenue': float(month_revenue),
            'invoice_count': month_invoice_count,
            'quotation_count': month_quotations,
        })
    monthly_data.reverse()
    return JsonResponse({
        'success': True,
        'data': {'monthly_data': monthly_data},
    })


@login_required
@require_http_methods(["GET"])
def dashboard_quick_actions(request):
    """Get quick action suggestions based on current data"""
    company_profile = get_company_profile_for_user(request.user, request)
    if not company_profile:
        return JsonResponse({'error': 'Company profile not found'}, status=400)
    
    # Analyze current state and suggest actions
    suggestions = []
    
    # Check for overdue invoices (visibility-scoped)
    overdue_invoices = for_user_queryset(Invoice, request.user, request, account_lookup='account').filter(
        due_date__lt=timezone.now().date(),
        status__in=['unpaid', 'partial']
    ).count()
    
    if overdue_invoices > 0:
        suggestions.append({
            'type': 'urgent',
            'title': f'Follow up on {overdue_invoices} overdue invoices',
            'description': 'You have invoices that are past their due date',
            'action': 'invoices:list',
            'icon': 'warning'
        })
    
    # Check for pending quotations
    pending_quotations = for_user_queryset(Quotation, request.user, request, account_lookup='account').filter(
        status='pending'
    ).count()
    
    if pending_quotations > 0:
        suggestions.append({
            'type': 'info',
            'title': f'Review {pending_quotations} pending quotations',
            'description': 'Follow up on quotations to convert them to sales',
            'action': 'quotations:list',
            'icon': 'info'
        })
    
    # Check for low stock
    try:
        low_stock_items = _inventory_qs(request).filter(stock_status='low_stock').count()
        out_count = _inventory_qs(request).filter(stock_status='out_of_stock').count()
        low_stock_items += out_count
        if low_stock_items > 0:
            suggestions.append({
                'type': 'warning',
                'title': f'Restock {low_stock_items} low inventory items',
                'description': 'Some items are running low on stock',
                'action': 'inventory:list',
                'icon': 'inventory'
            })
    except Exception:
        pass
    
    # Check for new clients this month (visibility-scoped)
    new_clients = for_user_queryset(Client, request.user, request, account_lookup='company__account').filter(
        created_at__gte=timezone.now().replace(day=1).date()
    ).count()
    
    if new_clients == 0:
        suggestions.append({
            'type': 'success',
            'title': 'Add new clients to grow your business',
            'description': 'No new clients added this month',
            'action': 'clients:create',
            'icon': 'person_add'
        })
    
    # Default suggestions if no specific issues
    if not suggestions:
        suggestions = [
            {
                'type': 'success',
                'title': 'Create a new invoice',
                'description': 'Generate revenue by creating invoices',
                'action': 'invoices:create',
                'icon': 'receipt'
            },
            {
                'type': 'info',
                'title': 'Send a quotation',
                'description': 'Create quotations to win new business',
                'action': 'quotations:create',
                'icon': 'description'
            }
        ]
    
    return JsonResponse({
        'success': True,
        'data': {
            'suggestions': suggestions[:5]  # Limit to 5 suggestions
        }
    })


@login_required
@require_http_methods(["GET"])
def dashboard_tips(request):
    """Get dynamic business tips based on current data"""
    company_profile = get_company_profile_for_user(request.user, request)
    if not company_profile:
        return JsonResponse({'error': 'Company profile not found'}, status=400)
    
    # Get current business metrics (company-scoped)
    invoices = _invoice_qs(request)
    total_invoices = invoices.count()
    outstanding_amount = invoices.filter(
        status__in=['unpaid', 'partial']
    ).aggregate(total=Sum('balance_due'))['total'] or 0
    
    # Generate contextual tips
    tips = []
    
    if total_invoices == 0:
        tips.append("Start by creating your first invoice to begin tracking revenue!")
    elif total_invoices < 5:
        tips.append("Great start! Consider setting up invoice templates to speed up your workflow.")
    elif outstanding_amount > 1000:
        tips.append("Follow up on outstanding invoices to improve your cash flow.")
    else:
        tips.append("Your business is running smoothly! Consider expanding your client base.")
    
    # Add general business tips
    general_tips = [
        "Set up automated invoice reminders to get paid faster.",
        "Use clear, professional descriptions in your invoices to avoid payment delays.",
        "Include your payment terms prominently to set clear expectations.",
        "Send invoices within 24 hours of completing work for the best results.",
        "Consider offering early payment discounts to encourage faster payments.",
        "Keep track of your most profitable services and focus on those.",
        "Regular follow-ups on outstanding invoices can improve your collection rate by 40%!",
        "Use professional invoice templates to impress clients and get paid faster.",
        "Set aside time weekly to review your finances and business performance.",
        "Build strong relationships with your best clients for repeat business."
    ]
    
    # Add a random general tip
    import random
    tips.append(random.choice(general_tips))
    
    return JsonResponse({
        'success': True,
        'data': {
            'tips': tips
        }
    })


@login_required
@require_http_methods(["GET"])
def dashboard_realtime_updates(request):
    """Get real-time dashboard updates with WebSocket support"""
    company_profile = get_company_profile_for_user(request.user, request)
    if not company_profile:
        return JsonResponse({'error': 'Company profile not found'}, status=400)
    
    invoices = _invoice_qs(request)
    quotations = _quotation_qs(request)
    
    # Get timestamp of last update
    last_update = request.GET.get('last_update')
    
    # Get current time
    now = timezone.now()
    
    # Check for new data since last update
    updates = {}
    
    # Check for new invoices
    if last_update:
        try:
            last_update_dt = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
            new_invoices = invoices.filter(created_at__gt=last_update_dt).count()
            if new_invoices > 0:
                updates['new_invoices'] = new_invoices
        except Exception:
            pass
    
    # Check for new quotations
    if last_update:
        try:
            last_update_dt = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
            new_quotations = quotations.filter(created_at__gt=last_update_dt).count()
            if new_quotations > 0:
                updates['new_quotations'] = new_quotations
        except Exception:
            pass
    
    # Check for status changes
    if last_update:
        try:
            last_update_dt = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
            updated_invoices = invoices.filter(updated_at__gt=last_update_dt).count()
            if updated_invoices > 0:
                updates['updated_invoices'] = updated_invoices
        except Exception:
            pass
    
    # Get current statistics for comparison (company-scoped)
    current_stats = {
        'total_invoices': invoices.count(),
        'total_quotations': quotations.count(),
        'outstanding_invoices': invoices.filter(
            status__in=['unpaid', 'partial']
        ).aggregate(total=Sum('balance_due'))['total'] or 0,
    }
    
    return JsonResponse({
        'success': True,
        'data': {
            'updates': updates,
            'current_stats': current_stats,
            'timestamp': now.isoformat(),
            'has_updates': len(updates) > 0
        }
    })


@login_required
@require_http_methods(["GET"])
def dashboard_notifications(request):
    """Get real-time notifications and alerts"""
    company_profile = get_company_profile_for_user(request.user, request)
    if not company_profile:
        return JsonResponse({'error': 'Company profile not found'}, status=400)
    
    notifications = []
    
    # Check for overdue invoices (visibility-scoped)
    overdue_invoices = for_user_queryset(Invoice, request.user, request, account_lookup='account').filter(
        due_date__lt=timezone.now().date(),
        status__in=['unpaid', 'partial']
    )
    
    for invoice in overdue_invoices[:5]:  # Limit to 5 most recent
        days_overdue = (timezone.now().date() - invoice.due_date).days
        notifications.append({
            'type': 'warning',
            'title': f'Overdue Invoice: {invoice.invoice_number}',
            'message': f'Invoice is {days_overdue} days overdue. Amount: {company_profile.currency_symbol}{invoice.balance_due}',
            'action_url': f'/invoices/{invoice.id}/',
            'timestamp': invoice.due_date.isoformat(),
            'priority': 'high' if days_overdue > 30 else 'medium'
        })
    
    # Check for low stock items
    try:
        low_stock_items = _inventory_qs(request).filter(
            Q(stock_status='low_stock') | Q(stock_status='out_of_stock')
        )[:5]
        for item in low_stock_items:
            notifications.append({
                'type': 'info',
                'title': f'Low Stock Alert: {item.product_name}',
                'message': f'Stock is running low. Balance quantity: {item.balance_quantity}',
                'action_url': f'/inventory/detail/{item.id}/',
                'timestamp': item.updated_at.isoformat(),
                'priority': 'medium'
            })
    except Exception:
        pass
    
    # Check for pending quotations that need follow-up
    pending_quotations = for_user_queryset(Quotation, request.user, request, account_lookup='account').filter(
        status='pending',
        quotation_date__lt=timezone.now().date() - timedelta(days=7)
    )[:5]
    
    for quotation in pending_quotations:
        days_pending = (timezone.now().date() - quotation.quotation_date).days
        notifications.append({
            'type': 'info',
            'title': f'Follow-up Needed: {quotation.quotation_number}',
            'message': f'Quotation has been pending for {days_pending} days',
            'action_url': f'/quotations/{quotation.id}/',
            'timestamp': quotation.quotation_date.isoformat(),
            'priority': 'low'
        })

    # HR & Staff: pending leave requests (for users with HR access)
    if request.user.has_perm('hr_staff.view_hr_dashboard') or request.user.has_perm('hr_staff.view_employee') or request.user.has_perm('hr_staff.view_own_hr_dashboard'):
        try:
            from apps.hr_staff.querysets import get_leave_queryset_for_user
            pending_leaves = get_leave_queryset_for_user(
                request.user, request, account_lookup='account'
            ).filter(status='pending').select_related('employee').order_by('-created_at')[:5]
            for leave in pending_leaves:
                notifications.append({
                    'type': 'info',
                    'title': 'Pending Leave Request',
                    'message': f'{leave.employee.full_name} – {leave.get_leave_type_display()} ({leave.start_date} to {leave.end_date})',
                    'action_url': f'/hr-staff/leave/{leave.id}/',
                    'timestamp': leave.created_at.isoformat() if leave.created_at else timezone.now().isoformat(),
                    'priority': 'medium'
                })
        except Exception:
            pass

    # Sort notifications by priority and timestamp
    priority_order = {'high': 3, 'medium': 2, 'low': 1}
    notifications.sort(key=lambda x: (priority_order.get(x['priority'], 0), x['timestamp']), reverse=True)
    
    return JsonResponse({
        'success': True,
        'data': {
            'notifications': notifications[:10],  # Limit to 10 notifications
            'unread_count': len([n for n in notifications if n['priority'] == 'high'])
        }
    })


@login_required
@require_http_methods(["GET"])
def dashboard_activity_feed(request):
    """Get real-time activity feed"""
    company_profile = get_company_profile_for_user(request.user, request)
    if not company_profile:
        return JsonResponse({'error': 'Company profile not found'}, status=400)
    
    # Get recent activities from different modules
    activities = []
    
    # Recent invoices (visibility-scoped)
    recent_invoices = for_user_queryset(Invoice, request.user, request, account_lookup='account').order_by('-created_at')[:5]
    
    for invoice in recent_invoices:
        activities.append({
            'id': invoice.id,
            'type': 'invoice',
            'action': 'created',
            'title': f'New Invoice Created',
            'description': f'Invoice {invoice.invoice_number} for {invoice.client_name}',
            'amount': float(invoice.grand_total),
            'timestamp': invoice.created_at.isoformat(),
            'icon': 'receipt',
            'color': 'primary'
        })
    
    # Recent quotations
    recent_quotations = for_user_queryset(Quotation, request.user, request, account_lookup='account').order_by('-created_at')[:5]
    
    for quotation in recent_quotations:
        activities.append({
            'id': quotation.id,
            'type': 'quotation',
            'action': 'created',
            'title': f'New Quotation Created',
            'description': f'Quotation {quotation.quotation_number} for {quotation.client.name if quotation.client else "No Client"}',
            'amount': float(quotation.grand_total),
            'timestamp': quotation.created_at.isoformat(),
            'icon': 'description',
            'color': 'success'
        })
    
    # Recent waybills
    recent_waybills = for_user_queryset(Waybill, request.user, request, account_lookup='account').order_by('-created_at')[:5]
    
    for waybill in recent_waybills:
        activities.append({
            'id': waybill.id,
            'type': 'waybill',
            'action': 'created',
            'title': f'New Waybill Created',
            'description': f'Waybill {waybill.waybill_number}',
            'amount': float(waybill.grand_total) if hasattr(waybill, 'grand_total') else 0,
            'timestamp': waybill.created_at.isoformat(),
            'icon': 'local_shipping',
            'color': 'warning'
        })
    
    # Recent clients (visibility-scoped)
    recent_clients = for_user_queryset(Client, request.user, request, account_lookup='company__account').order_by('-created_at')[:5]
    
    for client in recent_clients:
        activities.append({
            'id': client.id,
            'type': 'client',
            'action': 'created',
            'title': f'New Client Added',
            'description': f'Client {client.name} added to the system',
            'amount': None,
            'timestamp': client.created_at.isoformat(),
            'icon': 'person_add',
            'color': 'info'
        })
    
    # Sort all activities by timestamp
    activities.sort(key=lambda x: x['timestamp'], reverse=True)
    
    return JsonResponse({
        'success': True,
        'data': {
            'activities': activities[:20],  # Limit to 20 activities
            'total_activities': len(activities)
        }
    })


@login_required
@require_http_methods(["GET"])
def dashboard_inventory_alerts(request):
    """Get real-time inventory alerts and notifications"""
    company_profile = get_company_profile_for_user(request.user, request)
    if not company_profile:
        return JsonResponse({'error': 'Company profile not found'}, status=400)
    
    alerts = []
    
    try:
        inv_qs = _inventory_qs(request)
        low_stock_items = inv_qs.filter(stock_status='low_stock')
        for item in low_stock_items[:5]:
            alerts.append({
                'type': 'warning',
                'title': f'Low Stock Alert: {item.product_name}',
                'message': f'Stock is running low. Balance quantity: {item.balance_quantity}',
                'action_url': f'/inventory/detail/{item.id}/',
                'timestamp': item.updated_at.isoformat(),
                'priority': 'high' if item.balance_quantity <= 2 else 'medium',
                'item_id': item.id,
                'current_quantity': float(item.balance_quantity),
                'threshold': 5
            })
        out_of_stock_items = inv_qs.filter(stock_status='out_of_stock')
        for item in out_of_stock_items[:5]:
            alerts.append({
                'type': 'error',
                'title': f'Out of Stock: {item.product_name}',
                'message': 'This item is completely out of stock',
                'action_url': f'/inventory/detail/{item.id}/',
                'timestamp': item.updated_at.isoformat(),
                'priority': 'high',
                'item_id': item.id,
                'current_quantity': 0,
                'threshold': 0
            })
        from datetime import timedelta
        stale_threshold = timezone.now() - timedelta(days=30)
        stale_items = inv_qs.filter(updated_at__lt=stale_threshold)[:5]
        for item in stale_items:
            days_since_update = (timezone.now() - item.updated_at).days
            alerts.append({
                'type': 'info',
                'title': f'Stale Inventory: {item.product_name}',
                'message': f'This item hasn\'t been updated in {days_since_update} days',
                'action_url': f'/inventory/detail/{item.id}/',
                'timestamp': item.updated_at.isoformat(),
                'priority': 'low',
                'item_id': item.id,
                'days_since_update': days_since_update
            })
        
    except Exception as e:
        # If inventory app is not available, return empty alerts
        pass
    
    # Sort alerts by priority and timestamp
    priority_order = {'high': 3, 'medium': 2, 'low': 1}
    alerts.sort(key=lambda x: (priority_order.get(x['priority'], 0), x['timestamp']), reverse=True)
    
    return JsonResponse({
        'success': True,
        'data': {
            'alerts': alerts[:10],  # Limit to 10 alerts
            'total_alerts': len(alerts),
            'high_priority_count': len([a for a in alerts if a['priority'] == 'high'])
        }
    })


@login_required
@require_http_methods(["GET"])
def dashboard_system_health(request):
    """Get system health and performance metrics"""
    company_profile = get_company_profile_for_user(request.user, request)
    if not company_profile:
        return JsonResponse({'error': 'Company profile not found'}, status=400)
    
    # Calculate system health metrics
    health_metrics = {}
    
    # Database health
    try:
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        health_metrics['database'] = 'healthy'
    except:
        health_metrics['database'] = 'unhealthy'
    
    # Check for recent errors in logs
    try:
        import os
        log_file = os.path.join(settings.BASE_DIR, 'logs', 'django.log')
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                lines = f.readlines()
                recent_errors = [line for line in lines[-100:] if 'ERROR' in line]
                health_metrics['recent_errors'] = len(recent_errors)
        else:
            health_metrics['recent_errors'] = 0
    except:
        health_metrics['recent_errors'] = 0
    
    # Check data consistency (visibility-scoped)
    try:
        inv_qs = for_user_queryset(Invoice, request.user, request, account_lookup='account')
        orphaned_invoices = inv_qs.filter(
            Q(client_name__isnull=True) | Q(client_name='')
        ).count()
        health_metrics['orphaned_invoices'] = orphaned_invoices
        
        incomplete_invoices = inv_qs.filter(
            Q(invoice_number__isnull=True) | Q(invoice_number='')
        ).count()
        health_metrics['incomplete_invoices'] = incomplete_invoices
        
    except:
        health_metrics['orphaned_invoices'] = 0
        health_metrics['incomplete_invoices'] = 0
    
    # Overall health score
    health_score = 100
    if health_metrics['database'] != 'healthy':
        health_score -= 50
    if health_metrics['recent_errors'] > 10:
        health_score -= 20
    if health_metrics['orphaned_invoices'] > 0:
        health_score -= 10
    if health_metrics['incomplete_invoices'] > 0:
        health_score -= 10
    
    health_metrics['overall_score'] = max(0, health_score)
    
    return JsonResponse({
        'success': True,
        'data': {
            'health_metrics': health_metrics,
            'timestamp': timezone.now().isoformat()
        }
    })


@login_required
@require_http_methods(["GET"])
def num2words_api(request):
    """Convert numbers to words for amount display"""
    amount = request.GET.get('amount', '0')
    currency = request.GET.get('currency', 'USD')
    
    try:
        # Convert amount to decimal
        amount_decimal = Decimal(str(amount))
        
        # Convert to words
        words = number_to_words(amount_decimal, currency)
        
        return JsonResponse({
            'success': True,
            'words': words,
            'amount': str(amount_decimal),
            'currency': currency
        })
        
    except (ValueError, TypeError) as e:
        return JsonResponse({
            'success': False,
            'error': 'Invalid amount provided',
            'words': 'Zero'
        }, status=400)


# number_to_words is imported from apps.core.utils (supports trillion+)


@login_required
@require_http_methods(["GET"])
def currency_status(request):
    """Get current currency status for real-time updates"""
    try:
        company_context = get_company_context(request.user, request)
        return JsonResponse({
            'success': True,
            'currency_symbol': company_context['currency_symbol'],
            'currency_code': company_context['currency_code'],
            'timestamp': timezone.now().isoformat()
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


@login_required
@require_http_methods(["GET"])
@never_cache
def api_ping(request):
    """Lightweight connectivity check for the connection status indicator. Returns 200 when server is reachable."""
    return JsonResponse({"ok": True})


def my_ip(request):
    """Return the client IP as seen by the server. Useful for debugging IP/location issues."""
    from apps.accounts.security_utils import get_client_ip, get_ip_geolocation
    ip = get_client_ip(request)
    loc = get_ip_geolocation(ip) if ip else {}
    return JsonResponse({
        'ip': ip,
        'remote_addr': request.META.get('REMOTE_ADDR'),
        'x_forwarded_for': request.META.get('HTTP_X_FORWARDED_FOR'),
        'x_real_ip': request.META.get('HTTP_X_REAL_IP'),
        'cf_connecting_ip': request.META.get('HTTP_CF_CONNECTING_IP'),
        'location': f"{loc.get('city', '')}, {loc.get('region', '')} {loc.get('country', '')}".strip(', ') or None,
        'city': loc.get('city'),
        'country': loc.get('country'),
        'isp': loc.get('isp'),
    })


@login_required
@require_http_methods(["GET"])
@never_cache
def debug_session(request):
    """
    Diagnostic endpoint for live server: session/cookie/HTTPS check.
    Open when logged in: /dashboard/api/debug-session/
    Remove or restrict in production after debugging.
    """
    from django.urls import reverse
    session_has_key = bool(getattr(request.session, 'session_key', None))
    data = {
        'ok': True,
        'is_secure': request.is_secure(),
        'host': request.get_host(),
        'session_has_key': session_has_key,
        'user_authenticated': request.user.is_authenticated,
        'session_cookie_secure': getattr(settings, 'SESSION_COOKIE_SECURE', None),
        'csrf_cookie_secure': getattr(settings, 'CSRF_COOKIE_SECURE', None),
        'notification_api_url': request.build_absolute_uri(reverse('notifications:api_list')),
        'hint': 'If is_secure is False on HTTPS site, set SECURE_PROXY_SSL_HEADER in settings. If session_has_key is False, cookies are not being sent or are wrong.',
    }
    return JsonResponse(data)