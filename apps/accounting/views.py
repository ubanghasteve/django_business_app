from django.shortcuts import render, redirect, get_object_or_404
from business_app.views import get_object_or_unauthorized
from django.contrib.auth.decorators import login_required, permission_required
from apps.core.permissions import company_admin_or_permission_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.core.paginator import Paginator
from django.db.models import Sum, Q, Count, Min, Max
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.template.loader import render_to_string
from django.urls import reverse
from datetime import datetime, timedelta
import json
import csv
from decimal import Decimal
import re

from .models import (
    Transaction,
    Ledger,
    Account,
    FinancialReport,
    ChartOfAccount,
    JournalEntry,
    LedgerEntry,
)
from .forms import (
    TransactionForm,
    TransactionFilterForm,
    AccountForm,
    FinancialReportForm,
    BulkTransactionForm,
    ReconciliationForm,
    ImportTransactionForm,
    ChartOfAccountForm,
    JournalEntryForm,
)
from .serializers import (
    ChartOfAccountSerializer,
    JournalEntrySerializer,
    LedgerEntrySerializer,
    TransactionSerializer,
)
from .services import (
    create_journal_entry,
    calculate_trial_balance as de_calculate_trial_balance,
    generate_profit_loss as de_generate_profit_loss,
    generate_balance_sheet as de_generate_balance_sheet,
)
from apps.core.models import CompanyProfile
from apps.core.utils import get_company_profile_for_user
from apps.core.ownership import for_user_queryset, is_company_admin

def get_currency_display(currency_symbol):
    """Convert currency symbol to display text for better compatibility"""
    if not currency_symbol:
        return 'NGN'
    currency_symbol = currency_symbol.strip()
    currency_mapping = {
        '₦': 'NGN',
        '$': 'USD',
        '€': 'EUR',
        '£': 'GBP',
        '¥': 'JPY',
        '₹': 'INR',
        '₽': 'RUB',
        '₩': 'KRW',
        '₪': 'ILS',
        '₨': 'PKR',
        '₴': 'UAH',
        '₸': 'KZT',
        '₺': 'TRY',
        '₼': 'AZN',
        '₾': 'GEL',
        '₿': 'BTC',
    }
    return currency_mapping.get(currency_symbol, currency_symbol)


def clean_transaction_text(text):
    """Clean transaction text by removing HTML tags and special characters"""
    if not text:
        return ""
    
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', str(text))
    
    # Replace common HTML entities
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&quot;', '"')
    text = text.replace('&#39;', "'")
    
    # Clean up multiple spaces and newlines
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    
    return text


def get_pdf_currency_symbol(currency_symbol, use_symbol=True):
    """Convert currency symbol to PDF-compatible format"""
    if not currency_symbol or currency_symbol.strip() == '':
        return 'NGN '  # Default fallback with space
    
    # Clean the symbol
    currency_symbol = currency_symbol.strip()
    
    # If use_symbol is True, try to use the actual symbol first
    if use_symbol:
        # For common symbols that usually work well in PDFs
        if currency_symbol in ['$', '€', '£', '¥']:
            return f"{currency_symbol} "
        
        # For Naira symbol, try the actual symbol first
        if currency_symbol == '₦':
            try:
                # Test if the symbol can be properly encoded
                test_str = f"{currency_symbol}1000.00"
                test_str.encode('utf-8')
                return f"{currency_symbol} "
            except UnicodeEncodeError:
                pass  # Fall through to text representation
        
        # For other symbols, try them with a space
        try:
            # Test if the symbol can be properly encoded
            test_str = f"{currency_symbol}1000.00"
            test_str.encode('utf-8')
            return f"{currency_symbol} "
        except UnicodeEncodeError:
            pass  # Fall through to text representation
    
    # Use text representations for better compatibility
    currency_mapping = {
        '₦': 'NGN ',  # Naira - use code instead of symbol with space
        '$': '$',     # Dollar - works well
        '€': 'EUR ',  # Euro - use code instead of symbol with space
        '£': 'GBP ',  # Pound - use code instead of symbol with space
        '¥': 'JPY ',  # Yen - use code instead of symbol with space
        '₹': 'INR ',  # Rupee - use code instead of symbol with space
        '₽': 'RUB ',  # Ruble - use code instead of symbol with space
        '₩': 'KRW ',  # Won - use code instead of symbol with space
        '₪': 'ILS ',  # Shekel - use code instead of symbol with space
        '₨': 'PKR ',  # Rupee (Pakistani) - use code instead of symbol with space
        '₴': 'UAH ',  # Hryvnia - use code instead of symbol with space
        '₸': 'KZT ',  # Tenge - use code instead of symbol with space
        '₺': 'TRY ',  # Lira - use code instead of symbol with space
        '₼': 'AZN ',  # Manat - use code instead of symbol with space
        '₾': 'GEL ',  # Lari - use code instead of symbol with space
        '₿': 'BTC ',  # Bitcoin - use code instead of symbol with space
    }
    
    # If the symbol is in our mapping, use the text representation
    if currency_symbol in currency_mapping:
        return currency_mapping[currency_symbol]
    
    # For currency codes (like 'USD', 'EUR', etc.), add a space for readability
    if len(currency_symbol) == 3 and currency_symbol.isupper():
        return f"{currency_symbol} "
    
    # For unknown symbols, try to use them directly with a space
    try:
        # Test if the symbol can be properly encoded
        test_str = f"{currency_symbol}1000.00"
        test_str.encode('utf-8')
        # For safety, use a space after the symbol
        return f"{currency_symbol} "
    except UnicodeEncodeError:
        # If encoding fails, use a text fallback
        return f"{currency_symbol} "  # Add space for readability


def sync_ledgers_from_transactions(company):
    """Sync ledgers from existing transactions for all months"""
    
    # Get date range of transactions
    date_range = Transaction.objects.filter(
        company=company,
        is_void=False,
        is_deleted=False
    ).aggregate(
        min_date=Min('transaction_date'),
        max_date=Max('transaction_date')
    )
    
    if not date_range['min_date'] or not date_range['max_date']:
        return
    
    # Create ledgers for each month in the range
    current_date = date_range['min_date'].replace(day=1)
    end_date = date_range['max_date'].replace(day=1)
    
    while current_date <= end_date:
        # Check if ledger exists for this month
        existing_ledger = Ledger.objects.filter(
            company=company,
            year=current_date.year,
            month=current_date.month
        ).first()
        
        if not existing_ledger:
            # Calculate totals from transactions
            month_transactions = Transaction.objects.filter(
                company=company,
                transaction_date__year=current_date.year,
                transaction_date__month=current_date.month,
                is_void=False,
                is_deleted=False
            )
            
            total_income = month_transactions.filter(type='income').aggregate(
                total=Sum('net_amount')
            )['total'] or 0
            
            total_expense = month_transactions.filter(type='expense').aggregate(
                total=Sum('net_amount')
            )['total'] or 0
            
            net_profit = total_income - total_expense
            
            # Create ledger
            Ledger.objects.create(
                company=company,
                year=current_date.year,
                month=current_date.month,
                total_income=total_income,
                total_expense=total_expense,
                net_profit=net_profit
            )
        
        # Move to next month
        if current_date.month == 12:
            current_date = current_date.replace(year=current_date.year + 1, month=1)
        else:
            current_date = current_date.replace(month=current_date.month + 1)


@login_required
@company_admin_or_permission_required('accounting.view_transaction', raise_exception=True)
def accounting_dashboard(request):
    """Main accounting dashboard with charts and summary - Staff only"""
    user = request.user
    company = get_company_profile_for_user(user, request)
    
    if not company:
        messages.error(request, "Company profile not found. Please set up your company profile first.")
        return redirect('core:company_profile')
    
    # Sync ledgers from existing transactions
    sync_ledgers_from_transactions(company)
    
    # Get current month/year
    current_date = timezone.now()
    current_month = current_date.month
    current_year = current_date.year
    
    # Get current month ledger
    current_ledger = Ledger.objects.filter(
        company=company,
        year=current_year,
        month=current_month
    ).first()
    
    # Create a default ledger if none exists
    if not current_ledger:
        current_ledger = type('obj', (object,), {
            'total_income': 0,
            'total_expense': 0,
            'net_profit': 0
        })()
    
    # Visibility-scoped transaction queryset for dashboard (exclude void and soft-deleted from offline sync)
    txn_qs = for_user_queryset(Transaction, request.user, request, account_lookup='company__account').filter(is_void=False, is_deleted=False)
    recent_transactions = txn_qs.order_by('-created_at')[:10]
    
    # Get monthly data for charts (last 12 months) - improved with real transaction data
    monthly_data = []
    for i in range(12):
        date = current_date - timedelta(days=30*i)
        
        # Get or create ledger for this month
        month_ledger = Ledger.objects.filter(
            company=company,
            year=date.year,
            month=date.month
        ).first()
        
        # If no ledger exists, calculate from actual transactions (visibility-scoped)
        if not month_ledger:
            month_transactions = txn_qs.filter(
                transaction_date__year=date.year,
                transaction_date__month=date.month,
            )
            
            month_income = month_transactions.filter(type='income').aggregate(
                total=Sum('net_amount')
            )['total'] or 0
            
            month_expense = month_transactions.filter(type='expense').aggregate(
                total=Sum('net_amount')
            )['total'] or 0
            
            month_profit = month_income - month_expense
        else:
            month_income = float(month_ledger.total_income)
            month_expense = float(month_ledger.total_expense)
            month_profit = float(month_ledger.net_profit)
        
        monthly_data.append({
            'month': date.strftime('%b %Y'),
            'year': date.year,
            'month_num': date.month,
            'income': month_income,
            'expense': month_expense,
            'profit': month_profit,
        })
    
    # Get outstanding invoices (company-scoped so team sees same as owner)
    from apps.invoices.models import Invoice
    account_id = getattr(user, 'account_id', None)
    if account_id:
        outstanding_invoices = Invoice.objects.filter(
            user__account_id=account_id,
            status__in=['unpaid', 'partial']
        ).aggregate(total=Sum('balance_due'))['total'] or 0
    else:
        outstanding_invoices = Invoice.objects.filter(
            user=user,
            status__in=['unpaid', 'partial']
        ).aggregate(total=Sum('balance_due'))['total'] or 0
    
    # Get today's transactions (visibility-scoped)
    today_transactions = txn_qs.filter(transaction_date=current_date.date())
    
    today_income = today_transactions.filter(type='income').aggregate(
        total=Sum('net_amount')
    )['total'] or 0
    
    today_expense = today_transactions.filter(type='expense').aggregate(
        total=Sum('net_amount')
    )['total'] or 0
    
    # If no transactions today, use recent transactions for demonstration (visibility-scoped)
    if today_income == 0 and today_expense == 0:
        recent_income = txn_qs.filter(type='income').order_by('-transaction_date')[:3].aggregate(
            total=Sum('net_amount')
        )['total'] or 0
        recent_expense = txn_qs.filter(type='expense').order_by('-transaction_date')[:3].aggregate(
            total=Sum('net_amount')
        )['total'] or 0
        
        today_income = recent_income
        today_expense = recent_expense
    
    # Get source app breakdown (visibility-scoped)
    source_breakdown = list(txn_qs.values('source_app').annotate(
        total=Sum('net_amount'),
        count=Count('id')
    ).order_by('-total'))
    
    # Convert Decimal values to float for JSON serialization
    for item in source_breakdown:
        item['total'] = float(item['total'])
    
    context = {
        'current_ledger': current_ledger,
        'recent_transactions': recent_transactions,
        'monthly_data': list(reversed(monthly_data)),  # Reverse for chronological order
        'outstanding_invoices': float(outstanding_invoices),
        'today_income': float(today_income),
        'today_expense': float(today_expense),
        'source_breakdown': source_breakdown,
        'current_month': current_month,
        'current_year': current_year,
        'has_real_data': any(item['income'] > 0 or item['expense'] > 0 for item in monthly_data),
        'company_profile': company,  # Add company profile for currency formatting
    }
    
    return render(request, 'accounting/dashboard.html', context)


@login_required
@company_admin_or_permission_required('accounting.view_transaction', raise_exception=True)
def transaction_list(request):
    """List all transactions with filtering and pagination"""
    try:
        user = request.user
        company = get_company_profile_for_user(user, request)
        
        if not company:
            messages.error(request, "Company profile not found.")
            return redirect('core:company_profile')
        
        # Get filter form
        filter_form = TransactionFilterForm(request.GET)
        
        # Base queryset (visibility-scoped: admin sees all, team sees own). Exclude void and soft-deleted (offline sync).
        transactions = for_user_queryset(
            Transaction, request.user, request, account_lookup='company__account'
        ).filter(is_void=False, is_deleted=False).select_related('created_by')
        
        from apps.core.utils import get_account_users_for_filter
        if is_company_admin(request.user, request):
            filter_form.fields['created_by'].queryset = get_account_users_for_filter(request.user)
        # Apply filters
        if filter_form.is_valid():
            data = filter_form.cleaned_data
            if is_company_admin(request.user, request) and data.get('created_by'):
                transactions = transactions.filter(created_by=data['created_by'])
            
            if data.get('start_date'):
                transactions = transactions.filter(transaction_date__gte=data['start_date'])
            
            if data.get('end_date'):
                transactions = transactions.filter(transaction_date__lte=data['end_date'])
            
            if data.get('transaction_type'):
                transactions = transactions.filter(type=data['transaction_type'])
            
            if data.get('source_app'):
                transactions = transactions.filter(source_app=data['source_app'])
            
            if data.get('min_amount'):
                transactions = transactions.filter(net_amount__gte=data['min_amount'])
            
            if data.get('max_amount'):
                transactions = transactions.filter(net_amount__lte=data['max_amount'])
            
            if data.get('search'):
                search_term = data['search']
                transactions = transactions.filter(
                    Q(title__icontains=search_term) |
                    Q(description__icontains=search_term) |
                    Q(notes__icontains=search_term)
                )
            
            if data.get('is_reconciled'):
                is_reconciled = data['is_reconciled'] == 'true'
                transactions = transactions.filter(is_reconciled=is_reconciled)
        
        # Order by date
        transactions = transactions.order_by('-transaction_date', '-created_at')
        
        # Pagination
        paginator = Paginator(transactions, 25)
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)
        
        # Summary totals - calculate on filtered data
        total_income = transactions.filter(type='income').aggregate(
            total=Sum('net_amount')
        )['total'] or 0
        
        total_expense = transactions.filter(type='expense').aggregate(
            total=Sum('net_amount')
        )['total'] or 0
        
        net_total = total_income - total_expense
        
        # Get total count for pagination info
        total_count = transactions.count()
        
        context = {
            'page_obj': page_obj,
            'filter_form': filter_form,
            'total_income': total_income,
            'total_expense': total_expense,
            'net_total': net_total,
            'total_count': total_count,
        }
        
        return render(request, 'accounting/transactions.html', context)
        
    except Exception as e:
        messages.error(request, f"An error occurred while loading transactions: {str(e)}")
        return redirect('accounting:dashboard')


@login_required
@company_admin_or_permission_required('accounting.add_transaction', raise_exception=True)
def add_transaction(request):
    """Add a new transaction"""
    user = request.user
    company = get_company_profile_for_user(user, request)
    
    if not company:
        messages.error(request, "Company profile not found.")
        return redirect('core:company_profile')
    
    if request.method == 'POST':
        form = TransactionForm(request.POST, user=user)
        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.user = user
            transaction.company = company
            transaction.created_by = user
            transaction.source_app = 'manual'
            transaction.save()
            
            messages.success(request, f"Transaction '{transaction.title}' added successfully.")
            return redirect('accounting:transaction_list')
    else:
        form = TransactionForm(user=user)
    
    context = {
        'form': form,
        'title': 'Add Transaction',
    }
    
    return render(request, 'accounting/transaction_form.html', context)


@login_required
@company_admin_or_permission_required('accounting.change_transaction', raise_exception=True)
def edit_transaction(request, transaction_id):
    """Edit an existing transaction"""
    user = request.user
    company = get_company_profile_for_user(user, request)
    
    if not company:
        messages.error(request, "Company profile not found.")
        return redirect('core:company_profile')
    
    qs = for_user_queryset(Transaction, request.user, request, account_lookup='company__account')
    transaction, response = get_object_or_unauthorized(request, qs, id=transaction_id)
    if response:
        return response
    if request.method == 'POST':
        form = TransactionForm(request.POST, instance=transaction, user=user)
        if form.is_valid():
            form.save()
            messages.success(request, f"Transaction '{transaction.title}' updated successfully.")
            return redirect('accounting:transaction_list')
    else:
        form = TransactionForm(instance=transaction, user=user)
    
    context = {
        'form': form,
        'transaction': transaction,
        'title': 'Edit Transaction',
    }
    
    return render(request, 'accounting/transaction_form.html', context)


@login_required
@company_admin_or_permission_required('accounting.delete_transaction', raise_exception=True)
def delete_transaction(request, transaction_id):
    """Delete a transaction (mark as void)"""
    user = request.user
    company = get_company_profile_for_user(user, request)
    
    if not company:
        messages.error(request, "Company profile not found.")
        return redirect('core:company_profile')
    
    qs = for_user_queryset(Transaction, request.user, request, account_lookup='company__account')
    transaction, response = get_object_or_unauthorized(request, qs, id=transaction_id)
    if response:
        return response
    if request.method == 'POST':
        transaction.is_void = True
        transaction.save()
        messages.success(request, f"Transaction '{transaction.title}' has been voided.")
        return redirect('accounting:transaction_list')
    
    context = {
        'transaction': transaction,
    }
    
    return render(request, 'accounting/transaction_confirm_delete.html', context)


@login_required
@company_admin_or_permission_required('accounting.change_transaction', raise_exception=True)
@require_POST
@csrf_exempt
def reconcile_transaction(request, transaction_id):
    """Mark a transaction as reconciled"""
    try:
        user = request.user
        company = get_company_profile_for_user(user, request)
        
        if not company:
            return JsonResponse({'success': False, 'error': 'Company profile not found'}, status=400)
        
        qs = for_user_queryset(Transaction, request.user, request, account_lookup='company__account')
        transaction, response = get_object_or_unauthorized(request, qs, id=transaction_id)
        if response:
            return response
        transaction.is_reconciled = True
        transaction.save()
        
        return JsonResponse({'success': True, 'message': 'Transaction marked as reconciled'})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@company_admin_or_permission_required('accounting.change_transaction', raise_exception=True)
@require_POST
@csrf_exempt
def unreconcile_transaction(request, transaction_id):
    """Mark a transaction as not reconciled"""
    try:
        user = request.user
        company = get_company_profile_for_user(user, request)
        
        if not company:
            return JsonResponse({'success': False, 'error': 'Company profile not found'}, status=400)
        
        qs = for_user_queryset(Transaction, request.user, request, account_lookup='company__account')
        transaction, response = get_object_or_unauthorized(request, qs, id=transaction_id)
        if response:
            return response
        transaction.is_reconciled = False
        transaction.save()
        
        return JsonResponse({'success': True, 'message': 'Transaction marked as not reconciled'})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@company_admin_or_permission_required('accounting.view_transaction', raise_exception=True)
def ledger_summary(request):
    """Show ledger summary by month/year"""
    user = request.user
    company = get_company_profile_for_user(user, request)
    
    if not company:
        messages.error(request, "Company profile not found.")
        return redirect('core:company_profile')
    
    # Get year filter
    selected_year = request.GET.get('year', timezone.now().year)
    
    # Get ledgers for the selected year
    ledgers = Ledger.objects.filter(
        company=company,
        year=selected_year
    ).order_by('month')
    
    # Get available years
    available_years = Ledger.objects.filter(
        company=company
    ).values_list('year', flat=True).distinct().order_by('-year')
    
    # Get company currency
    company_currency = getattr(company, 'currency_symbol', '₦')
    
    # Add currency information to ledgers
    for ledger in ledgers:
        ledger.currency_symbol = company_currency
    
    # Calculate yearly totals
    yearly_totals = {
        'total_income': sum(ledger.total_income for ledger in ledgers),
        'total_expense': sum(ledger.total_expense for ledger in ledgers),
        'net_profit': sum(ledger.net_profit for ledger in ledgers),
        'currency_symbol': company_currency,
    }
    
    context = {
        'ledgers': ledgers,
        'yearly_totals': yearly_totals,
        'selected_year': int(selected_year),
        'available_years': available_years,
    }
    
    return render(request, 'accounting/ledger_summary.html', context)


@login_required
@company_admin_or_permission_required('accounting.view_transaction', raise_exception=True)
def api_ledger_summary(request):
    """
    JSON endpoint for ledger summary by year.

    Query params:
      - year (int, optional; defaults to current year)

    Returns:
    {
      "year": 2026,
      "currency_symbol": "₦",
      "yearly_totals": {
        "total_income": 12345.67,
        "total_expense": 2345.67,
        "net_profit": 10000.0
      },
      "months": [
        {
          "month": 1,
          "month_name": "January",
          "year": 2026,
          "total_income": 1000.0,
          "total_expense": 500.0,
          "net_profit": 500.0,
          "outstanding_invoices": 200.0,
          "profit_margin": 50.0
        },
        ...
      ]
    }
    """
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return JsonResponse({"detail": "Company profile not found."}, status=400)

    try:
        year_param = request.GET.get("year")
        if year_param:
            year = int(year_param)
        else:
            year = timezone.now().year
    except (TypeError, ValueError):
        return JsonResponse({"detail": "Invalid year parameter."}, status=400)

    ledgers = (
        Ledger.objects.filter(company=company, year=year)
        .order_by("month")
    )

    currency_symbol = getattr(company, "currency_symbol", "₦")

    months_data = []
    total_income = Decimal("0")
    total_expense = Decimal("0")
    total_net_profit = Decimal("0")

    for ledger in ledgers:
        income = ledger.total_income or 0
        expense = ledger.total_expense or 0
        net_profit = ledger.net_profit or 0
        outstanding = getattr(ledger, "outstanding_invoices", 0)

        total_income += income
        total_expense += expense
        total_net_profit += net_profit

        profit_margin = 0.0
        if income and income != 0:
            try:
                profit_margin = float((net_profit / income) * 100)
            except Exception:
                profit_margin = 0.0

        months_data.append(
            {
                "month": ledger.month,
                "month_name": getattr(ledger, "month_name", ""),
                "year": ledger.year,
                "total_income": float(income),
                "total_expense": float(expense),
                "net_profit": float(net_profit),
                "outstanding_invoices": float(outstanding or 0),
                "profit_margin": profit_margin,
            }
        )

    response_data = {
        "year": year,
        "currency_symbol": currency_symbol,
        "yearly_totals": {
            "total_income": float(total_income),
            "total_expense": float(total_expense),
            "net_profit": float(total_net_profit),
        },
        "months": months_data,
    }

    return JsonResponse(response_data, status=200)


@login_required
@company_admin_or_permission_required('accounting.view_transaction', raise_exception=True)
def export_accounting_data(request):
    """Export accounting data to CSV/Excel/PDF"""
    user = request.user
    company = get_company_profile_for_user(user, request)
    
    if not company:
        messages.error(request, "Company profile not found.")
        return redirect('core:company_profile')
    
    export_type = request.GET.get('type', 'transactions')
    format_type = request.GET.get('format', 'csv')
    
    if export_type == 'transactions':
        # Export transactions (visibility-scoped)
        transactions = for_user_queryset(
            Transaction, request.user, request, account_lookup='company__account'
        ).filter(is_void=False, is_deleted=False).order_by('-transaction_date')
        
        if format_type == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="transactions_{timezone.now().strftime("%Y%m%d")}.csv"'
            
            writer = csv.writer(response)
            writer.writerow([
                'S/N', 'Date', 'Type', 'Title', 'Amount', 'Currency', 'Tax', 'Discount', 
                'Net Amount', 'Source', 'Reference', 'Notes', 'Reconciled'
            ])
            
            # Use the utility function for currency conversion
            
            for index, transaction in enumerate(transactions, 1):
                currency_display = get_currency_display(transaction.currency)
                writer.writerow([
                    index,  # Serial number
                    transaction.transaction_date,
                    transaction.get_type_display(),
                    clean_transaction_text(transaction.title),
                    transaction.amount,
                    currency_display,
                    transaction.tax or 0,
                    transaction.discount or 0,
                    transaction.net_amount,
                    clean_transaction_text(transaction.get_source_app_display()),
                    clean_transaction_text(transaction.reference_id or ''),
                    clean_transaction_text(transaction.notes or ''),
                    'Yes' if transaction.is_reconciled else 'No',
                ])
            
            return response
        
        elif format_type == 'excel':
            try:
                import openpyxl
                from openpyxl.styles import Font, PatternFill, Alignment
                
                # Create workbook and worksheet
                wb = openpyxl.Workbook()
                ws = wb.active
                ws.title = "Transactions"
                
                # Use the utility function for currency conversion
                
                # Define headers
                headers = [
                    'S/N', 'Date', 'Type', 'Title', 'Amount', 'Currency', 'Tax', 'Discount', 
                    'Net Amount', 'Source', 'Reference', 'Notes', 'Reconciled'
                ]
                
                # Style for headers
                header_font = Font(bold=True, color="FFFFFF")
                header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
                header_alignment = Alignment(horizontal="center", vertical="center")
                
                # Write headers
                for col, header in enumerate(headers, 1):
                    cell = ws.cell(row=1, column=col, value=header)
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.alignment = header_alignment
                
                # Write data
                for row, transaction in enumerate(transactions, 2):
                    currency_display = get_currency_display(transaction.currency)
                    ws.cell(row=row, column=1, value=row-1)  # Serial number
                    ws.cell(row=row, column=2, value=transaction.transaction_date)
                    ws.cell(row=row, column=3, value=transaction.get_type_display())
                    ws.cell(row=row, column=4, value=clean_transaction_text(transaction.title))
                    ws.cell(row=row, column=5, value=float(transaction.amount))
                    ws.cell(row=row, column=6, value=currency_display)
                    ws.cell(row=row, column=7, value=float(transaction.tax or 0))
                    ws.cell(row=row, column=8, value=float(transaction.discount or 0))
                    ws.cell(row=row, column=9, value=float(transaction.net_amount))
                    ws.cell(row=row, column=10, value=clean_transaction_text(transaction.get_source_app_display()))
                    ws.cell(row=row, column=11, value=clean_transaction_text(transaction.reference_id or ''))
                    ws.cell(row=row, column=12, value=clean_transaction_text(transaction.notes or ''))
                    ws.cell(row=row, column=13, value='Yes' if transaction.is_reconciled else 'No')
                
                # Auto-adjust column widths
                for column in ws.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    adjusted_width = min(max_length + 2, 50)
                    ws.column_dimensions[column_letter].width = adjusted_width
                
                # Create response
                response = HttpResponse(
                    content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                )
                response['Content-Disposition'] = f'attachment; filename="transactions_{timezone.now().strftime("%Y%m%d")}.xlsx"'
                
                wb.save(response)
                return response
                
            except ImportError:
                messages.error(request, "Excel export requires openpyxl package. Please install it.")
                return redirect('accounting:transaction_list')
        
        elif format_type == 'pdf':
            try:
                from reportlab.lib.pagesizes import letter, A4
                from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
                from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
                from reportlab.lib.units import inch
                from reportlab.lib import colors
                from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
                from io import BytesIO
                
                # Create the HttpResponse object with PDF headers
                response = HttpResponse(content_type='application/pdf')
                response['Content-Disposition'] = f'attachment; filename="transactions_{timezone.now().strftime("%Y%m%d")}.pdf"'
                
                # Create the PDF object using BytesIO as its "file."
                buffer = BytesIO()
                doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
                
                # Container for the 'Flowable' objects
                elements = []
                
                # Get styles
                styles = getSampleStyleSheet()
                title_style = ParagraphStyle(
                    'CustomTitle',
                    parent=styles['Heading1'],
                    fontSize=16,
                    spaceAfter=30,
                    alignment=TA_CENTER,
                    textColor=colors.darkblue
                )
                
                # Add title
                title = Paragraph(f"Transaction Report - {company.company_name}", title_style)
                elements.append(title)
                
                # Add company info
                company_info = Paragraph(f"Generated on: {timezone.now().strftime('%B %d, %Y at %I:%M %p')}", styles['Normal'])
                elements.append(company_info)
                elements.append(Spacer(1, 20))
                
                # Use the utility function for currency conversion
                
                # Function to create paragraph for better text rendering
                def create_paragraph(text, style):
                    """Create a ReportLab Paragraph object for better text rendering"""
                    if not text:
                        return ""
                    
                    # Clean the text using our utility function
                    clean_text = clean_transaction_text(text)
                    
                    # Wrap text if it's too long
                    if len(clean_text) > 25:
                        words = clean_text.split()
                        lines = []
                        current_line = ""
                        
                        for word in words:
                            if len(current_line + " " + word) <= 25:
                                current_line += (" " + word) if current_line else word
                            else:
                                if current_line:
                                    lines.append(current_line)
                                current_line = word
                        
                        if current_line:
                            lines.append(current_line)
                        
                        clean_text = "<br/>".join(lines)
                    
                    return Paragraph(clean_text, style)
                
                # Prepare table data with serial numbers
                table_data = [['S/N', 'Date', 'Type', 'Title', 'Amount', 'Currency', 'Tax', 'Discount', 'Net Amount', 'Source', 'Reconciled']]
                
                # Create paragraph style for text cells
                text_style = ParagraphStyle(
                    'TableCell',
                    parent=styles['Normal'],
                    fontSize=8,
                    leading=10,
                    spaceAfter=2,
                    spaceBefore=2,
                    leftIndent=2,
                    rightIndent=2,
                )
                
                for index, transaction in enumerate(transactions, 1):
                    # Get proper currency display
                    currency_display = get_currency_display(transaction.currency)
                    
                    # Create paragraph for title with proper text wrapping
                    title_paragraph = create_paragraph(transaction.title, text_style)
                    
                    # Create paragraph for source with proper text wrapping
                    source_paragraph = create_paragraph(transaction.get_source_app_display(), text_style)
                    
                    table_data.append([
                        str(index),  # Serial number
                        transaction.transaction_date.strftime('%Y-%m-%d'),
                        transaction.get_type_display(),
                        title_paragraph,  # Use paragraph object
                        f"{transaction.amount:,.2f}",
                        currency_display,
                        f"{transaction.tax or 0:,.2f}",
                        f"{transaction.discount or 0:,.2f}",
                        f"{transaction.net_amount:,.2f}",
                        source_paragraph,  # Use paragraph object
                        'Yes' if transaction.is_reconciled else 'No',
                    ])
                
                # Create table with adjusted column widths for better layout
                col_widths = [
                    0.8*inch,  # S/N - significantly increased width to prevent cutoff
                    0.7*inch,  # Date - slightly reduced
                    0.5*inch,  # Type - slightly reduced
                    1.5*inch,  # Title - reduced to accommodate wider S/N and Reconciled
                    0.7*inch,  # Amount - slightly reduced
                    0.5*inch,  # Currency
                    0.5*inch,  # Tax - slightly reduced
                    0.5*inch,  # Discount - slightly reduced
                    0.7*inch,  # Net Amount - slightly reduced
                    0.9*inch,  # Source - slightly reduced
                    0.9*inch,  # Reconciled - significantly increased width to prevent cutoff
                ]
                
                table = Table(table_data, colWidths=col_widths)
                
                # Add style to table with improved formatting
                style = TableStyle([
                    # Header styling
                    ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 9),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                    
                    # Data row styling
                    ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black),
                    ('FONTSIZE', (0, 1), (-1, -1), 8),
                    
                    # Specific column alignments
                    ('ALIGN', (0, 1), (0, -1), 'CENTER'),  # S/N center
                    ('ALIGN', (1, 1), (1, -1), 'CENTER'),  # Date center
                    ('ALIGN', (2, 1), (2, -1), 'CENTER'),  # Type center
                    ('ALIGN', (3, 1), (3, -1), 'LEFT'),    # Title left
                    ('ALIGN', (4, 1), (4, -1), 'RIGHT'),   # Amount right
                    ('ALIGN', (5, 1), (5, -1), 'CENTER'),  # Currency center
                    ('ALIGN', (6, 1), (6, -1), 'RIGHT'),   # Tax right
                    ('ALIGN', (7, 1), (7, -1), 'RIGHT'),   # Discount right
                    ('ALIGN', (8, 1), (8, -1), 'RIGHT'),   # Net Amount right
                    ('ALIGN', (9, 1), (9, -1), 'LEFT'),    # Source left
                    ('ALIGN', (10, 1), (10, -1), 'CENTER'), # Reconciled center
                    
                    # Text wrapping and padding for title and source columns
                    ('VALIGN', (3, 1), (3, -1), 'TOP'),    # Title top align
                    ('VALIGN', (9, 1), (9, -1), 'TOP'),    # Source top align
                    ('LEFTPADDING', (3, 1), (3, -1), 3),   # Title left padding
                    ('RIGHTPADDING', (3, 1), (3, -1), 3),  # Title right padding
                    ('LEFTPADDING', (9, 1), (9, -1), 3),   # Source left padding
                    ('RIGHTPADDING', (9, 1), (9, -1), 3),  # Source right padding
                    
                    # Padding for S/N and Reconciled columns to prevent cutoff
                    ('LEFTPADDING', (0, 1), (0, -1), 5),   # S/N left padding
                    ('RIGHTPADDING', (0, 1), (0, -1), 5),  # S/N right padding
                    ('LEFTPADDING', (10, 1), (10, -1), 5), # Reconciled left padding
                    ('RIGHTPADDING', (10, 1), (10, -1), 5), # Reconciled right padding
                    
                    # Row height for better text display
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.beige, colors.white]),
                ])
                table.setStyle(style)
                elements.append(table)
                
                # Add summary with proper currency display
                elements.append(Spacer(1, 20))
                total_income = sum(t.net_amount for t in transactions if t.type == 'income')
                total_expense = sum(t.net_amount for t in transactions if t.type == 'expense')
                net_total = total_income - total_expense
                
                # Use the most common currency from transactions, or default to NGN
                most_common_currency = 'NGN'
                if transactions.exists():
                    currency_counts = {}
                    for t in transactions:
                        currency = get_currency_display(t.currency)
                        currency_counts[currency] = currency_counts.get(currency, 0) + 1
                    if currency_counts:
                        most_common_currency = max(currency_counts, key=currency_counts.get)
                
                summary_data = [
                    ['Summary', 'Amount'],
                    ['Total Income', f"{most_common_currency} {total_income:,.2f}"],
                    ['Total Expense', f"{most_common_currency} {total_expense:,.2f}"],
                    ['Net Total', f"{most_common_currency} {net_total:,.2f}"],
                ]
                
                summary_table = Table(summary_data, colWidths=[2*inch, 1.5*inch])
                summary_style = TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black),
                    ('ALIGN', (1, 1), (1, -1), 'RIGHT'),  # Right align amounts
                ])
                summary_table.setStyle(summary_style)
                elements.append(summary_table)
                
                # Build PDF
                doc.build(elements)
                
                # Get the value of the BytesIO buffer and write it to the response
                pdf = buffer.getvalue()
                buffer.close()
                response.write(pdf)
                
                return response
                
            except ImportError:
                messages.error(request, "PDF export requires reportlab package. Please install it.")
                return redirect('accounting:transaction_list')
    
    elif export_type == 'ledger':
        # Export ledger summary
        year = request.GET.get('year', timezone.now().year)
        ledgers = Ledger.objects.filter(
            company=company,
            year=year
        ).order_by('month')
        
        if format_type == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="ledger_{year}.csv"'
            
            writer = csv.writer(response)
            writer.writerow(['S/N', 'Month', 'Income', 'Expense', 'Net Profit', 'Outstanding Invoices', 'Profit Margin'])
            
            # Get company currency code instead of symbol
            company_currency_symbol = getattr(company, 'currency_symbol', '₦')
            company_currency_code = get_currency_display(company_currency_symbol)
            
            for index, ledger in enumerate(ledgers, 1):
                profit_margin = 0
                if ledger.total_income > 0:
                    profit_margin = (ledger.net_profit / ledger.total_income) * 100
                
                writer.writerow([
                    index,  # Serial number
                    ledger.month_name,
                    f"{company_currency_code} {ledger.total_income:,.2f}",
                    f"{company_currency_code} {ledger.total_expense:,.2f}",
                    f"{company_currency_code} {ledger.net_profit:,.2f}",
                    f"{company_currency_code} {ledger.outstanding_invoices:,.2f}",
                    f"{profit_margin:.1f}%",
                ])
            
            return response
        
        elif format_type == 'excel':
            try:
                import openpyxl
                from openpyxl.styles import Font, PatternFill, Alignment
                
                # Create workbook and worksheet
                wb = openpyxl.Workbook()
                ws = wb.active
                ws.title = "Ledger Summary"
                
                # Get company currency code instead of symbol
                company_currency_symbol = getattr(company, 'currency_symbol', '₦')
                company_currency_code = get_currency_display(company_currency_symbol)
                
                # Define headers
                headers = ['S/N', 'Month', 'Income', 'Expense', 'Net Profit', 'Outstanding Invoices', 'Profit Margin']
                
                # Style for headers
                header_font = Font(bold=True, color="FFFFFF")
                header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
                header_alignment = Alignment(horizontal="center", vertical="center")
                
                # Write headers
                for col, header in enumerate(headers, 1):
                    cell = ws.cell(row=1, column=col, value=header)
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.alignment = header_alignment
                
                # Write data
                for row, ledger in enumerate(ledgers, 2):
                    profit_margin = 0
                    if ledger.total_income > 0:
                        profit_margin = (ledger.net_profit / ledger.total_income) * 100
                    
                    ws.cell(row=row, column=1, value=row-1)  # Serial number
                    ws.cell(row=row, column=2, value=ledger.month_name)
                    ws.cell(row=row, column=3, value=f"{company_currency_code} {float(ledger.total_income):,.2f}")
                    ws.cell(row=row, column=4, value=f"{company_currency_code} {float(ledger.total_expense):,.2f}")
                    ws.cell(row=row, column=5, value=f"{company_currency_code} {float(ledger.net_profit):,.2f}")
                    ws.cell(row=row, column=6, value=f"{company_currency_code} {float(ledger.outstanding_invoices):,.2f}")
                    ws.cell(row=row, column=7, value=f"{profit_margin:.1f}%")
                
                # Auto-adjust column widths
                for column in ws.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    adjusted_width = min(max_length + 2, 50)
                    ws.column_dimensions[column_letter].width = adjusted_width
                
                # Create response
                response = HttpResponse(
                    content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                )
                response['Content-Disposition'] = f'attachment; filename="ledger_{year}.xlsx"'
                
                wb.save(response)
                return response
                
            except ImportError:
                messages.error(request, "Excel export requires openpyxl package. Please install it.")
                return redirect('accounting:transaction_list')
        
        elif format_type == 'pdf':
            try:
                from reportlab.lib.pagesizes import letter, A4
                from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
                from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
                from reportlab.lib.units import inch
                from reportlab.lib import colors
                from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
                from io import BytesIO
                
                # Create the HttpResponse object with PDF headers
                response = HttpResponse(content_type='application/pdf')
                response['Content-Disposition'] = f'attachment; filename="ledger_{year}.pdf"'
                
                # Create the PDF object using BytesIO as its "file."
                buffer = BytesIO()
                doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
                
                # Container for the 'Flowable' objects
                elements = []
                
                # Get styles
                styles = getSampleStyleSheet()
                title_style = ParagraphStyle(
                    'CustomTitle',
                    parent=styles['Heading1'],
                    fontSize=16,
                    spaceAfter=30,
                    alignment=TA_CENTER,
                    textColor=colors.darkblue
                )
                
                # Add title
                title = Paragraph(f"Ledger Summary Report - {year} - {company.company_name}", title_style)
                elements.append(title)
                
                # Add company info
                company_info = Paragraph(f"Generated on: {timezone.now().strftime('%B %d, %Y at %I:%M %p')}", styles['Normal'])
                elements.append(company_info)
                elements.append(Spacer(1, 20))
                
                # Get company currency code instead of symbol
                company_currency_symbol = getattr(company, 'currency_symbol', '₦')
                company_currency_code = get_currency_display(company_currency_symbol)
                
                # Prepare table data with serial numbers and currency
                table_data = [['S/N', 'Month', 'Income', 'Expense', 'Net Profit', 'Outstanding Invoices', 'Profit Margin']]
                
                for index, ledger in enumerate(ledgers, 1):
                    profit_margin = 0
                    if ledger.total_income > 0:
                        profit_margin = (ledger.net_profit / ledger.total_income) * 100
                    
                    table_data.append([
                        str(index),  # Serial number
                        ledger.month_name,
                        f"{company_currency_code} {ledger.total_income:,.2f}",
                        f"{company_currency_code} {ledger.total_expense:,.2f}",
                        f"{company_currency_code} {ledger.net_profit:,.2f}",
                        f"{company_currency_code} {ledger.outstanding_invoices:,.2f}",
                        f"{profit_margin:.1f}%",
                    ])
                
                # Create table with adjusted column widths
                table = Table(table_data, colWidths=[0.5*inch, 1.2*inch, 1.2*inch, 1.2*inch, 1.2*inch, 1.2*inch, 1.0*inch])
                
                # Add style to table with improved formatting for new columns
                style = TableStyle([
                    # Header styling
                    ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 9),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                    
                    # Data row styling
                    ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black),
                    ('FONTSIZE', (0, 1), (-1, -1), 8),
                    
                    # Specific column alignments
                    ('ALIGN', (0, 1), (0, -1), 'CENTER'),  # S/N center
                    ('ALIGN', (1, 1), (1, -1), 'LEFT'),     # Month left
                    ('ALIGN', (2, 1), (5, -1), 'RIGHT'),    # Amounts right
                    ('ALIGN', (6, 1), (6, -1), 'CENTER'),   # Profit margin center
                    
                    # Row height for better text display
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.beige, colors.white]),
                ])
                table.setStyle(style)
                elements.append(table)
                
                # Add yearly summary with currency
                elements.append(Spacer(1, 20))
                yearly_income = sum(ledger.total_income for ledger in ledgers)
                yearly_expense = sum(ledger.total_expense for ledger in ledgers)
                yearly_profit = sum(ledger.net_profit for ledger in ledgers)
                
                summary_data = [
                    ['Yearly Summary', 'Amount'],
                    ['Total Income', f"{company_currency_code} {yearly_income:,.2f}"],
                    ['Total Expense', f"{company_currency_code} {yearly_expense:,.2f}"],
                    ['Net Profit', f"{company_currency_code} {yearly_profit:,.2f}"],
                ]
                
                summary_table = Table(summary_data, colWidths=[2*inch, 1.5*inch])
                summary_style = TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 12),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black),
                    ('ALIGN', (1, 1), (1, -1), 'RIGHT'),  # Right align amounts
                ])
                summary_table.setStyle(summary_style)
                elements.append(summary_table)
                
                # Build PDF
                doc.build(elements)
                
                # Get the value of the BytesIO buffer and write it to the response
                pdf = buffer.getvalue()
                buffer.close()
                response.write(pdf)
                
                return response
                
            except ImportError:
                messages.error(request, "PDF export requires reportlab package. Please install it.")
                return redirect('accounting:transaction_list')
    
    messages.error(request, "Invalid export type or format.")
    return redirect('accounting:transaction_list')


@login_required
@company_admin_or_permission_required('accounting.view_transaction', raise_exception=True)
@require_POST
@csrf_exempt
def update_ledger_ajax(request):
    """AJAX endpoint to update ledger data with comprehensive chart data"""
    try:
        data = json.loads(request.body)
        month = data.get('month')
        year = data.get('year')
        include_charts = data.get('include_charts', False)
        
        user = request.user
        company = get_company_profile_for_user(user, request)
        
        if not company:
            return JsonResponse({'error': 'Company profile not found'}, status=400)
        
        # Update ledger for the specified month
        ledger = Ledger.objects.filter(
            company=company,
            year=year,
            month=month
        ).first()
        
        if ledger:
            ledger.update_outstanding_amounts()
        
        # Get outstanding invoices (company-scoped for accurate dashboard)
        from apps.invoices.models import Invoice
        outstanding_invoices = Invoice.objects.filter(
            user__account_id=company.account_id,
            status__in=['unpaid', 'partial']
        ).aggregate(total=Sum('balance_due'))['total'] or 0
        
        # Transaction queryset scoped to current user visibility
        txn_qs = for_user_queryset(
            Transaction, request.user, request, account_lookup='company__account'
        ).filter(is_void=False, is_deleted=False)
        
        # Get today's transactions
        current_date = timezone.now()
        today_transactions = txn_qs.filter(transaction_date=current_date.date())
        
        today_income = today_transactions.filter(type='income').aggregate(
            total=Sum('net_amount')
        )['total'] or 0
        
        today_expense = today_transactions.filter(type='expense').aggregate(
            total=Sum('net_amount')
        )['total'] or 0
        
        response_data = {
            'success': True,
            'total_income': float(ledger.total_income) if ledger else 0,
            'total_expense': float(ledger.total_expense) if ledger else 0,
            'net_profit': float(ledger.net_profit) if ledger else 0,
            'outstanding_invoices': float(outstanding_invoices),
            'today_income': float(today_income),
            'today_expense': float(today_expense),
            'currency_symbol': company.currency_symbol if company else '₦',
            'currency_code': company.currency_code if company else 'NGN',
        }
        
        # Include chart data if requested
        if include_charts:
            # Monthly data for charts (last 12 months) - improved with real transaction data
            monthly_data = []
            for i in range(12):
                date = current_date - timedelta(days=30*i)
                
                # Get or create ledger for this month
                month_ledger = Ledger.objects.filter(
                    company=company,
                    year=date.year,
                    month=date.month
                ).first()
                
                # If no ledger exists, calculate from actual transactions
                if not month_ledger:
                    month_transactions = txn_qs.filter(
                        transaction_date__year=date.year,
                        transaction_date__month=date.month
                    )
                    
                    month_income = month_transactions.filter(type='income').aggregate(
                        total=Sum('net_amount')
                    )['total'] or 0
                    
                    month_expense = month_transactions.filter(type='expense').aggregate(
                        total=Sum('net_amount')
                    )['total'] or 0
                    
                    month_profit = month_income - month_expense
                else:
                    month_income = float(month_ledger.total_income)
                    month_expense = float(month_ledger.total_expense)
                    month_profit = float(month_ledger.net_profit)
                
                monthly_data.append({
                    'month': date.strftime('%b %Y'),
                    'income': month_income,
                    'expense': month_expense,
                    'profit': month_profit,
                })
            
            # Source breakdown data
            source_breakdown = txn_qs.values('source_app').annotate(
                total=Sum('net_amount'),
                count=Count('id')
            ).order_by('-total')
            
            # Recent transactions
            recent_transactions = txn_qs.order_by('-created_at')[:10]
            
            response_data.update({
                'monthly_data': list(reversed(monthly_data)),
                'today_data': {
                    'income': float(today_income),
                    'expense': float(today_expense)
                },
                'source_data': list(source_breakdown),
                'recent_transactions': [
                    {
                        'title': t.title,
                        'type': t.type,
                        'type_display': t.get_type_display(),
                        'net_amount': float(t.net_amount),
                        'date': t.transaction_date.strftime('%b %d, %Y'),
                        'source_app': t.get_source_app_display()
                    }
                    for t in recent_transactions
                ]
            })
        
        return JsonResponse(response_data)
        
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        print(f"Unexpected error: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@company_admin_or_permission_required('accounting.change_transaction', raise_exception=True)
def sync_from_other_apps(request):
    """Sync transactions from other apps"""
    user = request.user
    company = get_company_profile_for_user(user, request)
    
    if not company:
        messages.error(request, "Company profile not found.")
        return redirect('core:company_profile')
    
    if request.method == 'POST':
        # Sync from invoices
        from apps.invoices.models import Invoice
        from apps.receipts.models import Receipt
        
        # Sync paid invoices
        paid_invoices = Invoice.objects.filter(
            user=user,
            status='paid'
        )
        
        synced_count = 0
        for invoice in paid_invoices:
            # Check if transaction already exists
            existing_transaction = Transaction.objects.filter(
                company=company,
                source_app='invoice',
                reference_id=str(invoice.id)
            ).first()
            
            if not existing_transaction:
                Transaction.objects.create(
                    user=user,
                    company=company,
                    type='income',
                    title=f"Invoice Payment - {invoice.invoice_number}",
                    description=f"Payment for invoice {invoice.invoice_number} from {invoice.client_name}",
                    amount=invoice.grand_total,
                    currency=company.currency_code,
                    tax=invoice.total_tax,
                    discount=invoice.total_discount,
                    source_app='invoice',
                    reference_id=str(invoice.id),
                    reference_model='Invoice',
                    transaction_date=invoice.updated_at.date(),
                    notes=f"Auto-synced from invoice {invoice.invoice_number}"
                )
                synced_count += 1
        
        # Sync from receipts
        receipts = Receipt.objects.filter(
            created_by=user
        )
        
        for receipt in receipts:
            existing_transaction = Transaction.objects.filter(
                company=company,
                source_app='receipt',
                reference_id=str(receipt.id)
            ).first()
            
            if not existing_transaction:
                Transaction.objects.create(
                    user=user,
                    company=company,
                    type='income',
                    title=f"Receipt Payment - {receipt.receipt_no}",
                    description=f"Payment receipt {receipt.receipt_no} from {receipt.client_name}",
                    amount=receipt.amount_received,
                    currency=company.currency_code,
                    source_app='receipt',
                    reference_id=str(receipt.id),
                    reference_model='Receipt',
                    transaction_date=receipt.date_received,
                    notes=f"Auto-synced from receipt {receipt.receipt_no}"
                )
                synced_count += 1
        
        messages.success(request, f"Successfully synced {synced_count} transactions from other apps.")
        return redirect('accounting:transaction_list')
    
    return render(request, 'accounting/sync_from_other_apps.html')


@login_required
@company_admin_or_permission_required('accounting.view_transaction', raise_exception=True)
def generate_report(request):
    """Generate financial reports"""
    user = request.user
    company = get_company_profile_for_user(user, request)
    
    if not company:
        messages.error(request, "Company profile not found.")
        return redirect('core:company_profile')
    
    if request.method == 'POST':
        form = FinancialReportForm(request.POST)
        if form.is_valid():
            report = form.save(commit=False)
            report.company = company
            report.created_by = user
            
            # Generate report data based on type (visibility-scoped: admin=company-wide, team=own)
            if report.report_type == 'income_statement':
                report.report_data = generate_income_statement(company, report.start_date, report.end_date, request=request)
            elif report.report_type == 'balance_sheet':
                report.report_data = generate_balance_sheet(company, report.end_date, request=request)
            
            report.save()
            
            messages.success(request, f"Report '{report.title}' generated successfully.")
            return redirect('accounting:view_report', report_id=report.id)
    else:
        form = FinancialReportForm()
    
    context = {
        'form': form,
    }
    
    return render(request, 'accounting/generate_report.html', context)


@login_required
@company_admin_or_permission_required('accounting.view_transaction', raise_exception=True)
def export_report_pdf(request, report_id):
    """Export financial report as PDF. Per-creator: team members can only export reports they created."""
    user = request.user
    company = get_company_profile_for_user(user, request)
    
    if not company:
        messages.error(request, "Company profile not found.")
        return redirect('core:company_profile')
    
    report = get_object_or_404(FinancialReport, id=report_id, company=company)
    if not is_company_admin(user, request) and getattr(report, 'created_by_id', None) != user.pk:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied("You can only export reports you created.")
    
    txn_qs = for_user_queryset(Transaction, request.user, request, account_lookup='company__account').filter(is_void=False, is_deleted=False)
    original_transactions_count = txn_qs.filter(
        transaction_date__range=[report.start_date, report.end_date]
    ).count()
    
    if original_transactions_count == 0:
        latest_transaction = txn_qs.order_by('-transaction_date').first()
        
        if latest_transaction:
            adjusted_start_date = min(report.start_date, latest_transaction.transaction_date)
            adjusted_end_date = max(report.end_date, latest_transaction.transaction_date)
            
            if report.report_type == 'income_statement':
                fresh_report_data = generate_income_statement(company, adjusted_start_date, adjusted_end_date, request=request)
            elif report.report_type == 'balance_sheet':
                fresh_report_data = generate_balance_sheet(company, adjusted_end_date, request=request)
            else:
                fresh_report_data = report.report_data
            
            fresh_report_data['date_adjusted'] = True
            fresh_report_data['original_period'] = f"{report.start_date} to {report.end_date}"
            fresh_report_data['adjusted_period'] = f"{adjusted_start_date} to {adjusted_end_date}"
        else:
            if report.report_type == 'income_statement':
                fresh_report_data = generate_income_statement(company, report.start_date, report.end_date, request=request)
            elif report.report_type == 'balance_sheet':
                fresh_report_data = generate_balance_sheet(company, report.end_date, request=request)
            else:
                fresh_report_data = report.report_data
            fresh_report_data['date_adjusted'] = False
    else:
        if report.report_type == 'income_statement':
            fresh_report_data = generate_income_statement(company, report.start_date, report.end_date, request=request)
        elif report.report_type == 'balance_sheet':
            fresh_report_data = generate_balance_sheet(company, report.end_date, request=request)
        else:
            fresh_report_data = report.report_data
        fresh_report_data['date_adjusted'] = False
    
    try:
        from reportlab.lib.pagesizes import letter, A4
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from io import BytesIO
        import os
        
        # Create the HttpResponse object with PDF headers
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{report.title}_{timezone.now().strftime("%Y%m%d")}.pdf"'
        
        # Register fonts for better Unicode support
        try:
            # Try to register a Unicode-compatible font if available
            font_path = os.path.join(os.path.dirname(__file__), '..', '..', 'static', 'fonts')
            
            # Try to find a Unicode-compatible font
            unicode_fonts = [
                'DejaVuSans.ttf',
                'Arial.ttf',
                'arial.ttf',
                'LiberationSans-Regular.ttf',
                'FreeSans.ttf'
            ]
            
            default_font = 'Helvetica'  # Default fallback
            font_registered = False
            
            for font_file in unicode_fonts:
                font_path_full = os.path.join(font_path, font_file)
                if os.path.exists(font_path_full):
                    try:
                        font_name = font_file.replace('.ttf', '')
                        pdfmetrics.registerFont(TTFont(font_name, font_path_full))
                        default_font = font_name
                        font_registered = True
                        break
                    except:
                        continue
            
            # If no font found in static directory, try system fonts
            if not font_registered:
                # Try to use a system font that supports Unicode
                system_fonts = [
                    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                    '/System/Library/Fonts/Arial.ttf',
                    'C:/Windows/Fonts/arial.ttf',
                    'C:/Windows/Fonts/calibri.ttf'
                ]
                
                for system_font in system_fonts:
                    if os.path.exists(system_font):
                        try:
                            font_name = os.path.basename(system_font).replace('.ttf', '')
                            pdfmetrics.registerFont(TTFont(font_name, system_font))
                            default_font = font_name
                            font_registered = True
                            break
                        except:
                            continue
            
            # If we registered a custom font, we need to be careful about bold variants
            # Most TTF fonts don't automatically have bold variants in ReportLab
            # So we'll use the regular font for everything and rely on font weight
            if font_registered:
                # Use the registered font name without bold suffix
                default_font = default_font
            else:
                # Use Helvetica which has built-in bold variants
                default_font = 'Helvetica'
                            
        except Exception as e:
            print(f"Font registration error: {e}")
            default_font = 'Helvetica'
        
        # Create the PDF object using BytesIO as its "file."
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
        
        # Container for the 'Flowable' objects
        elements = []
        
        # Get styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            spaceAfter=30,
            alignment=TA_CENTER,
            textColor=colors.darkblue
        )
        
        subtitle_style = ParagraphStyle(
            'Subtitle',
            parent=styles['Heading2'],
            fontSize=14,
            spaceAfter=20,
            alignment=TA_CENTER,
            textColor=colors.darkgreen
        )
        
        # Add title
        title = Paragraph(f"{report.title}", title_style)
        elements.append(title)
        
        # Add subtitle
        subtitle = Paragraph(f"{report.get_report_type_display()} - {company.company_name}", subtitle_style)
        elements.append(subtitle)
        
        # Add report info with currency
        currency_symbol = getattr(company, 'currency_symbol', '₦')
        if report.report_type == 'balance_sheet':
            report_info = Paragraph(f"As of: {fresh_report_data.get('as_of_date', report.end_date)}<br/>Generated on: {timezone.now().strftime('%B %d, %Y at %I:%M %p')}", styles['Normal'])
        else:
            report_info = Paragraph(f"Period: {fresh_report_data.get('period', f'{report.start_date} to {report.end_date}')}<br/>Generated on: {timezone.now().strftime('%B %d, %Y at %I:%M %p')}", styles['Normal'])
        elements.append(report_info)
        
        # Add date adjustment notice if applicable
        if fresh_report_data.get('date_adjusted'):
            adjustment_notice = Paragraph(f"<b>Note:</b> Date range adjusted to include actual data. Original: {fresh_report_data['original_period']} → Adjusted: {fresh_report_data['adjusted_period']}", styles['Normal'])
            elements.append(adjustment_notice)
        
        elements.append(Spacer(1, 30))
        
        # Generate report content based on type with fresh data
        if report.report_type == 'income_statement':
            elements.extend(generate_income_statement_pdf_content(fresh_report_data, currency_symbol, default_font))
        elif report.report_type == 'balance_sheet':
            elements.extend(generate_balance_sheet_pdf_content(fresh_report_data, currency_symbol, default_font))
        else:
            # Generic report display
            elements.append(Paragraph("Report Data:", styles['Heading3']))
            elements.append(Spacer(1, 10))
            
            # Display report data as table
            if fresh_report_data:
                # Handle currency symbol for PDF compatibility - try symbol first, fallback to text
                pdf_currency = get_pdf_currency_symbol(currency_symbol, use_symbol=False)
                
                table_data = [['Item', 'Value']]
                for key, value in fresh_report_data.items():
                    if key not in ['date_adjusted', 'original_period', 'adjusted_period', 'debug_info']:
                        if isinstance(value, (int, float)):
                            table_data.append([key.replace('_', ' ').title(), f"{pdf_currency} {value:,.2f}"])
                        else:
                            table_data.append([key.replace('_', ' ').title(), str(value)])
                
                # Determine font names based on whether we're using a custom font or built-in Helvetica
                if default_font == 'Helvetica':
                    header_font = 'Helvetica-Bold'
                    bold_font = 'Helvetica-Bold'
                else:
                    # For custom fonts, use the regular font name (no bold variant available)
                    header_font = default_font
                    bold_font = default_font
                
                table = Table(table_data, colWidths=[3*inch, 2*inch])
                style = TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('FONTNAME', (0, 0), (-1, 0), header_font),
                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black),
                    ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
                ])
                table.setStyle(style)
                elements.append(table)
        
        # Build PDF
        doc.build(elements)
        
        # Get the value of the BytesIO buffer and write it to the response
        pdf = buffer.getvalue()
        buffer.close()
        response.write(pdf)
        
        return response
        
    except Exception as e:
        messages.error(request, f"Error generating PDF: {str(e)}")
        return redirect('accounting:view_report', report_id=report.id)


def generate_income_statement_pdf_content(report_data, currency_symbol, default_font='Helvetica'):
    """Generate PDF content for income statement"""
    from reportlab.platypus import Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    
    elements = []
    styles = getSampleStyleSheet()
    
    # Handle currency symbol for PDF compatibility
    pdf_currency = get_pdf_currency_symbol(currency_symbol, use_symbol=False)
    
    # Income Statement table
    table_data = [
        ['Income Statement', ''],
        ['', ''],
        ['Revenue', f"{pdf_currency} {report_data.get('income', 0):,.2f}"],
        ['', ''],
        ['Expenses', f"{pdf_currency} {report_data.get('expenses', 0):,.2f}"],
        ['', ''],
        ['Net Income', f"{pdf_currency} {report_data.get('net_income', 0):,.2f}"],
    ]
    
    table = Table(table_data, colWidths=[3*inch, 2*inch])
    # Determine font names based on whether we're using a custom font or built-in Helvetica
    if default_font == 'Helvetica':
        header_font = 'Helvetica-Bold'
        bold_font = 'Helvetica-Bold'
    else:
        # For custom fonts, use the regular font name (no bold variant available)
        header_font = default_font
        bold_font = default_font
    
    style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), header_font),
        ('FONTSIZE', (0, 0), (-1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
        ('FONTNAME', (0, 2), (0, 2), bold_font),  # Revenue
        ('FONTNAME', (0, 4), (0, 4), bold_font),  # Expenses
        ('FONTNAME', (0, 6), (0, 6), bold_font),  # Net Income
        ('BACKGROUND', (0, 2), (-1, 2), colors.lightgreen),  # Revenue section
        ('BACKGROUND', (0, 4), (-1, 4), colors.lightcoral),  # Expenses section
        ('BACKGROUND', (0, 6), (-1, 6), colors.lightblue),  # Net Income section
    ])
    table.setStyle(style)
    elements.append(table)
    
    # Add period information
    if report_data.get('period'):
        elements.append(Spacer(1, 20))
        period_info = Paragraph(f"<b>Period:</b> {report_data['period']}", styles['Normal'])
        elements.append(period_info)
    
    return elements


def generate_balance_sheet_pdf_content(report_data, currency_symbol, default_font='Helvetica'):
    """Generate PDF content for balance sheet"""
    from reportlab.platypus import Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    
    elements = []
    styles = getSampleStyleSheet()
    
    # Handle currency symbol for PDF compatibility - try symbol first, fallback to text
    pdf_currency = get_pdf_currency_symbol(currency_symbol, use_symbol=False)
    
    # Balance Sheet table with detailed breakdown
    table_data = [
        ['Balance Sheet', ''],
        ['', ''],
        ['ASSETS', ''],
        ['Cash', f"{pdf_currency} {report_data.get('cash', 0):,.2f}"],
        ['Accounts Receivable', f"{pdf_currency} {report_data.get('accounts_receivable', 0):,.2f}"],
        ['Total Assets', f"{pdf_currency} {report_data.get('total_assets', 0):,.2f}"],
        ['', ''],
        ['LIABILITIES', ''],
        ['Accounts Payable', f"{pdf_currency} {report_data.get('accounts_payable', 0):,.2f}"],
        ['Total Liabilities', f"{pdf_currency} {report_data.get('total_liabilities', 0):,.2f}"],
        ['', ''],
        ['EQUITY', ''],
        ['Owner\'s Equity', f"{pdf_currency} {report_data.get('owner_equity', 0):,.2f}"],
        ['Retained Earnings', f"{pdf_currency} {report_data.get('retained_earnings', 0):,.2f}"],
        ['Total Equity', f"{pdf_currency} {report_data.get('owner_equity', 0) + report_data.get('retained_earnings', 0):,.2f}"],
        ['', ''],
        ['Total Liabilities & Equity', f"{pdf_currency} {report_data.get('total_liabilities', 0) + report_data.get('owner_equity', 0) + report_data.get('retained_earnings', 0):,.2f}"],
    ]
    
    # Determine font names based on whether we're using a custom font or built-in Helvetica
    if default_font == 'Helvetica':
        header_font = 'Helvetica-Bold'
        bold_font = 'Helvetica-Bold'
    else:
        # For custom fonts, use the regular font name (no bold variant available)
        header_font = default_font
        bold_font = default_font
    
    table = Table(table_data, colWidths=[3*inch, 2*inch])
    style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), header_font),
        ('FONTSIZE', (0, 0), (-1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
        ('FONTNAME', (0, 2), (0, 2), bold_font),  # ASSETS
        ('FONTNAME', (0, 8), (0, 8), bold_font),  # LIABILITIES
        ('FONTNAME', (0, 12), (0, 12), bold_font),  # EQUITY
        ('FONTNAME', (0, 5), (0, 5), bold_font),  # Total Assets
        ('FONTNAME', (0, 10), (0, 10), bold_font),  # Total Liabilities
        ('FONTNAME', (0, 15), (0, 15), bold_font),  # Total Equity
        ('FONTNAME', (0, 17), (0, 17), bold_font),  # Total Liabilities & Equity
        ('BACKGROUND', (0, 2), (-1, 2), colors.lightblue),  # Assets section
        ('BACKGROUND', (0, 8), (-1, 8), colors.lightcoral),  # Liabilities section
        ('BACKGROUND', (0, 12), (-1, 12), colors.lightgreen),  # Equity section
        ('BACKGROUND', (0, 5), (-1, 5), colors.lightgrey),  # Total Assets
        ('BACKGROUND', (0, 10), (-1, 10), colors.lightgrey),  # Total Liabilities
        ('BACKGROUND', (0, 15), (-1, 15), colors.lightgrey),  # Total Equity
        ('BACKGROUND', (0, 17), (-1, 17), colors.lightgrey),  # Total Liabilities & Equity
    ])
    table.setStyle(style)
    elements.append(table)
    
    # Add as of date information
    if report_data.get('as_of_date'):
        elements.append(Spacer(1, 20))
        as_of_info = Paragraph(f"<b>As of Date:</b> {report_data['as_of_date']}", styles['Normal'])
        elements.append(as_of_info)
    
    # Add period information
    if report_data.get('period'):
        elements.append(Spacer(1, 10))
        period_info = Paragraph(f"<b>Period:</b> {report_data['period']}", styles['Normal'])
        elements.append(period_info)
    
    return elements


# -----------------------------------------------------------------------------
# REPORT VISIBILITY POLICY (per-team-member record isolation):
# - Reports are PER-CREATOR: team members can view/export only reports they created.
# - Report DATA (income statement / balance sheet totals) is PER-USER when request
#   is passed: company admins see company-wide totals; team members see totals
#   only for transactions (and related Invoice/Expense) they are allowed to see
#   via for_user_queryset (creator isolation).
# - view_report and export_report_pdf enforce: report must belong to company and
#   either user is company admin OR report.created_by == request.user.
# -----------------------------------------------------------------------------


def generate_income_statement(company, start_date, end_date, request=None):
    """Generate income statement data. If request is provided and user is not company admin, scope transactions to that user's visibility (for_user_queryset)."""
    if request and not is_company_admin(request.user, request):
        transactions = for_user_queryset(Transaction, request.user, request, account_lookup='company__account').filter(
            transaction_date__range=[start_date, end_date],
            is_void=False,
            is_deleted=False
        )
    else:
        transactions = Transaction.objects.filter(
            company=company,
            transaction_date__range=[start_date, end_date],
            is_void=False,
            is_deleted=False
        )
    
    # Calculate income (positive amounts)
    income_transactions = transactions.filter(type='income')
    income = income_transactions.aggregate(
        total=Sum('net_amount')
    )['total'] or 0
    
    # Calculate expenses (negative amounts)
    expense_transactions = transactions.filter(type='expense')
    expenses = expense_transactions.aggregate(
        total=Sum('net_amount')
    )['total'] or 0
    
    # Calculate net income
    net_income = income - expenses
    
    # Debug information
    print(f"DEBUG: Income Statement for {company.company_name}")
    print(f"DEBUG: Date range: {start_date} to {end_date}")
    print(f"DEBUG: Total transactions found: {transactions.count()}")
    print(f"DEBUG: Income transactions: {income_transactions.count()}")
    print(f"DEBUG: Expense transactions: {expense_transactions.count()}")
    print(f"DEBUG: Total income: {income}")
    print(f"DEBUG: Total expenses: {expenses}")
    print(f"DEBUG: Net income: {net_income}")
    
    return {
        'income': float(income),
        'expenses': float(expenses),
        'net_income': float(net_income),
        'period': f"{start_date} to {end_date}",
        'debug_info': {
            'total_transactions': transactions.count(),
            'income_transactions': income_transactions.count(),
            'expense_transactions': expense_transactions.count(),
        }
    }


def generate_balance_sheet(company, as_of_date, request=None):
    """Generate balance sheet data. If request is provided and user is not company admin, scope transactions and AR/AP to that user's visibility."""
    if request and not is_company_admin(request.user, request):
        transactions = for_user_queryset(Transaction, request.user, request, account_lookup='company__account').filter(
            transaction_date__lte=as_of_date,
            is_void=False,
            is_deleted=False
        )
    else:
        transactions = Transaction.objects.filter(
            company=company,
            transaction_date__lte=as_of_date,
            is_void=False,
            is_deleted=False
        )
    
    total_income = transactions.filter(type='income').aggregate(
        total=Sum('net_amount')
    )['total'] or 0
    
    total_expenses = transactions.filter(type='expense').aggregate(
        total=Sum('net_amount')
    )['total'] or 0
    
    retained_earnings = total_income - total_expenses
    
    # Accounts receivable (Invoice: account/user; visibility-scoped when request provided)
    try:
        from apps.invoices.models import Invoice
        if request and not is_company_admin(request.user, request):
            inv_qs = for_user_queryset(Invoice, request.user, request, account_lookup='account').filter(
                status__in=['unpaid', 'partial']
            )
        else:
            inv_qs = Invoice.objects.filter(user__account_id=company.account_id, status__in=['unpaid', 'partial'])
        accounts_receivable = inv_qs.aggregate(total=Sum('balance_due'))['total'] or 0
    except Exception:
        accounts_receivable = 0
    
    cash = retained_earnings
    total_assets = cash + accounts_receivable
    
    # Accounts payable: no longer using expense_management app
    accounts_payable = 0
    
    total_liabilities = accounts_payable
    
    # Equity = Owner's Equity + Retained Earnings
    # For simplicity, we'll assume owner's equity is the initial investment
    # and calculate it to balance the equation
    owner_equity = total_assets - total_liabilities - retained_earnings
    
    # If owner's equity is negative, it means we have accumulated losses
    # In this case, we should adjust retained earnings
    if owner_equity < 0:
        retained_earnings = total_assets - total_liabilities
        owner_equity = 0
    
    # Verify the accounting equation: Assets = Liabilities + Equity
    calculated_equity = total_liabilities + owner_equity + retained_earnings
    balance_check = abs(total_assets - calculated_equity)
    
    # Debug information
    print(f"DEBUG: Balance Sheet for {company.company_name}")
    print(f"DEBUG: As of date: {as_of_date}")
    print(f"DEBUG: Total transactions found: {transactions.count()}")
    print(f"DEBUG: Total income: {total_income}")
    print(f"DEBUG: Total expenses: {total_expenses}")
    print(f"DEBUG: Retained earnings: {retained_earnings}")
    print(f"DEBUG: Accounts receivable: {accounts_receivable}")
    print(f"DEBUG: Cash: {cash}")
    print(f"DEBUG: Total assets: {total_assets}")
    print(f"DEBUG: Accounts payable: {accounts_payable}")
    print(f"DEBUG: Total liabilities: {total_liabilities}")
    print(f"DEBUG: Owner's equity: {owner_equity}")
    print(f"DEBUG: Balance check (should be 0): {balance_check}")
    
    return {
        'total_assets': float(total_assets),
        'total_liabilities': float(total_liabilities),
        'owner_equity': float(owner_equity),
        'retained_earnings': float(retained_earnings),
        'accounts_receivable': float(accounts_receivable),
        'accounts_payable': float(accounts_payable),
        'cash': float(cash),
        'as_of_date': as_of_date.strftime('%Y-%m-%d'),
        'period': f"As of {as_of_date.strftime('%B %d, %Y')}",
        'balance_check': float(balance_check),
        'debug_info': {
            'total_transactions': transactions.count(),
            'income_transactions': transactions.filter(type='income').count(),
            'expense_transactions': transactions.filter(type='expense').count(),
            'accounting_equation_balanced': balance_check < 0.01,  # Allow for small rounding differences
        }
    }


@login_required
@company_admin_or_permission_required('accounting.view_transaction', raise_exception=True)
def view_report(request, report_id):
    """View a generated financial report. Per-creator: team members can only view reports they created."""
    user = request.user
    company = get_company_profile_for_user(user, request)
    
    if not company:
        messages.error(request, "Company profile not found.")
        return redirect('core:company_profile')
    
    report = get_object_or_404(FinancialReport, id=report_id, company=company)
    if not is_company_admin(user, request) and getattr(report, 'created_by_id', None) != user.pk:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied("You can only view reports you created.")
    txn_qs_report = for_user_queryset(Transaction, request.user, request, account_lookup='company__account').filter(is_void=False, is_deleted=False)
    # Check if there are transactions in the original date range (visibility-scoped)
    original_transactions_count = txn_qs_report.filter(
        transaction_date__range=[report.start_date, report.end_date]
    ).count()
    # If no transactions in original range, extend the range to include recent transactions
    if original_transactions_count == 0:
        latest_transaction = txn_qs_report.order_by('-transaction_date').first()
        
        if latest_transaction:
            # Extend the date range to include the latest transaction
            adjusted_start_date = min(report.start_date, latest_transaction.transaction_date)
            adjusted_end_date = max(report.end_date, latest_transaction.transaction_date)
            
            # Use adjusted dates for calculation
            if report.report_type == 'income_statement':
                fresh_report_data = generate_income_statement(company, adjusted_start_date, adjusted_end_date, request=request)
            elif report.report_type == 'balance_sheet':
                fresh_report_data = generate_balance_sheet(company, adjusted_end_date, request=request)
            else:
                fresh_report_data = report.report_data
            
            # Add note about date adjustment
            fresh_report_data['date_adjusted'] = True
            fresh_report_data['original_period'] = f"{report.start_date} to {report.end_date}"
            fresh_report_data['adjusted_period'] = f"{adjusted_start_date} to {adjusted_end_date}"
        else:
            # No transactions at all, use original data
            if report.report_type == 'income_statement':
                fresh_report_data = generate_income_statement(company, report.start_date, report.end_date, request=request)
            elif report.report_type == 'balance_sheet':
                fresh_report_data = generate_balance_sheet(company, report.end_date, request=request)
            else:
                fresh_report_data = report.report_data
            fresh_report_data['date_adjusted'] = False
    else:
        # Use original date range
        if report.report_type == 'income_statement':
            fresh_report_data = generate_income_statement(company, report.start_date, report.end_date, request=request)
        elif report.report_type == 'balance_sheet':
            fresh_report_data = generate_balance_sheet(company, report.end_date, request=request)
        else:
            fresh_report_data = report.report_data
        fresh_report_data['date_adjusted'] = False
    
    # Debug: visibility-scoped counts and sample
    total_transactions = txn_qs_report.count()
    transactions_in_period = txn_qs_report.filter(
        transaction_date__range=[report.start_date, report.end_date]
    ).count()
    sample_transactions = txn_qs_report.order_by('-transaction_date')[:5]
    context = {
        'report': report,
        'company': company,
        'report_data': fresh_report_data,  # Use fresh data instead of stored data
        'debug_info': {
            'total_transactions': total_transactions,
            'transactions_in_period': transactions_in_period,
            'sample_transactions': sample_transactions,
            'date_range': f"{report.start_date} to {report.end_date}",
            'original_transactions_count': original_transactions_count,
        }
    }
    
    return render(request, 'accounting/view_report.html', context)


def update_transactions_currency(company_profile, new_currency_symbol):
    """Update all existing transactions to use the new currency symbol"""
    from .models import Transaction
    
    # Get all transactions for this company
    transactions = Transaction.objects.filter(company=company_profile)
    
    # Update currency for all transactions
    updated_count = transactions.update(currency=new_currency_symbol)
    
    return updated_count


@login_required
@company_admin_or_permission_required('accounting.change_transaction', raise_exception=True)
@require_POST
@csrf_exempt
def update_accounting_currency(request):
    """Update currency across all accounting transactions"""
    try:
        data = json.loads(request.body)
        currency_code = data.get('currency_code')
        currency_symbol = data.get('currency_symbol')
        
        if not currency_code or not currency_symbol:
            return JsonResponse({'success': False, 'error': 'Currency code and symbol are required'})
        
        # Update company profile currency (works for team members via account's company)
        company_profile = get_company_profile_for_user(request.user, request)
        if not company_profile:
            return JsonResponse({'success': False, 'error': 'Company profile not found'})
        company_profile.currency_code = currency_code
        company_profile.currency_symbol = currency_symbol
        company_profile.save()
        
        # Update all existing transactions to use the new currency
        updated_count = update_transactions_currency(company_profile, currency_symbol)
        
        return JsonResponse({
            'success': True,
            'currency_code': currency_code,
            'currency_symbol': currency_symbol,
            'transactions_updated': updated_count,
            'message': f'Successfully updated {updated_count} transactions to use {currency_code} ({currency_symbol})'
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@company_admin_or_permission_required('accounting.change_transaction', raise_exception=True)
@require_POST
@csrf_exempt
def update_transaction_currencies(request):
    """Update all transaction currencies to match the current company profile currency"""
    try:
        user = request.user
        company = get_company_profile_for_user(user, request)
        
        if not company:
            return JsonResponse({'success': False, 'error': 'Company profile not found'})
        
        # Get current company currency (symbol from company profile)
        current_currency = getattr(company, 'currency_symbol', '₦')
        
        # Update all transactions for this company
        updated_count = update_transactions_currency(company, current_currency)
        
        return JsonResponse({
            'success': True,
            'transactions_updated': updated_count,
            'currency': current_currency,
            'message': f'Successfully updated {updated_count} transactions to use {current_currency}'
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


# ---------------------------------------------------------------------------
# PAGE VIEWS FOR CORE ACCOUNTING MODULES (Chart of Accounts, Journal, Reports)
# These render HTML shells that rely on the JSON APIs for data via AJAX.
# ---------------------------------------------------------------------------


@login_required
@company_admin_or_permission_required('accounting.view_account', raise_exception=True)
def accounting_chart_of_accounts_page(request):
    """Chart of Accounts management page (uses /accounting/api/chart-of-accounts/ via AJAX)."""
    company = get_company_profile_for_user(request.user, request)
    if not company:
        messages.error(request, "Company profile not found.")
        return redirect('core:company_profile')

    form = ChartOfAccountForm()
    context = {
        'form': form,
    }
    return render(request, 'accounting/chart_of_accounts/list.html', context)


@login_required
@company_admin_or_permission_required('accounting.view_journalentry', raise_exception=True)
def accounting_journal_page(request):
    """Journal Entries page shell; entries are loaded via /accounting/api/journal/ endpoints."""
    company = get_company_profile_for_user(request.user, request)
    if not company:
        messages.error(request, "Company profile not found.")
        return redirect('core:company_profile')

    form = JournalEntryForm()
    context = {
        'form': form,
    }
    return render(request, 'accounting/journal/list.html', context)


@login_required
@company_admin_or_permission_required('accounting.view_ledger', raise_exception=True)
def accounting_trial_balance_page(request):
    """Trial Balance report page shell; data loaded via /accounting/api/trial-balance/."""
    company = get_company_profile_for_user(request.user, request)
    if not company:
        messages.error(request, "Company profile not found.")
        return redirect('core:company_profile')

    return render(request, 'accounting/reports/trial_balance.html', {})


@login_required
@company_admin_or_permission_required('accounting.view_ledger', raise_exception=True)
def accounting_profit_loss_page(request):
    """Profit & Loss report page shell; data loaded via /accounting/api/profit-loss/."""
    company = get_company_profile_for_user(request.user, request)
    if not company:
        messages.error(request, "Company profile not found.")
        return redirect('core:company_profile')

    return render(request, 'accounting/reports/profit_loss.html', {})


@login_required
@company_admin_or_permission_required('accounting.view_ledger', raise_exception=True)
def accounting_balance_sheet_page(request):
    """Balance Sheet report page shell; data loaded via /accounting/api/balance-sheet/."""
    company = get_company_profile_for_user(request.user, request)
    if not company:
        messages.error(request, "Company profile not found.")
        return redirect('core:company_profile')

    return render(request, 'accounting/reports/balance_sheet.html', {})


@login_required
@company_admin_or_permission_required('accounting.view_ledger', raise_exception=True)
def accounting_tax_summary_page(request):
    """Tax summary report page shell; data loaded via /accounting/api/tax-summary/."""
    company = get_company_profile_for_user(request.user, request)
    if not company:
        messages.error(request, "Company profile not found.")
        return redirect('core:company_profile')

    return render(request, 'accounting/reports/tax_summary.html', {})


# ---------------------------------------------------------------------------
# API ENDPOINTS (JSON, AJAX-FRIENDLY)
# These endpoints are designed for the /accounting/api/... URL space and
# return JsonResponse payloads suitable for front-end AJAX usage.
# ---------------------------------------------------------------------------


@login_required
@company_admin_or_permission_required('accounting.view_account', raise_exception=True)
def api_chart_of_accounts(request):
    """
    List or create ChartOfAccount entries for the current tenant (company).

    GET  -> list of accounts
    POST -> create a new account (JSON body)
    """
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return JsonResponse({'detail': 'Company profile not found.'}, status=400)

    if request.method == 'GET':
        qs = ChartOfAccount.objects.filter(company=company, is_active=True).order_by('code')
        serializer = ChartOfAccountSerializer(qs, many=True)
        return JsonResponse({'results': serializer.data}, status=200)

    if request.method == 'POST':
        try:
            payload = json.loads(request.body or '{}')
        except json.JSONDecodeError:
            return JsonResponse({'detail': 'Invalid JSON body.'}, status=400)

        serializer = ChartOfAccountSerializer(data=payload)
        if not serializer.is_valid():
            return JsonResponse(serializer.errors, status=400)

        instance = serializer.save(company=company)
        return JsonResponse(ChartOfAccountSerializer(instance).data, status=201)

    return JsonResponse({'detail': 'Method not allowed.'}, status=405)


@login_required
@company_admin_or_permission_required('accounting.add_journalentry', raise_exception=True)
@require_POST
def api_journal_create(request):
    """
    Create a journal entry using the double-entry engine.

    Expected JSON body:
    {
      "date": "2026-03-09",
      "description": "Invoice payment",
      "reference": "JE-0001",
      "source_app": "invoice",
      "source_id": "123",
      "lines": [
        {"account_id": 1, "debit": "1000.00", "credit": "0.00", "description": "..."},
        {"account_id": 2, "debit": "0.00", "credit": "1000.00", "description": "..."}
      ]
    }
    """
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return JsonResponse({'detail': 'Company profile not found.'}, status=400)

    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'detail': 'Invalid JSON body.'}, status=400)

    lines_payload = payload.get('lines') or []
    if not lines_payload:
        return JsonResponse({'detail': 'At least one journal line is required.'}, status=400)

    from .services.accounting_service import JournalLineInput  # local import to avoid circular

    line_inputs = []
    for line in lines_payload:
        account_id = line.get('account') or line.get('account_id')
        try:
            account = ChartOfAccount.objects.get(company=company, id=account_id)
        except ChartOfAccount.DoesNotExist:
            return JsonResponse({'detail': f'Invalid account specified: {account_id}'}, status=400)
        line_inputs.append(
            JournalLineInput(
                account=account,
                debit=Decimal(str(line.get('debit', '0')) or '0'),
                credit=Decimal(str(line.get('credit', '0')) or '0'),
                description=line.get('description') or '',
            )
        )

    try:
        journal = create_journal_entry(
            company=company,
            date=payload.get('date') or timezone.now().date(),
            description=payload.get('description') or '',
            lines=line_inputs,
            source_app=payload.get('source_app') or 'manual',
            source_id=str(payload.get('source_id') or ''),
            reference=payload.get('reference'),
            created_by=request.user,
        )
    except ValueError as exc:
        return JsonResponse({'detail': str(exc)}, status=400)

    serializer = JournalEntrySerializer(journal)
    return JsonResponse(serializer.data, status=201)


@login_required
@company_admin_or_permission_required('accounting.view_journalentry', raise_exception=True)
def api_journal_detail(request, journal_id):
    """Retrieve a single journal entry (with lines) for the current tenant."""
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return JsonResponse({'detail': 'Company profile not found.'}, status=400)

    journal = get_object_or_404(JournalEntry, id=journal_id, company=company)
    serializer = JournalEntrySerializer(journal)
    return JsonResponse(serializer.data, status=200)


@login_required
@company_admin_or_permission_required('accounting.view_journalentry', raise_exception=True)
def api_journal_list(request):
    """
    Return recent journal entries for the current tenant.

    Optional query params:
      - start_date (YYYY-MM-DD)
      - end_date   (YYYY-MM-DD)
      - q          (search in reference/description)
      - limit      (max items, default 20, max 100)
      - offset     (offset for pagination, default 0)
    """
    if request.method != "GET":
        return JsonResponse({"detail": "Method not allowed."}, status=405)

    company = get_company_profile_for_user(request.user, request)
    if not company:
        return JsonResponse({"detail": "Company profile not found."}, status=400)

    journals = JournalEntry.objects.filter(company=company).order_by("-date", "-id")

    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")
    search = request.GET.get("q")

    if start_date:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
            journals = journals.filter(date__gte=start)
        except ValueError:
            return JsonResponse({"detail": "Invalid start_date format. Use YYYY-MM-DD."}, status=400)

    if end_date:
        try:
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
            journals = journals.filter(date__lte=end)
        except ValueError:
            return JsonResponse({"detail": "Invalid end_date format. Use YYYY-MM-DD."}, status=400)

    if search:
        journals = journals.filter(
            Q(reference__icontains=search) | Q(description__icontains=search)
        )

    try:
        limit = int(request.GET.get("limit", 20))
    except (TypeError, ValueError):
        limit = 20
    try:
        offset = int(request.GET.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0

    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    total = journals.count()
    slice_qs = journals[offset : offset + limit]
    data = JournalEntrySerializer(slice_qs, many=True).data

    return JsonResponse(
        {
            "results": data,
            "total": total,
        },
        status=200,
    )


@login_required
@company_admin_or_permission_required('accounting.view_ledger', raise_exception=True)
def api_ledger(request):
    """
    Return ledger lines for the current tenant, optionally filtered by account and date range.

    Query params:
      - account_id (optional)
      - start_date (YYYY-MM-DD, optional)
      - end_date (YYYY-MM-DD, optional)
    """
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return JsonResponse({'detail': 'Company profile not found.'}, status=400)

    entries = LedgerEntry.objects.filter(company=company).select_related('account')

    account_id = request.GET.get('account_id')
    if account_id:
        entries = entries.filter(account_id=account_id)

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    if start_date:
        entries = entries.filter(date__gte=start_date)
    if end_date:
        entries = entries.filter(date__lte=end_date)

    entries = entries.order_by('date', 'id')[:2000]
    serializer = LedgerEntrySerializer(entries, many=True)
    return JsonResponse({'results': serializer.data}, status=200)


def _parse_date_param(value, default=None):
    """Parse YYYY-MM-DD string to date; return default if missing/invalid."""
    if not value:
        return default
    try:
        return datetime.strptime(value.strip()[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return default


@login_required
@company_admin_or_permission_required('accounting.view_ledger', raise_exception=True)
def api_trial_balance(request):
    """
    Return trial balance data using the double-entry ledger.

    Query params:
      - start_date (optional, YYYY-MM-DD)
      - end_date (optional, YYYY-MM-DD)
    """
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return JsonResponse({'detail': 'Company profile not found.'}, status=400)

    start_date = _parse_date_param(request.GET.get('start_date'))
    end_date = _parse_date_param(request.GET.get('end_date'))

    data = de_calculate_trial_balance(
        company=company,
        start_date=start_date,
        end_date=end_date,
    )
    return JsonResponse(data, status=200)


@login_required
@company_admin_or_permission_required('accounting.view_ledger', raise_exception=True)
def api_profit_loss(request):
    """
    Return Profit & Loss summary via double-entry ledger.

    Query params:
      - start_date (optional, YYYY-MM-DD; default: first day of current month)
      - end_date (optional, YYYY-MM-DD; default: today)
    """
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return JsonResponse({'detail': 'Company profile not found.'}, status=400)

    today = timezone.now().date()
    start_date = _parse_date_param(request.GET.get('start_date'))
    end_date = _parse_date_param(request.GET.get('end_date'))
    if not start_date:
        start_date = today.replace(day=1)
    if not end_date:
        end_date = today
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    data = de_generate_profit_loss(
        company=company,
        start_date=start_date,
        end_date=end_date,
    )
    return JsonResponse(data, status=200)


@login_required
@company_admin_or_permission_required('accounting.view_ledger', raise_exception=True)
def api_balance_sheet(request):
    """
    Return Balance Sheet snapshot using double-entry ledger balances.

    Query params:
      - as_of_date (optional, defaults to today)
    """
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return JsonResponse({'detail': 'Company profile not found.'}, status=400)

    as_of_param = request.GET.get('as_of_date')
    if as_of_param:
        try:
            as_of = datetime.strptime(as_of_param, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'detail': 'Invalid as_of_date format, expected YYYY-MM-DD.'}, status=400)
    else:
        as_of = timezone.now().date()

    data = de_generate_balance_sheet(company=company, as_of_date=as_of)
    return JsonResponse(data, status=200)


@login_required
@company_admin_or_permission_required('accounting.view_transaction', raise_exception=True)
def api_accounts_receivable(request):
    """Return a simple Accounts Receivable summary based on outstanding invoices."""
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return JsonResponse({'detail': 'Company profile not found.'}, status=400)

    from apps.invoices.models import Invoice

    qs = Invoice.objects.filter(
        user__account_id=company.account_id,
        status__in=['unpaid', 'partial'],
    )
    total = qs.aggregate(total=Sum('balance_due'))['total'] or 0

    return JsonResponse(
        {
            'total_accounts_receivable': float(total),
            'currency_symbol': company.currency_symbol,
        },
        status=200,
    )


@login_required
@company_admin_or_permission_required('accounting.view_transaction', raise_exception=True)
def api_outstanding_invoices(request):
    """Return unpaid/partial invoice rows for Outstanding card drilldown."""
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return JsonResponse({'detail': 'Company profile not found.'}, status=400)

    from apps.invoices.models import Invoice

    invoice_qs = for_user_queryset(
        Invoice,
        request.user,
        request,
        account_lookup='account',
    ).filter(
        status__in=['unpaid', 'partial'],
        balance_due__gt=0,
    ).order_by('-invoice_date', '-created_at')[:500]

    invoices = []
    for inv in invoice_qs:
        invoices.append(
            {
                'id': inv.id,
                'invoice_number': inv.invoice_number or f'INV-{inv.id}',
                'invoice_date': inv.invoice_date.isoformat() if inv.invoice_date else '',
                'client_name': inv.client_name or '-',
                'status': inv.status or 'unpaid',
                'status_display': inv.get_status_display() or 'Unpaid',
                'grand_total': float(inv.grand_total or 0),
                'amount_paid': float(inv.amount_paid or 0),
                'balance_due': float(inv.balance_due or 0),
                'source_app': 'Invoices',
                'detail_url': f'/invoices/{inv.id}/',
            }
        )

    total_outstanding = sum(item['balance_due'] for item in invoices)

    return JsonResponse(
        {
            'results': invoices,
            'total_outstanding': total_outstanding,
            'currency_symbol': company.currency_symbol,
        },
        status=200,
    )


@login_required
@company_admin_or_permission_required('accounting.view_transaction', raise_exception=True)
def api_accounts_payable(request):
    """
    Return a simple Accounts Payable summary using approved, unpaid expenses.
    """
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return JsonResponse({'detail': 'Company profile not found.'}, status=400)

    from apps.expense.models import Expense

    qs = Expense.objects.filter(
        company=company,
        status__in=['pending', 'approved'],
        payment_date__isnull=True,
    )
    total = qs.aggregate(total=Sum('total_amount'))['total'] or 0

    return JsonResponse(
        {
            'total_accounts_payable': float(total),
            'currency_symbol': company.currency_symbol,
        },
        status=200,
    )


@login_required
@company_admin_or_permission_required('accounting.view_transaction', raise_exception=True)
def api_dashboard(request):
    """
    JSON dashboard endpoint mirroring the main accounting_dashboard but
    returning data only (no HTML).
    """
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return JsonResponse({'detail': 'Company profile not found.'}, status=400)

    # Reuse existing helper to keep monthly Ledger in sync
    sync_ledgers_from_transactions(company)

    now = timezone.now()
    current_month = now.month
    current_year = now.year

    ledger = Ledger.objects.filter(
        company=company,
        year=current_year,
        month=current_month,
    ).first()

    txn_qs = for_user_queryset(
        Transaction,
        request.user,
        request,
        account_lookup='company__account',
    ).filter(is_void=False, is_deleted=False)

    recent_transactions = txn_qs.order_by('-created_at')[:10]
    tx_serializer = TransactionSerializer(recent_transactions, many=True)

    # Simple source breakdown
    source_breakdown = list(
        txn_qs.values('source_app')
        .annotate(total=Sum('net_amount'), count=Count('id'))
        .order_by('-total')
    )
    for item in source_breakdown:
        item['total'] = float(item['total'] or 0)

    return JsonResponse(
        {
            'total_income': float(getattr(ledger, 'total_income', 0)),
            'total_expense': float(getattr(ledger, 'total_expense', 0)),
            'net_profit': float(getattr(ledger, 'net_profit', 0)),
            'recent_transactions': tx_serializer.data,
            'source_breakdown': source_breakdown,
            'currency_symbol': company.currency_symbol,
            'currency_code': company.currency_code,
        },
        status=200,
    )


@login_required
@company_admin_or_permission_required('accounting.view_transaction', raise_exception=True)
def api_transactions(request):
    """
    JSON list endpoint for transactions, with basic filtering.

    Query params mirror TransactionFilterForm where practical.
    """
    txn_qs = for_user_queryset(
        Transaction,
        request.user,
        request,
        account_lookup='company__account',
    ).filter(is_void=False, is_deleted=False)

    tx_type = request.GET.get('transaction_type')
    source_app = request.GET.get('source_app')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if tx_type:
        txn_qs = txn_qs.filter(type=tx_type)
    if source_app:
        txn_qs = txn_qs.filter(source_app=source_app)
    if start_date:
        txn_qs = txn_qs.filter(transaction_date__gte=start_date)
    if end_date:
        txn_qs = txn_qs.filter(transaction_date__lte=end_date)

    txn_qs = txn_qs.order_by('-transaction_date', '-created_at')[:500]
    serializer = TransactionSerializer(txn_qs, many=True)
    return JsonResponse({'results': serializer.data}, status=200)


@login_required
@company_admin_or_permission_required('accounting.view_ledger', raise_exception=True)
def api_tax_summary(request):
    """
    Return a simple tax summary based on TaxRecord entries.

    Query params:
      - period_type (optional: monthly/quarterly/yearly)
    """
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return JsonResponse({'detail': 'Company profile not found.'}, status=400)

    from apps.tax_engine.models import TaxRecord

    qs = TaxRecord.objects.filter(company=company)
    period_type = request.GET.get('period_type')
    if period_type:
        qs = qs.filter(period_type=period_type)

    latest = qs.order_by('-period_end').first()
    if not latest:
        return JsonResponse(
            {
                'has_data': False,
                'total_revenue': 0.0,
                'total_expenses': 0.0,
                'taxable_profit': 0.0,
                'corporate_tax': 0.0,
                'vat_payable': 0.0,
            },
            status=200,
        )

    return JsonResponse(
        {
            'has_data': True,
            'period_type': latest.period_type,
            'period_start': latest.period_start.strftime('%Y-%m-%d'),
            'period_end': latest.period_end.strftime('%Y-%m-%d'),
            'total_revenue': float(latest.total_revenue),
            'total_expenses': float(latest.total_expenses),
            'taxable_profit': float(latest.taxable_profit),
            'corporate_tax': float(latest.corporate_tax),
            'vat_payable': float(latest.vat_payable),
        },
        status=200,
    )


# ---------------------------------------------------------------------------
# CHART OF ACCOUNTS CRUD (Views & API)
# ---------------------------------------------------------------------------

@login_required
@company_admin_or_permission_required('accounting.view_chartofaccount', raise_exception=True)
def chart_of_accounts_list(request):
    """List all chart of accounts entries with grouping by category."""
    company = get_company_profile_for_user(request.user, request)
    if not company:
        messages.error(request, "Company profile not found.")
        return redirect('core:company_profile')
    
    accounts = ChartOfAccount.objects.filter(company=company).select_related('category', 'account_type', 'parent').order_by('category__category_type', 'code')
    
    grouped = {}
    for account in accounts:
        cat = account.category.category_type if account.category else 'other'
        if cat not in grouped:
            grouped[cat] = []
        grouped[cat].append(account)
    
    context = {
        'grouped_accounts': grouped,
        'categories': list(grouped.keys()),
    }
    return render(request, 'accounting/chart_of_accounts/list.html', context)


@login_required
@company_admin_or_permission_required('accounting.add_chartofaccount', raise_exception=True)
def chart_of_accounts_create(request):
    """Create a new chart of accounts entry."""
    company = get_company_profile_for_user(request.user, request)
    if not company:
        messages.error(request, "Company profile not found.")
        return redirect('core:company_profile')
    
    if request.method == 'POST':
        form = ChartOfAccountForm(request.POST, company=company)
        if form.is_valid():
            account = form.save(commit=False)
            account.company = company
            account.save()
            messages.success(request, f"Account '{account.name}' created successfully.")
            return redirect('accounting:chart_of_accounts_list')
    else:
        form = ChartOfAccountForm(company=company)
    
    context = {
        'form': form,
        'title': 'Create Account',
    }
    return render(request, 'accounting/chart_of_accounts/form.html', context)


@login_required
@company_admin_or_permission_required('accounting.change_chartofaccount', raise_exception=True)
def chart_of_accounts_edit(request, account_id):
    """Edit an existing chart of accounts entry."""
    company = get_company_profile_for_user(request.user, request)
    if not company:
        messages.error(request, "Company profile not found.")
        return redirect('core:company_profile')
    
    account = get_object_or_404(ChartOfAccount, id=account_id, company=company)
    
    if request.method == 'POST':
        form = ChartOfAccountForm(request.POST, instance=account, company=company)
        if form.is_valid():
            form.save()
            messages.success(request, f"Account '{account.name}' updated successfully.")
            return redirect('accounting:chart_of_accounts_list')
    else:
        form = ChartOfAccountForm(instance=account, company=company)
    
    context = {
        'form': form,
        'account': account,
        'title': 'Edit Account',
    }
    return render(request, 'accounting/chart_of_accounts/form.html', context)


@login_required
@company_admin_or_permission_required('accounting.delete_chartofaccount', raise_exception=True)
def chart_of_accounts_delete(request, account_id):
    """Delete a chart of accounts entry."""
    company = get_company_profile_for_user(request.user, request)
    if not company:
        messages.error(request, "Company profile not found.")
        return redirect('core:company_profile')
    
    account = get_object_or_404(ChartOfAccount, id=account_id, company=company)
    
    if request.method == 'POST':
        account.delete()
        messages.success(request, f"Account '{account.name}' deleted successfully.")
        return redirect('accounting:chart_of_accounts_list')
    
    context = {
        'account': account,
    }
    return render(request, 'accounting/chart_of_accounts/delete.html', context)


# ---------------------------------------------------------------------------
# JOURNAL ENTRY MANAGEMENT (Edit, Void, Delete)
# ---------------------------------------------------------------------------

@login_required
@company_admin_or_permission_required('accounting.change_journalentry', raise_exception=True)
def journal_entry_edit(request, journal_id):
    """Edit a journal entry (only draft entries can be edited)."""
    company = get_company_profile_for_user(request.user, request)
    if not company:
        messages.error(request, "Company profile not found.")
        return redirect('core:company_profile')
    
    journal = get_object_or_404(JournalEntry, id=journal_id, company=company)
    
    if journal.status != 'draft':
        messages.error(request, "Only draft journal entries can be edited.")
        return redirect('accounting:journal_page')
    
    if request.method == 'POST':
        payload = json.loads(request.body or '{}')
        lines_payload = payload.get('lines') or []
        
        if not lines_payload:
            return JsonResponse({'detail': 'At least one journal line is required.'}, status=400)
        
        from .services.accounting_service import JournalLineInput
        line_inputs = []
        for line in lines_payload:
            account_id = line.get('account') or line.get('account_id')
            try:
                account = ChartOfAccount.objects.get(company=company, id=account_id)
            except ChartOfAccount.DoesNotExist:
                return JsonResponse({'detail': f'Invalid account: {account_id}'}, status=400)
            line_inputs.append(
                JournalLineInput(
                    account=account,
                    debit=Decimal(str(line.get('debit', '0')) or '0'),
                    credit=Decimal(str(line.get('credit', '0')) or '0'),
                    description=line.get('description') or '',
                )
            )
        
        try:
            debits = sum(l.debit for l in line_inputs)
            credits = sum(l.credit for l in line_inputs)
            if debits != credits:
                return JsonResponse({'detail': f'Entry is not balanced: debits={debits}, credits={credits}'}, status=400)
        except Exception as e:
            return JsonResponse({'detail': str(e)}, status=400)
        
        journal.description = payload.get('description') or journal.description
        journal.reference = payload.get('reference') or journal.reference
        journal.date = payload.get('date') or journal.date
        journal.save()
        
        journal.lines.all().delete()
        for line in line_inputs:
            JournalEntryLine.objects.create(
                journal=journal,
                account=line.account,
                description=line.description,
                debit=line.debit,
                credit=line.credit,
            )
        
        return JsonResponse(JournalEntrySerializer(journal).data, status=200)
    
    accounts = ChartOfAccount.objects.filter(company=company, is_active=True).order_by('code')
    accounts_data = [{'id': a.id, 'code': a.code, 'name': a.name} for a in accounts]
    context = {
        'journal': journal,
        'accounts': accounts,
        'accounts_json': accounts_data,
    }
    return render(request, 'accounting/journal/edit.html', context)


@login_required
@company_admin_or_permission_required('accounting.change_journalentry', raise_exception=True)
@require_POST
def journal_entry_void(request, journal_id):
    """Void a journal entry."""
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return JsonResponse({'detail': 'Company profile not found.'}, status=400)
    
    journal = get_object_or_404(JournalEntry, id=journal_id, company=company)
    
    if journal.status == 'void':
        return JsonResponse({'detail': 'Journal entry is already void.'}, status=400)
    
    journal.status = 'void'
    journal.save()
    
    LedgerEntry.objects.filter(journal_line__journal=journal).delete()
    
    messages.success(request, f"Journal entry '{journal.reference}' voided successfully.")
    return JsonResponse({'success': True, 'message': 'Journal entry voided.'}, status=200)


@login_required
@company_admin_or_permission_required('accounting.delete_journalentry', raise_exception=True)
@require_POST
def journal_entry_delete(request, journal_id):
    """Delete a journal entry (only draft entries)."""
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return JsonResponse({'detail': 'Company profile not found.'}, status=400)
    
    journal = get_object_or_404(JournalEntry, id=journal_id, company=company)
    
    if journal.status != 'draft':
        return JsonResponse({'detail': 'Only draft journal entries can be deleted.'}, status=400)
    
    journal.delete()
    
    messages.success(request, f"Journal entry deleted successfully.")
    return JsonResponse({'success': True, 'message': 'Journal entry deleted.'}, status=200)


@login_required
@company_admin_or_permission_required('accounting.add_journalentry', raise_exception=True)
def journal_entry_create_page(request):
    """Create journal entry page (HTML form)."""
    company = get_company_profile_for_user(request.user, request)
    if not company:
        messages.error(request, "Company profile not found.")
        return redirect('core:company_profile')
    
    form = JournalEntryForm()
    accounts = ChartOfAccount.objects.filter(company=company, is_active=True).order_by('code')
    accounts_data = [{'id': a.id, 'code': a.code, 'name': a.name} for a in accounts]
    
    context = {
        'form': form,
        'accounts': accounts,
        'accounts_json': accounts_data,
    }
    return render(request, 'accounting/journal/create.html', context)


# ---------------------------------------------------------------------------
# CASH FLOW STATEMENT
# ---------------------------------------------------------------------------

@login_required
@company_admin_or_permission_required('accounting.view_ledger', raise_exception=True)
def api_cash_flow(request):
    """
    Generate Cash Flow Statement data.
    
    Query params:
      - start_date (optional, YYYY-MM-DD; default: first day of current year)
      - end_date (optional, YYYY-MM-DD; default: today)
    """
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return JsonResponse({'detail': 'Company profile not found.'}, status=400)
    
    today = timezone.now().date()
    start_date = _parse_date_param(request.GET.get('start_date'))
    end_date = _parse_date_param(request.GET.get('end_date'))
    if not start_date:
        start_date = today.replace(month=1, day=1)
    if not end_date:
        end_date = today
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    
    entries = LedgerEntry.objects.filter(
        company=company,
        date__gte=start_date,
        date__lte=end_date,
    ).select_related('account', 'account__category')
    
    operating_inflow = Decimal('0')
    operating_outflow = Decimal('0')
    investing_inflow = Decimal('0')
    investing_outflow = Decimal('0')
    financing_inflow = Decimal('0')
    financing_outflow = Decimal('0')
    
    for entry in entries:
        category_type = getattr(entry.account.category, 'category_type', None)
        debit = entry.debit or Decimal('0')
        credit = entry.credit or Decimal('0')
        amount = debit + credit
        
        if category_type == 'income':
            operating_inflow += credit
        elif category_type == 'expense':
            if 'investment' in entry.account.name.lower() or 'asset' in category_type:
                investing_outflow += debit
            elif 'financing' in entry.account.name.lower() or 'loan' in entry.account.name.lower():
                financing_outflow += debit
            else:
                operating_outflow += debit
        elif category_type == 'asset':
            investing_outflow += debit
            investing_inflow += credit
        elif category_type == 'liability' or category_type == 'equity':
            financing_inflow += credit
            financing_outflow += debit
    
    net_operating = operating_inflow - operating_outflow
    net_investing = investing_inflow - investing_outflow
    net_financing = financing_inflow - financing_outflow
    net_cash_flow = net_operating + net_investing + net_financing
    
    beginning_balance = LedgerEntry.objects.filter(
        company=company,
        date__lt=start_date,
    ).aggregate(total=Sum('debit'))['total'] or Decimal('0')
    beginning_balance -= LedgerEntry.objects.filter(
        company=company,
        date__lt=start_date,
    ).aggregate(total=Sum('credit'))['total'] or Decimal('0')
    
    ending_balance = beginning_balance + net_cash_flow
    
    return JsonResponse({
        'period': f'{start_date} to {end_date}',
        'operating': {
            'inflow': float(operating_inflow),
            'outflow': float(operating_outflow),
            'net': float(net_operating),
        },
        'investing': {
            'inflow': float(investing_inflow),
            'outflow': float(investing_outflow),
            'net': float(net_investing),
        },
        'financing': {
            'inflow': float(financing_inflow),
            'outflow': float(financing_outflow),
            'net': float(net_financing),
        },
        'net_cash_flow': float(net_cash_flow),
        'beginning_balance': float(beginning_balance),
        'ending_balance': float(ending_balance),
    }, status=200)


@login_required
@company_admin_or_permission_required('accounting.view_ledger', raise_exception=True)
def accounting_cash_flow_page(request):
    """Cash Flow Statement page shell."""
    company = get_company_profile_for_user(request.user, request)
    if not company:
        messages.error(request, "Company profile not found.")
        return redirect('core:company_profile')
    
    return render(request, 'accounting/reports/cash_flow.html', {'company': company})


# ---------------------------------------------------------------------------
# EXCEL EXPORT FOR FINANCIAL REPORTS
# ---------------------------------------------------------------------------

@login_required
@company_admin_or_permission_required('accounting.view_financialreport', raise_exception=True)
def export_report_excel(request, report_id):
    """Export financial report as Excel."""
    company = get_company_profile_for_user(request.user, request)
    if not company:
        messages.error(request, "Company profile not found.")
        return redirect('core:company_profile')
    
    report = get_object_or_404(FinancialReport, id=report_id, company=company)
    
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
        
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = report.get_report_type_display() or "Financial Report"
        
        currency_symbol = getattr(company, 'currency_symbol', '₦')
        
        header_font = Font(bold=True, color="FFFFFF", size=12)
        header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
        section_font = Font(bold=True, size=11)
        section_fill = PatternFill(start_color="E8F4FD", end_color="E8F4FD", fill_type="solid")
        money_font = Font(name='Calibri', size=11)
        money_alignment = Alignment(horizontal='right')
        
        thin_border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
        
        row_num = 1
        ws.cell(row=row_num, column=1, value=report.title).font = Font(bold=True, size=14)
        ws.merge_cells(start_row=row_num, start_column=1, end_row=row_num, end_column=2)
        row_num += 1
        
        ws.cell(row=row_num, column=1, value=f"{company.company_name}").font = Font(bold=True, size=12)
        row_num += 1
        
        if report.report_type == 'balance_sheet':
            ws.cell(row=row_num, column=1, value=f"As of: {report.end_date}")
        else:
            ws.cell(row=row_num, column=1, value=f"Period: {report.start_date} to {report.end_date}")
        row_num += 2
        
        ws.cell(row=row_num, column=1, value="Item").font = header_font
        ws.cell(row=row_num, column=1).fill = header_fill
        ws.cell(row=row_num, column=2, value="Amount").font = header_font
        ws.cell(row=row_num, column=2).fill = header_fill
        row_num += 1
        
        data = report.report_data or {}
        
        if report.report_type == 'income_statement':
            items = [
                ('Revenue', data.get('income', 0)),
                ('Expenses', data.get('expenses', 0)),
                ('Net Income', data.get('net_income', 0)),
            ]
        elif report.report_type == 'balance_sheet':
            items = [
                ('ASSETS', None),
                ('Cash', data.get('cash', 0)),
                ('Accounts Receivable', data.get('accounts_receivable', 0)),
                ('Total Assets', data.get('total_assets', 0)),
                ('', None),
                ('LIABILITIES', None),
                ('Accounts Payable', data.get('accounts_payable', 0)),
                ('Total Liabilities', data.get('total_liabilities', 0)),
                ('', None),
                ('EQUITY', None),
                ("Owner's Equity", data.get('owner_equity', 0)),
                ('Retained Earnings', data.get('retained_earnings', 0)),
                ('Total Equity', data.get('owner_equity', 0) + data.get('retained_earnings', 0)),
                ('', None),
                ('Total Liabilities & Equity', data.get('total_liabilities', 0) + data.get('owner_equity', 0) + data.get('retained_earnings', 0)),
            ]
        else:
            items = [(k.replace('_', ' ').title(), v) for k, v in data.items() if isinstance(v, (int, float))]
        
        for label, value in items:
            if label in ('ASSETS', 'LIABILITIES', 'EQUITY'):
                ws.cell(row=row_num, column=1, value=label)
                ws.cell(row=row_num, column=1).font = section_font
                ws.cell(row=row_num, column=1).fill = section_fill
                row_num += 1
            elif value is None:
                row_num += 1
            else:
                ws.cell(row=row_num, column=1, value=label)
                ws.cell(row=row_num, column=2, value=float(value))
                ws.cell(row=row_num, column=2).number_format = f'#,##0.00 "{currency_symbol}"'
                ws.cell(row=row_num, column=2).alignment = money_alignment
                row_num += 1
        
        ws.column_dimensions['A'].width = 30
        ws.column_dimensions['B'].width = 20
        
        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{report.title}_{timezone.now().strftime("%Y%m%d")}.xlsx"'
        
        wb.save(response)
        return response
        
    except ImportError:
        messages.error(request, "Excel export requires openpyxl package. Please install it.")
        return redirect('accounting:view_report', report_id=report.id)
    except Exception as e:
        messages.error(request, f"Error generating Excel: {str(e)}")
        return redirect('accounting:view_report', report_id=report.id)
