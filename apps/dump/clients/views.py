from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse
from business_app.views import get_object_or_unauthorized
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.db import models
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.urls import reverse
from datetime import date, timedelta
import calendar

from .models import Client
from .forms import ClientForm
from apps.core.ownership import for_user_queryset
from apps.core.permissions import company_admin_or_permission_required
from apps.core.utils import get_company_profile_for_user, apply_no_cache_headers


@login_required
@permission_required('clients.view_client', raise_exception=True)
def client_list(request):
    """List all clients: auto-discovered from all apps (Invoices, Receipts, Quotations, Waybills, Requisitions) and merged; real-time sync on each load."""
    from apps.core.utils import get_company_profile_for_user
    from apps.clients.discovery import sync_discovered_clients

    discovery_stats = {'synced': 0, 'created': 0, 'updated': 0}
    try:
        clients, discovery_stats = sync_discovered_clients(request.user, request)
        clients = clients.select_related('created_by')
    except Exception:
        clients = for_user_queryset(Client, request.user, request, account_lookup='company__account').select_related('created_by')

    try:
        search = (request.GET.get('search') or '').strip()
        if search:
            search_q = (
                models.Q(name__icontains=search) |
                models.Q(email__icontains=search) |
                models.Q(phone__icontains=search) |
                models.Q(address__icontains=search) |
                models.Q(source_record_label__icontains=search)
            )
            try:
                search_q |= models.Q(other_sources__icontains=search)
            except Exception:
                pass
            clients = clients.filter(search_q)
        from apps.accounts.rbac import is_company_admin as _is_company_admin
        if _is_company_admin(request):
            created_by_id = request.GET.get('created_by', '').strip()
            if created_by_id:
                try:
                    clients = clients.filter(created_by_id=int(created_by_id))
                except (ValueError, TypeError):
                    pass
        sort = request.GET.get('sort', 'name')
        if sort == '-name':
            clients = clients.order_by('-name')
        elif sort == 'created_at':
            clients = clients.order_by('created_at')
        elif sort == '-created_at':
            clients = clients.order_by('-created_at')
        else:
            clients = clients.order_by('name')
    except Exception:
        pass

    total_clients = clients.count()
    active_clients = clients.filter(created_at__gte=timezone.now() - timezone.timedelta(days=30)).count()
    recent_clients = clients.filter(created_at__gte=timezone.now() - timezone.timedelta(days=30)).count()

    from apps.quotations.models import Quotation
    total_quotations = for_user_queryset(Quotation, request.user, request, account_lookup='account').count()
    from apps.accounts.rbac import is_company_admin as _is_company_admin
    from apps.core.utils import get_account_users_for_filter
    account_users = get_account_users_for_filter(request.user) if _is_company_admin(request) else []
    return render(request, 'clients/client_list.html', {
        'clients': clients,
        'total_clients': total_clients,
        'active_clients_count': active_clients,
        'recent_clients_count': recent_clients,
        'total_quotations': total_quotations,
        'account_users': account_users,
        'discovery_stats': discovery_stats,
    })


def _parse_client_list_date_range(request):
    """
    Parse GET params: range_type (all, day, week, month, quarter, year, custom),
    period_date (YYYY-MM-DD), date_from, date_to (for custom).
    Returns (queryset_filter_kwargs, date_label).
    """
    range_type = (request.GET.get('range_type') or 'all').strip().lower()
    today = timezone.now().date()
    filter_kwargs = {}
    date_label = 'All records'

    if range_type == 'all':
        return {}, 'All records'

    if range_type == 'custom':
        date_from_s = (request.GET.get('date_from') or '').strip()
        date_to_s = (request.GET.get('date_to') or '').strip()
        try:
            if date_from_s:
                d_from = date.fromisoformat(date_from_s)
                filter_kwargs['created_at__date__gte'] = d_from
            if date_to_s:
                d_to = date.fromisoformat(date_to_s)
                filter_kwargs['created_at__date__lte'] = d_to
            if date_from_s and date_to_s:
                date_label = f"{d_from.strftime('%d %b %Y')} – {d_to.strftime('%d %b %Y')}"
            elif date_from_s:
                date_label = f"From {d_from.strftime('%d %b %Y')}"
            elif date_to_s:
                date_label = f"Up to {d_to.strftime('%d %b %Y')}"
        except ValueError:
            pass
        return filter_kwargs, date_label

    period_date_s = (request.GET.get('period_date') or '').strip()
    try:
        ref = date.fromisoformat(period_date_s) if period_date_s else today
    except ValueError:
        ref = today

    if range_type == 'day':
        filter_kwargs['created_at__date'] = ref
        date_label = ref.strftime('%d %b %Y')
    elif range_type == 'week':
        week_start = ref - timedelta(days=ref.weekday())
        week_end = week_start + timedelta(days=6)
        filter_kwargs['created_at__date__gte'] = week_start
        filter_kwargs['created_at__date__lte'] = week_end
        date_label = f"{week_start.strftime('%d %b %Y')} – {week_end.strftime('%d %b %Y')} (Week)"
    elif range_type == 'month':
        start_of_month = ref.replace(day=1)
        _, last_day = calendar.monthrange(ref.year, ref.month)
        end_of_month = ref.replace(day=last_day)
        filter_kwargs['created_at__date__gte'] = start_of_month
        filter_kwargs['created_at__date__lte'] = end_of_month
        date_label = ref.strftime('%B %Y')
    elif range_type == 'quarter':
        quarter = (ref.month - 1) // 3 + 1
        quarter_start = date(ref.year, (quarter - 1) * 3 + 1, 1)
        quarter_end_month = quarter * 3
        _, qlast = calendar.monthrange(ref.year, quarter_end_month)
        quarter_end = date(ref.year, quarter_end_month, qlast)
        filter_kwargs['created_at__date__gte'] = quarter_start
        filter_kwargs['created_at__date__lte'] = quarter_end
        date_label = f"Q{quarter} {ref.year}"
    elif range_type == 'year':
        year_start = date(ref.year, 1, 1)
        year_end = date(ref.year, 12, 31)
        filter_kwargs['created_at__date__gte'] = year_start
        filter_kwargs['created_at__date__lte'] = year_end
        date_label = str(ref.year)
    else:
        return {}, 'All records'

    return filter_kwargs, date_label


def _client_list_document_context(request, object_list, date_label):
    """Context for client list print/PDF: company details, logo, theme, object_list."""
    from apps.accounts.rbac import is_company_admin as _is_company_admin
    company = get_company_profile_for_user(request.user, request)
    company_logo = None
    if company and getattr(company, 'logo', None) and company.logo:
        company_logo = company.logo.url
    theme_primary = getattr(company, 'primary_color', '#1976d2') if company else '#1976d2'
    theme_secondary = getattr(company, 'secondary_color', '#f8f9fa') if company else '#f8f9fa'
    theme_accent = getattr(company, 'accent_color', '#e9ecef') if company else '#e9ecef'
    theme_text = getattr(company, 'text_color', '#333333') if company else '#333333'
    return {
        'object_list': object_list,
        'date_label': date_label,
        'company_profile': company,
        'company_logo': company_logo,
        'theme_primary_color': theme_primary,
        'theme_secondary_color': theme_secondary,
        'theme_accent_color': theme_accent,
        'theme_text_color': theme_text,
        'is_company_admin': _is_company_admin(request),
    }


@login_required
@company_admin_or_permission_required('clients.print_client', raise_exception=True)
@never_cache
def client_list_print(request):
    """Print full clients table with optional date range. Company details + logo, A4 zoom, text wrap."""
    from apps.clients.discovery import sync_discovered_clients

    discovery_stats = {'synced': 0, 'created': 0, 'updated': 0}
    try:
        clients, discovery_stats = sync_discovered_clients(request.user, request)
        clients = clients.select_related('created_by')
    except Exception:
        clients = for_user_queryset(Client, request.user, request, account_lookup='company__account').select_related('created_by')

    filter_kwargs, date_label = _parse_client_list_date_range(request)
    if filter_kwargs:
        clients = clients.filter(**filter_kwargs)
    clients = clients.order_by('name')
    object_list = list(clients)

    context = _client_list_document_context(request, object_list, date_label)
    response = render(request, 'clients/client_list_print.html', context)
    apply_no_cache_headers(response)
    return response


@login_required
@company_admin_or_permission_required('clients.download_client', raise_exception=True)
@never_cache
def client_list_pdf(request):
    """Download full clients table as PDF with optional date range. Same layout as print (A4, text wrap)."""
    from apps.clients.discovery import sync_discovered_clients

    discovery_stats = {'synced': 0, 'created': 0, 'updated': 0}
    try:
        clients, discovery_stats = sync_discovered_clients(request.user, request)
        clients = clients.select_related('created_by')
    except Exception:
        clients = for_user_queryset(Client, request.user, request, account_lookup='company__account').select_related('created_by')

    filter_kwargs, date_label = _parse_client_list_date_range(request)
    if filter_kwargs:
        clients = clients.filter(**filter_kwargs)
    clients = clients.order_by('name')
    object_list = list(clients)

    try:
        from django.template.loader import get_template
        from weasyprint import HTML
        context = _client_list_document_context(request, object_list, date_label)
        if context.get('company_logo'):
            context['company_logo'] = request.build_absolute_uri(context['company_logo'])
        template = get_template('clients/client_list_print.html')
        html_str = template.render(context, request)
        html = HTML(string=html_str)
        pdf_file = html.write_pdf()
        filename = f"clients-list-{timezone.now().strftime('%Y%m%d-%H%M')}.pdf"
        response = HttpResponse(pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        apply_no_cache_headers(response)
        return response
    except ImportError:
        url = reverse('clients:client_list_print') + ('?' + request.GET.urlencode() if request.GET else '')
        return redirect(url)


@login_required
@permission_required('clients.add_client', raise_exception=True)
def client_create(request):
    """Create a new client"""
    if request.method == 'POST':
        form = ClientForm(request.POST)
        if form.is_valid():
            client = form.save(commit=False)
            from apps.core.utils import get_company_profile_for_user
            company_profile = get_company_profile_for_user(request.user, request)
            if not company_profile:
                messages.error(request, 'Please create a company profile first.')
                return redirect('core:company_profile')
            client.company = company_profile
            client.created_by = request.user
            client.save()
            messages.success(request, f'Client "{client.name}" created successfully!')
            return redirect('clients:client_list')
    else:
        form = ClientForm()
    
    return render(request, 'clients/client_form.html', {
        'form': form,
        'create': True
    })

@login_required
@permission_required('clients.view_client', raise_exception=True)
def client_detail(request, pk):
    """View client details"""
    from apps.core.utils import get_company_profile_for_user
    company_profile = get_company_profile_for_user(request.user, request)
    if not company_profile:
        messages.error(request, 'Please create a company profile first.')
        return redirect('core:company_profile')
    qs = for_user_queryset(Client, request.user, request, account_lookup='company__account')
    client, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return response
    return render(request, 'clients/client_detail.html', {
        'client': client
    })

@login_required
@permission_required('clients.change_client', raise_exception=True)
def client_edit(request, pk):
    """Edit client"""
    from apps.core.utils import get_company_profile_for_user
    company_profile = get_company_profile_for_user(request.user, request)
    if not company_profile:
        messages.error(request, 'Please create a company profile first.')
        return redirect('core:company_profile')
    qs = for_user_queryset(Client, request.user, request, account_lookup='company__account')
    client, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return response
    if request.method == 'POST':
        form = ClientForm(request.POST, instance=client)
        if form.is_valid():
            form.save()
            messages.success(request, f'Client "{client.name}" updated successfully!')
            return redirect('clients:client_detail', pk=client.pk)
    else:
        form = ClientForm(instance=client)
    
    return render(request, 'clients/client_form.html', {
        'form': form,
        'client': client,
        'create': False
    })

@login_required
@permission_required('clients.delete_client', raise_exception=True)
def client_delete(request, pk):
    """Delete client"""
    from apps.core.utils import get_company_profile_for_user
    company_profile = get_company_profile_for_user(request.user, request)
    if not company_profile:
        messages.error(request, 'Please create a company profile first.')
        return redirect('core:company_profile')
    qs = for_user_queryset(Client, request.user, request, account_lookup='company__account')
    client, response = get_object_or_unauthorized(request, qs, pk=pk)
    if response:
        return response
    if request.method == 'POST':
        client_name = client.name
        client.delete()
        messages.success(request, f'Client "{client_name}" deleted successfully!')
        return redirect('clients:client_list')
    
    return render(request, 'clients/client_confirm_delete.html', {
        'client': client
    })
