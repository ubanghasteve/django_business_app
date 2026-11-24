from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.db import models
from .models import Client
from apps.core.utils import get_company_profile_for_user
from apps.core.ownership import for_user_queryset


@login_required
@require_http_methods(["GET"])
def client_list_api(request):
    """JSON API for real-time clients list + stats. Used by Ajax polling on /clients/ page."""
    from apps.clients.discovery import sync_discovered_clients

    if not request.user.has_perm('clients.view_client'):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    discovery_stats = {'synced': 0, 'created': 0, 'updated': 0}
    try:
        clients_qs, discovery_stats = sync_discovered_clients(request.user, request)
        clients_qs = clients_qs.select_related('created_by')
    except Exception:
        clients_qs = for_user_queryset(Client, request.user, request, account_lookup='company__account').select_related('created_by')

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
        clients_qs = clients_qs.filter(search_q)
    if request.user.has_perm('clients.view_client'):
        from apps.accounts.rbac import is_company_admin
        if is_company_admin(request):
            created_by_id = (request.GET.get('created_by') or '').strip()
            if created_by_id:
                try:
                    clients_qs = clients_qs.filter(created_by_id=int(created_by_id))
                except (ValueError, TypeError):
                    pass
    sort = request.GET.get('sort') or 'name'
    if sort == '-name':
        clients_qs = clients_qs.order_by('-name')
    elif sort == 'created_at':
        clients_qs = clients_qs.order_by('created_at')
    elif sort == '-created_at':
        clients_qs = clients_qs.order_by('-created_at')
    else:
        clients_qs = clients_qs.order_by('name')

    clients_qs = clients_qs.prefetch_related('quotations')

    total_clients = clients_qs.count()
    active_clients = clients_qs.filter(created_at__gte=timezone.now() - timezone.timedelta(days=30)).count()
    recent_clients = clients_qs.filter(created_at__gte=timezone.now() - timezone.timedelta(days=30)).count()
    from apps.quotations.models import Quotation
    total_quotations = for_user_queryset(Quotation, request.user, request, account_lookup='account').count()

    clients_list = []
    for c in clients_qs:
        display_sources = []
        for item in c.get_display_sources():
            app, label, url = item[0], item[1], item[2]
            created_at = item[3] if len(item) > 3 else None
            created_by = item[4] if len(item) > 4 else ''
            created_at_str = created_at.strftime('%b %d, %Y %I:%M %p') if created_at and hasattr(created_at, 'strftime') else ''
            display_sources.append({
                'app': app, 'label': label, 'url': url,
                'created_at': created_at_str,
                'created_by': (created_by or '').strip(),
            })
        clients_list.append({
            'id': c.id,
            'name': c.name or '',
            'email': c.email or '',
            'phone': c.phone or '',
            'address': c.address or '',
            'primary_source_url': c.get_primary_source_url() or '',
            'detail_url': reverse('clients:client_detail', args=[c.id]),
            'edit_url': reverse('clients:client_edit', args=[c.id]) if request.user.has_perm('clients.change_client') else '',
            'delete_url': reverse('clients:client_delete', args=[c.id]) if request.user.has_perm('clients.delete_client') else '',
            'can_edit': request.user.has_perm('clients.change_client'),
            'can_delete': request.user.has_perm('clients.delete_client'),
            'display_sources': display_sources,
            'quotation_count': len(c.quotations.all()) if hasattr(c, 'quotations') else 0,
            'created_at_display': c.created_at.strftime('%b %d, %Y') if c.created_at else '',
            'created_by_name': (c.created_by.get_full_name() or c.created_by.email) if c.created_by else '',
        })

    return JsonResponse({
        'stats': {
            'total_clients': total_clients,
            'active_clients_count': active_clients,
            'recent_clients_count': recent_clients,
            'total_quotations': total_quotations,
            'discovery_synced': discovery_stats.get('synced', 0),
            'discovery_created': discovery_stats.get('created', 0),
            'discovery_updated': discovery_stats.get('updated', 0),
        },
        'clients': clients_list,
    })


@login_required
@require_http_methods(["GET"])
def client_detail_api(request, client_id):
    """API endpoint to get client details (visibility-scoped: admin sees all, team sees own)."""
    try:
        company_profile = get_company_profile_for_user(request.user, request)
        if company_profile:
            qs = for_user_queryset(Client, request.user, request, account_lookup='company__account')
            client = get_object_or_404(qs, id=client_id)
            
            # Return client data as JSON
            client_data = {
                'id': client.id,
                'name': client.name,
                'email': client.email or '',
                'phone': client.phone or '',
                'address': client.address or '',
                'created_at': client.created_at.strftime('%B %d, %Y') if client.created_at else '',
            }
            
            return JsonResponse({
                'success': True,
                'client': client_data
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'Company profile not found'
            }, status=404)
            
    except Client.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Client not found'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500) 