from django.shortcuts import render, redirect, get_object_or_404
from business_app.views import get_object_or_unauthorized
from apps.accounts.models import User
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from apps.core.permissions import company_admin_or_permission_required
from django.conf import settings
from django.http import HttpResponse, JsonResponse, HttpResponseForbidden
from django.utils import timezone
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from .models import Product, Order, Leave, ProductStatusHistory, Customer, Store, StoreInventory, StockMovement, Waybill, Receipt, Invoice, get_next_job_order_number
from .forms import ProductForm, OrderForm, LeaveForm, CustomerForm, StoreForm, StoreInventoryForm, StockMovementForm, WaybillForm, ReceiptForm, InvoiceForm, ProductStatusHistoryForm
from apps.accounts.rbac import is_company_admin
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Q, Count, Sum, Avg, Min, Max
from reportlab.platypus import Image, Spacer
import os
from django.template.loader import get_template, render_to_string
from xhtml2pdf import pisa
from django.core.mail import send_mail
from datetime import timedelta
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import permission_required
from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.views.decorators.cache import never_cache
from django.urls import reverse
from datetime import datetime, timedelta
from decimal import Decimal
import time
import logging
from apps.core.utils import get_company_profile_for_user, get_account_users_for_filter
from apps.core.ownership import for_user_queryset, get_account_for_user

logger = logging.getLogger(__name__)


def _apply_no_cache_headers(response):
    """Set no-cache headers on response so job order pages always load fresh (sync with middleware)."""
    if response is None:
        return
    response['Cache-Control'] = (
        'no-store, no-cache, must-revalidate, max-age=0, private, no-transform'
    )
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'


def get_user_currency_symbol(user, request=None):
    """Get currency symbol from user's company profile (works for team members via account)."""
    try:
        if user:
            profile = get_company_profile_for_user(user, request)
            if profile and getattr(profile, 'currency_symbol', None):
                return profile.currency_symbol
    except Exception:
        pass
    return '₦'  # Default fallback

@login_required(login_url='auth:login')
def index(request):
    # Product Statistics - visibility-scoped (admin: all account; team: own)
    product = for_user_queryset(Product, request.user, request, account_lookup='account')
    product_count = product.count()
    
    # Order Statistics - Filter by current user's account (use get_account_for_user for team members)
    account = get_account_for_user(request.user)
    order = Order.objects.filter(customer__account_id=account.id) if account else Order.objects.none()
    order_count = order.count()
    
    # User Statistics - Only count for current user's context
    customer = User.objects.filter(is_active=True, id=request.user.id)
    customer_count = customer.count()
    
    # Role-based statistics (use permission, not role name); scope by account for team consistency
    account_id = account.id if account else None
    if request.user.has_perm('job_orders.manage_leave') and account_id:
        pending_leaves = Leave.objects.filter(employee__account_id=account_id, status='pending').order_by('-created_at')
        pending_leaves_count = pending_leaves.count()
        staff_count = Leave.objects.filter(employee__account_id=account_id).count()
    elif request.user.has_perm('job_orders.manage_leave'):
        pending_leaves = Leave.objects.filter(status='pending').order_by('-created_at')
        pending_leaves_count = pending_leaves.count()
        staff_count = Leave.objects.all().count()
    else:
        pending_leaves = Leave.objects.filter(employee=request.user, status='pending').order_by('-created_at')
        pending_leaves_count = pending_leaves.count()
        staff_count = Leave.objects.filter(employee=request.user).count()

    context = {
        'product': product,
        'product_count': product_count,
        'order_count': order_count,
        'customer_count': customer_count,
        'staff_count': staff_count,
        'pending_leaves': pending_leaves[:5],
        'pending_leaves_count': pending_leaves_count,
    }
    
    return render(request, 'dashboard/index.html', context)

@login_required(login_url='auth:login')
@never_cache
@company_admin_or_permission_required('job_orders.view_product', raise_exception=True)
def products(request):
    # Job Order Layouts URL requires view_jobordertemplate (or company admin)
    if request.resolver_match and request.resolver_match.url_name == 'layout_list':
        if not is_company_admin(request) and not request.user.has_perm('job_orders.view_jobordertemplate'):
            return HttpResponseForbidden('You do not have permission to view Job Order Layouts.')
    # Initialize form with user and company currency for price label
    _currency = get_user_currency_symbol(request.user, request)
    form = ProductForm(user=request.user, currency_symbol=_currency)
    
    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        try:
            if not is_company_admin(request) and not request.user.has_perm('job_orders.add_product'):
                if is_ajax:
                    return JsonResponse({'success': False, 'message': 'You do not have permission to create job orders.'}, status=403)
                return HttpResponseForbidden('You do not have permission to create job orders.')
            form = ProductForm(request.POST, request.FILES, user=request.user, currency_symbol=_currency)
            if form.is_valid():
                product = form.save(commit=False)
                product.created_by = request.user
                # Ensure account is set so product appears in list for team members (linked_user may have no account_id)
                account = get_account_for_user(request.user)
                if account:
                    product.account_id = account.id
                product.calculate_total()
                if 'image' in request.FILES:
                    product.image = request.FILES['image']
                # Save with auto-generated unique job_order; retry if duplicate (race condition)
                for _ in range(3):
                    try:
                        product.save()
                        break
                    except IntegrityError as e:
                        if 'job_order' in str(e).lower() or 'unique' in str(e).lower():
                            product.job_order = None  # force regenerate on next save()
                        else:
                            raise

                if is_ajax:
                    from apps.accounts.rbac import is_company_admin as _is_company_admin
                    row_html = render_to_string('job_orders/includes/product_table_row.html', {
                        'product': product,
                        'row_index': 1,
                        'currency_symbol': get_user_currency_symbol(request.user, request),
                        'is_company_admin': _is_company_admin(request),
                    }, request=request)
                    base_after = for_user_queryset(Product, request.user, request, account_lookup='account')
                    account_id = account.id if account else None
                    customer_count = base_after.exclude(organization_name='').exclude(organization_name__isnull=True).values('organization_name').distinct().count()
                    order_count = Order.objects.filter(customer__account_id=account_id).count() if account_id else 0
                    return JsonResponse({
                        'success': True,
                        'row_html': row_html,
                        'product_id': product.id,
                        'message': f'Job Order {product.job_order} has been added and is pending approval',
                        'product_count': base_after.count(),
                        'customer_count': customer_count,
                        'order_count': order_count,
                        'pending_count': base_after.filter(approval_status='pending').count(),
                        'approved_count': base_after.filter(approval_status='approved').count(),
                        'rejected_count': base_after.filter(approval_status='rejected').count(),
                    })
                messages.success(request, f'Job Order {product.job_order} has been added and is pending approval')
                return redirect(reverse('job_orders:products') + '?_=' + str(int(time.time() * 1000)))
            if is_ajax:
                err_msgs = []
                for f, errs in form.errors.items():
                    for e in errs:
                        err_msgs.append(str(e))
                return JsonResponse({
                    'success': False,
                    'message': ' '.join(err_msgs) if err_msgs else 'Please correct the form and try again.',
                }, status=400)
        except Exception as ex:
            if is_ajax:
                logger.exception('Add job order failed')
                return JsonResponse({
                    'success': False,
                    'message': 'Could not add job order. Please try again.',
                    'error': str(ex),
                }, status=500)
            raise

    # GET: list products
    # Get search and filter parameters
    search_query = request.GET.get('search', '')
    filter_status = request.GET.get('status', '')
    
    # Base queryset - visibility-scoped only (for dashboard cards: accurate totals regardless of filters). Exclude soft-deleted (offline sync).
    account_id = getattr(request.user, 'account_id', None)
    base_products = for_user_queryset(Product, request.user, request, account_lookup='account').filter(is_deleted=False)

    # Filtered queryset for table (search, status, created_by).
    # Order by date_created only (no TruncSecond/tz in DB) to avoid "invalid datetime / time zone definitions" on MySQL/SQLite.
    products = base_products.select_related('created_by').order_by('-date_created')
    
    if search_query:
        products = products.filter(
            Q(job_order__icontains=search_query) |
            Q(organization_name__icontains=search_query) |
            Q(job_title__icontains=search_query)
        )
    
    if filter_status:
        products = products.filter(approval_status=filter_status)
    
    if is_company_admin(request):
        created_by_id = request.GET.get('created_by', '').strip()
        if created_by_id:
            try:
                products = products.filter(created_by_id=int(created_by_id))
            except (ValueError, TypeError):
                pass
    
    # Pagination - Show 5 products per page
    paginator = Paginator(products, 5)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Dashboard stats: always from base (unfiltered) queryset so cards show accurate totals
    product_count = base_products.count()
    pending_count = base_products.filter(approval_status='pending').count()
    approved_count = base_products.filter(approval_status='approved').count()
    rejected_count = base_products.filter(approval_status='rejected').count()
    # Active customers = distinct organization_name from job orders (non-empty)
    customer_count = base_products.exclude(organization_name='').exclude(organization_name__isnull=True).values('organization_name').distinct().count()
    # Company-scoped order count (Order.customer is User; filter by account)
    order_count = Order.objects.filter(customer__account_id=account_id).count() if account_id else 0

    from apps.accounts.rbac import is_company_admin as _is_company_admin
    account_users = get_account_users_for_filter(request.user) if _is_company_admin(request) else []
    context = {
        'products': page_obj,
        'form': form,
        'customer_count': customer_count,
        'product_count': product_count,
        'order_count': order_count,
        'pending_count': pending_count,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
        'currency_symbol': get_user_currency_symbol(request.user, request),
        'account_users': account_users,
        'next_job_order_number': get_next_job_order_number(),
    }

    try:
        response = render(request, 'job_orders/products.html', context)
        _apply_no_cache_headers(response)
        return response
    except ValueError as e:
        # Database returned an invalid datetime / time zone definitions (e.g. MySQL without tz tables).
        # Rebuild products list with no datetime-based ordering so no tz conversion runs in DB.
        err_msg = str(e).lower()
        if 'datetime' in err_msg or 'time zone' in err_msg:
            products_safe = base_products.select_related('created_by').order_by('-id')
            if search_query:
                products_safe = products_safe.filter(
                    Q(job_order__icontains=search_query)
                    | Q(organization_name__icontains=search_query)
                    | Q(job_title__icontains=search_query)
                )
            if filter_status:
                products_safe = products_safe.filter(approval_status=filter_status)
            if is_company_admin(request):
                created_by_id = request.GET.get('created_by', '').strip()
                if created_by_id:
                    try:
                        products_safe = products_safe.filter(created_by_id=int(created_by_id))
                    except (ValueError, TypeError):
                        pass
            page_obj = Paginator(products_safe, 5).get_page(page_number)
            context['products'] = page_obj
            response = render(request, 'job_orders/products.html', context)
            _apply_no_cache_headers(response)
        else:
            raise

    return response

@login_required
@company_admin_or_permission_required('job_orders.can_approve_jobs', raise_exception=True)
def approve_product(request, product_id):
    """Update product approval status via Ajax. Requires can_approve_jobs permission."""
    try:
        # Users can only approve their own products
        qs = for_user_queryset(Product, request.user, request, account_lookup='account')
        product, response = get_object_or_unauthorized(request, qs, id=product_id)
        if response:
            return response
        action = request.POST.get('action')
        
        if action in ['approved', 'pending', 'rejected']:
            product.approval_status = action
            if action == 'approved':
                product.approved_by = request.user
            elif action in ['pending', 'rejected']:
                product.approved_by = None
            product.save()
            
            # Log the status change
            ProductStatusHistory.objects.create(
                product=product,
                status=action,
                updated_by=request.user
            )
            
            # Safely get user names with defensive programming
            approved_by_name = None
            created_by_name = 'Not specified'
            
            if product.approved_by:
                try:
                    approved_by_name = product.approved_by.get_full_name()
                except AttributeError:
                    approved_by_name = product.approved_by.email if hasattr(product.approved_by, 'email') else str(product.approved_by)
            
            if product.created_by:
                try:
                    created_by_name = product.created_by.get_full_name()
                except AttributeError:
                    created_by_name = product.created_by.email if hasattr(product.created_by, 'email') else str(product.created_by)
            
            # Return updated approval counts so dashboard cards update without refresh
            account_id = getattr(request.user, 'account_id', None)
            base_products = for_user_queryset(Product, request.user, request, account_lookup='account')
            pending_count = base_products.filter(approval_status='pending').count()
            approved_count = base_products.filter(approval_status='approved').count()
            rejected_count = base_products.filter(approval_status='rejected').count()
            customer_count = base_products.exclude(organization_name='').exclude(organization_name__isnull=True).values('organization_name').distinct().count()
            order_count = Order.objects.filter(customer__account_id=account_id).count() if account_id else 0
            return JsonResponse({
                'success': True,
                'message': f'Product status updated to {action}',
                'approved_by': approved_by_name,
                'created_by': created_by_name,
                'product_count': base_products.count(),
                'customer_count': customer_count,
                'order_count': order_count,
                'pending_count': pending_count,
                'approved_count': approved_count,
                'rejected_count': rejected_count,
            })
        
        return JsonResponse({
            'success': False,
            'message': 'Invalid action specified'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error updating approval status: {str(e)}'
        })

@login_required
@company_admin_or_permission_required('job_orders.change_product', raise_exception=True)
def update_delivery_dates(request, product_id):
    """Update delivery dates via Ajax"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'})
    qs = for_user_queryset(Product, request.user, request, account_lookup='account')
    product, response = get_object_or_unauthorized(request, qs, id=product_id)
    if response:
        return response
    try:
        from datetime import datetime
        
        estimated_date = request.POST.get('estimated_delivery_date')
        actual_date = request.POST.get('actual_delivery_date')
        
        if estimated_date and estimated_date.strip():
            try:
                # Parse the date string and convert to date object
                product.estimated_delivery_date = datetime.strptime(estimated_date, '%Y-%m-%d').date()
            except ValueError:
                return JsonResponse({
                    'success': False,
                    'message': 'Invalid estimated delivery date format. Please use YYYY-MM-DD format.'
                })
        elif estimated_date == '':
            # Clear the date if empty string is passed
            product.estimated_delivery_date = None
            
        if actual_date and actual_date.strip():
            try:
                # Parse the date string and convert to date object
                product.actual_delivery_date = datetime.strptime(actual_date, '%Y-%m-%d').date()
            except ValueError:
                return JsonResponse({
                    'success': False,
                    'message': 'Invalid actual delivery date format. Please use YYYY-MM-DD format.'
                })
        elif actual_date == '':
            # Clear the date if empty string is passed
            product.actual_delivery_date = None
            
        # Calculate cycle time
        product.calculate_cycle_time()
        product.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Delivery dates updated successfully',
            'estimated_delivery_date': product.estimated_delivery_date.strftime('%Y-%m-%d') if product.estimated_delivery_date else '',
            'actual_delivery_date': product.actual_delivery_date.strftime('%Y-%m-%d') if product.actual_delivery_date else '',
            'cycle_time': str(product.cycle_time) if product.cycle_time else '',
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error updating delivery dates: {str(e)}'
        })

@login_required
@never_cache
@company_admin_or_permission_required('job_orders.view_product', raise_exception=True)
def product_detail(request, pk):
    qs = for_user_queryset(Product, request.user, request, account_lookup='account')
    product, response = get_object_or_unauthorized(request, qs, id=pk)
    if response:
        return response
    _currency = get_user_currency_symbol(request.user, request)
    if request.method == 'POST':
        if not is_company_admin(request) and not request.user.has_perm('job_orders.change_product'):
            return HttpResponseForbidden('You do not have permission to edit this job order.')
        form = ProductForm(
            data=request.POST,
            files=request.FILES,
            instance=product,
            user=request.user,
            currency_symbol=_currency
        )
        if form.is_valid():
            product = form.save(commit=False)
            product.updated_by = request.user
            product.calculate_total()
            product.save()
            messages.success(request, 'Product updated successfully!')
            return redirect(reverse('job_orders:product_detail', kwargs={'pk': pk}) + '?_=' + str(int(time.time() * 1000)))
    else:
        form = ProductForm(instance=product, user=request.user, currency_symbol=_currency)
    
    context = {
        'product': product,
        'form': form,
        'currency_symbol': _currency,
    }
    resp = render(request, 'job_orders/product_detail.html', context)
    _apply_no_cache_headers(resp)
    return resp

@login_required
@never_cache
@company_admin_or_permission_required('job_orders.change_product', raise_exception=True)
def product_edit(request, pk):
    qs = for_user_queryset(Product, request.user, request, account_lookup='account')
    product, response = get_object_or_unauthorized(request, qs, id=pk)
    if response:
        return response
    _currency = get_user_currency_symbol(request.user, request)
    if request.method == 'POST':
        form = ProductForm(
            data=request.POST,
            files=request.FILES,
            instance=product,
            user=request.user,
            currency_symbol=_currency
        )
        if form.is_valid():
            product = form.save(commit=False)
            # Preserve the original created_by if it exists
            if not product.created_by:
                product.created_by = request.user
            product.updated_by = request.user
            product.calculate_total()
            product.save()
            messages.success(request, 'Product updated successfully!')
            return redirect(reverse('job_orders:product_detail', kwargs={'pk': pk}) + '?_=' + str(int(time.time() * 1000)))
    else:
        form = ProductForm(instance=product, user=request.user, currency_symbol=_currency)
    
    context = {
        'product': product,
        'form': form,
        'currency_symbol': _currency,
    }
    resp = render(request, 'job_orders/product_edit.html', context)
    _apply_no_cache_headers(resp)
    return resp

@login_required
@never_cache
@company_admin_or_permission_required('job_orders.delete_product', raise_exception=True)
def product_delete(request, pk):
    qs = for_user_queryset(Product, request.user, request, account_lookup='account')
    product, response = get_object_or_unauthorized(request, qs, id=pk)
    if response:
        return response
    if request.method == 'POST':
        product_id = product.id
        product.delete()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            base_after = for_user_queryset(Product, request.user, request, account_lookup='account')
            account_id = getattr(request.user, 'account_id', None)
            customer_count = base_after.exclude(organization_name='').exclude(organization_name__isnull=True).values('organization_name').distinct().count()
            order_count = Order.objects.filter(customer__account_id=account_id).count() if account_id else 0
            return JsonResponse({
                'success': True,
                'product_id': product_id,
                'message': 'Product deleted successfully!',
                'product_count': base_after.count(),
                'customer_count': customer_count,
                'order_count': order_count,
                'pending_count': base_after.filter(approval_status='pending').count(),
                'approved_count': base_after.filter(approval_status='approved').count(),
                'rejected_count': base_after.filter(approval_status='rejected').count(),
            })
        messages.success(request, 'Product deleted successfully!')
        return redirect(reverse('job_orders:products') + '?_=' + str(int(time.time() * 1000)))
    context = {
        'product': product,
        'currency_symbol': get_user_currency_symbol(request.user, request),
    }
    resp = render(request, 'job_orders/product_delete.html', context)
    _apply_no_cache_headers(resp)
    return resp

@login_required
@never_cache
@company_admin_or_permission_required('job_orders.view_product', raise_exception=True)
def product_view(request, job_id):
    qs = for_user_queryset(Product, request.user, request, account_lookup='account')
    product, response = get_object_or_unauthorized(request, qs, job_order=job_id)
    if response:
        return response
    # Get status history for this product
    status_history = ProductStatusHistory.objects.filter(product=product, is_active=True).order_by('-created_at')
    
    # Job-order-specific stats for the header cards on this detail page (account-scoped for accuracy)
    account_id = getattr(request.user, 'account_id', None)
    orders_for_product = Order.objects.filter(product=product)
    if account_id:
        orders_for_product = orders_for_product.filter(customer__account_id=account_id)
    order_count_detail = orders_for_product.count()
    pending_count = 1 if product.approval_status == 'pending' else 0
    approved_count = 1 if product.approval_status == 'approved' else 0
    rejected_count = 1 if product.approval_status == 'rejected' else 0
    
    context = {
        'product': product,
        'status_history': status_history,
        'currency_symbol': get_user_currency_symbol(request.user, request),
        'job_order_detail_view': True,
        'product_count': 1,
        'customer_count': 1,
        'order_count': order_count_detail,
        'pending_count': pending_count,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
        'status_updates_count': status_history.count(),
    }
    resp = render(request, 'job_orders/product_view.html', context)
    _apply_no_cache_headers(resp)
    return resp


@login_required
@never_cache
@company_admin_or_permission_required('job_orders.print_product', raise_exception=True)
def product_view_print(request, job_id):
    """Print-friendly job order view by job_id (same format as invoice print: A4/A5, zoom to one page)."""
    qs = for_user_queryset(Product, request.user, request, account_lookup='account')
    product, response = get_object_or_unauthorized(request, qs, job_order=job_id)
    if response:
        return response
    company_profile = get_company_profile_for_user(request.user, request)
    company_logo = company_profile.logo.url if company_profile and company_profile.logo else None
    company_signature = company_profile.signature.url if company_profile and company_profile.signature else None
    theme_primary_color = getattr(company_profile, 'primary_color', '#1976d2') if company_profile else '#1976d2'
    theme_secondary_color = getattr(company_profile, 'secondary_color', '#f8f9fa') if company_profile else '#f8f9fa'
    theme_accent_color = getattr(company_profile, 'accent_color', '#e9ecef') if company_profile else '#e9ecef'
    theme_text_color = getattr(company_profile, 'text_color', '#333333') if company_profile else '#333333'
    context = {
        'product': product,
        'currency_symbol': get_user_currency_symbol(request.user, request),
        'company_profile': company_profile,
        'company_logo': company_logo,
        'company_signature': company_signature,
        'is_company_admin': is_company_admin(request),
        'theme_primary_color': theme_primary_color,
        'theme_secondary_color': theme_secondary_color,
        'theme_accent_color': theme_accent_color,
        'theme_text_color': theme_text_color,
    }
    resp = render(request, 'job_orders/product_view_print.html', context)
    _apply_no_cache_headers(resp)
    return resp


@login_required
@never_cache
@company_admin_or_permission_required('job_orders.print_product', raise_exception=True)
def product_print(request, pk):
    """Print-friendly view of a product (requires job_orders.print_product)."""
    qs = for_user_queryset(Product, request.user, request, account_lookup='account')
    product, response = get_object_or_unauthorized(request, qs, id=pk)
    if response:
        return response
    from apps.core.utils import get_company_profile_for_user
    company_profile = get_company_profile_for_user(request.user, request)
    context = {
        'product': product,
        'joborder': product,  # Alias for manufacturing templates
        'currency_symbol': get_user_currency_symbol(request.user, request),
        'company_profile': company_profile,
        'company_logo': company_profile.logo.url if company_profile and company_profile.logo else None,
        'company_signature': company_profile.signature.url if company_profile and company_profile.signature else None,
    }
    resp = render(request, 'job_orders/product_print.html', context)
    _apply_no_cache_headers(resp)
    return resp


@login_required
@company_admin_or_permission_required('job_orders.download_product', raise_exception=True)
def export_products_pdf(request):
    products_qs = for_user_queryset(Product, request.user, request, account_lookup='account').filter(is_deleted=False).order_by('-date_created')
    products = list(products_qs)

    from apps.accounts.rbac import is_company_admin as _is_company_admin
    from apps.core.utils import get_currency_info, get_company_context
    company_context = get_company_context(request.user, request)
    currency_symbol = company_context.get('currency_symbol') or get_user_currency_symbol(request.user, request)
    currency_code = company_context.get('currency_code') or 'NGN'
    currency_info = get_currency_info(currency_code)
    currency_display = (currency_info.get('name') if currency_info else None) or currency_code

    pending_count = sum(1 for p in products if p.approval_status == 'pending')
    approved_count = sum(1 for p in products if p.approval_status == 'approved')
    rejected_count = sum(1 for p in products if p.approval_status == 'rejected')
    total_value = sum((p.total or 0) for p in products)

    context = {
        'products': products,
        'currency_symbol': currency_symbol,
        'currency_code': currency_code,
        'currency_display': currency_display,
        'is_company_admin': _is_company_admin(request),
        'pending_count': pending_count,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
        'total_value': total_value,
    }
    html = render_to_string('job_orders/products_pdf.html', context, request=request)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="products_report.pdf"'
    import io
    dest = io.BytesIO()
    pisa_status = pisa.pisaDocument(io.BytesIO(html.encode('utf-8')), dest, encoding='utf-8')
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')
    response.write(dest.getvalue())
    return response

@login_required
@company_admin_or_permission_required('job_orders.download_product', raise_exception=True)
def export_single_product_pdf(request, job_id):
    qs = for_user_queryset(Product, request.user, request, account_lookup='account')
    product, response = get_object_or_unauthorized(request, qs, job_order=job_id)
    if response:
        return response
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="product_{job_id}.pdf"'
    
    from apps.accounts.rbac import is_company_admin as _is_company_admin
    template = get_template('job_orders/product_pdf.html')
    html = template.render({
        'product': product,
        'currency_symbol': get_user_currency_symbol(request.user, request),
        'is_company_admin': _is_company_admin(request),
    })
    
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response

@login_required
@company_admin_or_permission_required('job_orders.download_product', raise_exception=True)
def export_product_view_pdf(request, job_id):
    qs = for_user_queryset(Product, request.user, request, account_lookup='account')
    product, response = get_object_or_unauthorized(request, qs, job_order=job_id)
    if response:
        return response
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="product_view_{job_id}.pdf"'
    
    from apps.accounts.rbac import is_company_admin as _is_company_admin
    template = get_template('job_orders/product_view_pdf.html')
    html = template.render({
        'product': product,
        'currency_symbol': get_user_currency_symbol(request.user, request),
        'is_company_admin': _is_company_admin(request),
    })
    
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response

@login_required
@company_admin_or_permission_required('job_orders.change_product', raise_exception=True)
def update_production_status(request):
    if request.method == 'POST':
        product_id = request.POST.get('product_id')
        new_status = request.POST.get('new_status')
        priority = request.POST.get('priority', 1)  # Default to normal priority
        
        try:
            qs = for_user_queryset(Product, request.user, request, account_lookup='account')
            product, response = get_object_or_unauthorized(request, qs, id=product_id)
            if response:
                return response
            history = ProductStatusHistory.objects.create(
                product=product,
                status=new_status,
                priority=int(priority),
                updated_by=request.user
            )
            can_edit = request.user.has_perm('job_orders.change_product')
            can_delete = request.user.has_perm('job_orders.delete_product')
            status_item_html = render_to_string(
                'job_orders/includes/status_history_item.html',
                {'status': history, 'status_number': 1, 'can_edit': can_edit, 'can_delete': can_delete},
                request=request
            )
            return JsonResponse({
                'success': True,
                'message': 'Status updated successfully',
                'status_item_html': status_item_html,
                'status_id': history.id
            })
        except Product.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Product not found'})
        except ValueError:
            return JsonResponse({'success': False, 'message': 'Invalid priority value'})
    
    return JsonResponse({'success': False, 'message': 'Invalid request method'})

@login_required
@company_admin_or_permission_required('job_orders.change_product', raise_exception=True)
def delete_status_history(request, history_id):
    try:
        history = ProductStatusHistory.objects.get(id=history_id)
        # Check if user owns the product or created the status
        if (request.user.is_superuser or 
            history.updated_by == request.user or 
            history.product.created_by == request.user):
            history.delete()
            return JsonResponse({'success': True, 'message': 'Status update deleted successfully'})
        else:
            return JsonResponse({'success': False, 'message': 'You do not have permission to delete this status update'})
    except ProductStatusHistory.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Status update not found'})

@login_required
@company_admin_or_permission_required('job_orders.change_product', raise_exception=True)
def edit_status_history(request, history_id):
    if request.method == 'POST':
        try:
            history = ProductStatusHistory.objects.get(id=history_id)
            # Check if user owns the product or created the status
            if (request.user.is_superuser or 
                history.updated_by == request.user or 
                history.product.created_by == request.user):
                new_status = request.POST.get('new_status')
                new_priority = request.POST.get('priority', history.priority)
                
                # Update the status history
                history.status = new_status
                history.priority = int(new_priority)
                history.save()
                
                # If this is the most recent status update, also update the product's production_status
                latest_history = ProductStatusHistory.objects.filter(
                    product=history.product, 
                    is_active=True
                ).order_by('-created_at').first()
                
                if latest_history and latest_history.id == history.id:
                    # This is the most recent status, update the product
                    history.product.production_status = new_status
                    history.product.production_status_date = history.created_at
                    history.product.updated_by = request.user
                    history.product.save()
                
                return JsonResponse({
                    'success': True, 
                    'message': 'Status update edited successfully',
                    'new_status': new_status,
                    'new_priority': int(new_priority),
                    'new_priority_display': history.get_priority_display()
                })
            else:
                return JsonResponse({'success': False, 'message': 'You do not have permission to edit this status update'})
        except ProductStatusHistory.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Status update not found'})
        except ValueError:
            return JsonResponse({'success': False, 'message': 'Invalid priority value'})
    
    return JsonResponse({'success': False, 'message': 'Invalid request method'})

# Customer views
# Known gap: job_orders.Customer has no company/account FK — list restricted to company admin only until schema fix.
@login_required
@never_cache
def customer_list(request):
    if not is_company_admin(request):
        customers = Customer.objects.none()
    else:
        customers = Customer.objects.all().order_by('-created_at')
    context = {'customers': customers}
    resp = render(request, 'job_orders/customer_list.html', context)
    _apply_no_cache_headers(resp)
    return resp

@login_required
@never_cache
def customer_create(request):
    if request.method == 'POST':
        form = CustomerForm(request.POST)
        if form.is_valid():
            customer = form.save()
            messages.success(request, 'Customer created successfully!')
            return redirect(reverse('job_orders:customer_list') + '?_=' + str(int(time.time() * 1000)))
    else:
        form = CustomerForm()
    
    context = {'form': form}
    resp = render(request, 'job_orders/customer_form.html', context)
    _apply_no_cache_headers(resp)
    return resp

# Store views
# Known gap: job_orders.Store has no company/account FK — list restricted to company admin only until schema fix.
@login_required
@never_cache
def store_list(request):
    if not is_company_admin(request):
        stores = Store.objects.none()
    else:
        stores = Store.objects.all().order_by('-created_at')
    context = {'stores': stores}
    resp = render(request, 'job_orders/store_list.html', context)
    _apply_no_cache_headers(resp)
    return resp

@login_required
@never_cache
def store_create(request):
    if request.method == 'POST':
        form = StoreForm(request.POST)
        if form.is_valid():
            store = form.save()
            messages.success(request, 'Store created successfully!')
            return redirect(reverse('job_orders:store_list') + '?_=' + str(int(time.time() * 1000)))
    else:
        form = StoreForm()
    
    context = {'form': form}
    resp = render(request, 'job_orders/store_form.html', context)
    _apply_no_cache_headers(resp)
    return resp

# Order views
@login_required
@never_cache
def order_list(request):
    account = get_account_for_user(request.user)
    orders = Order.objects.filter(customer__account_id=account.id).order_by('-date_created') if account else Order.objects.none()
    context = {
        'orders': orders,
        'currency_symbol': get_user_currency_symbol(request.user, request),
    }
    resp = render(request, 'job_orders/order_list.html', context)
    _apply_no_cache_headers(resp)
    return resp

@login_required
@never_cache
def order_create(request):
    if request.method == 'POST':
        form = OrderForm(request.POST)
        if form.is_valid():
            order = form.save(commit=False)
            order.save()
            messages.success(request, 'Order created successfully!')
            return redirect(reverse('job_orders:order_list') + '?_=' + str(int(time.time() * 1000)))
    else:
        form = OrderForm()
    
    context = {'form': form}
    resp = render(request, 'job_orders/order_form.html', context)
    _apply_no_cache_headers(resp)
    return resp

# Leave views (use permission for "see all"; no is_staff/is_superuser); scope by account when manage_leave
@login_required
@never_cache
def leave_list(request):
    account = get_account_for_user(request.user)
    account_id = account.id if account else None
    if request.user.has_perm('job_orders.manage_leave') and account_id:
        leaves = Leave.objects.filter(employee__account_id=account_id).order_by('-created_at')
    elif request.user.has_perm('job_orders.manage_leave'):
        leaves = Leave.objects.all().order_by('-created_at')
    else:
        leaves = Leave.objects.filter(employee=request.user).order_by('-created_at')
    
    context = {'leaves': leaves}
    resp = render(request, 'job_orders/leave_list.html', context)
    _apply_no_cache_headers(resp)
    return resp

@login_required
@never_cache
def leave_create(request):
    if request.method == 'POST':
        form = LeaveForm(request.POST)
        if form.is_valid():
            leave = form.save(commit=False)
            leave.employee = request.user
            leave.save()
            messages.success(request, 'Leave request submitted successfully!')
            return redirect(reverse('job_orders:leave_list') + '?_=' + str(int(time.time() * 1000)))
    else:
        form = LeaveForm()
    
    context = {'form': form}
    resp = render(request, 'job_orders/leave_form.html', context)
    _apply_no_cache_headers(resp)
    return resp


@login_required
@company_admin_or_permission_required('job_orders.change_order', raise_exception=True)
@require_http_methods(["POST"])
@csrf_exempt
def update_job_order_currency(request):
    """Update currency across all job order features"""
    try:
        import json
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
        
        # Update all job order products to trigger recalculation
        products = for_user_queryset(Product, request.user, request, account_lookup='account')
        updated_products = 0
        
        for product in products:
            # Trigger save to update currency displays
            product.save()
            updated_products += 1
        
        # Update all orders (use get_account_for_user for team members)
        account = get_account_for_user(request.user)
        orders = Order.objects.filter(customer__account_id=account.id) if account else Order.objects.none()
        updated_orders = 0
        
        for order in orders:
            # Trigger save to update currency displays
            order.save()
            updated_orders += 1
        
        # Update accounting transactions if they exist
        transactions_updated = 0
        try:
            from apps.accounting.models import Transaction
            transactions_updated = Transaction.objects.filter(
                company=company_profile,
                source_app='job_order'
            ).update(currency=currency_symbol)
        except ImportError:
            # Accounting app might not be installed
            pass
        except Exception as e:
            print(f"Warning: Failed to update job order transactions: {e}")
        
        return JsonResponse({
            'success': True,
            'currency_code': currency_code,
            'currency_symbol': currency_symbol,
            'products_updated': updated_products,
            'orders_updated': updated_orders,
            'transactions_updated': transactions_updated,
            'message': f'Successfully updated job order currency to {currency_code} ({currency_symbol}). {updated_products} products, {updated_orders} orders, and {transactions_updated} transactions updated.'
        })
        
    except json.JSONDecodeError as e:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data provided'})
    except Exception as e:
        import traceback
        print(f"Job order currency update error: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        return JsonResponse({'success': False, 'error': f'Failed to update job order currency: {str(e)}'})