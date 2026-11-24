"""
Global notification API. Returns notifications for the current user.
Respects RBAC, data isolation, multi-tenant permissions, and role-based visibility.
Only shows notifications from apps the user has permission to access.
Real-time updates via Ajax polling - no page refresh required.

Database accuracy: Every request reads directly from the database (no view-level
or queryset caching). Combined with no-cache response headers, this ensures
the UI always shows the latest notifications and correct unread counts.
"""
import logging
from django.utils.dateformat import DateFormat
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.ownership import get_account_for_user

from .models import Notification
from .permissions import SOURCE_APP_PERMISSIONS, user_can_see_app_notifications

logger = logging.getLogger(__name__)

# Prevent browser caching - ensures users always get fresh notification data without hard refresh
NO_CACHE_HEADERS = {
    'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
    'Pragma': 'no-cache',
    'Expires': '0',
}


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def notification_list_api(request):
    """
    List notifications for the current user. Tenant-scoped; user only sees their own.
    Permission-aware: only returns notifications from apps the user has access to
    (based on their role and permissions). Team members, employees, and admins each
    see only notifications relevant to their permission level.
    Returns: notifications, unread_count.
    """
    user = request.user
    account = get_account_for_user(user)
    if not account:
        logger.warning(
            "notification_list_api: no account for user id=%s, account_id=%s; returning empty list",
            getattr(user, 'id', None), getattr(user, 'account_id', None),
        )
        resp = Response({'notifications': [], 'unread_count': 0})
        for k, v in NO_CACHE_HEADERS.items():
            resp[k] = v
        return resp

    # Single source of truth: always query DB; order newest first for accuracy
    qs = (
        Notification.objects.filter(user=user, account=account)
        .select_related('actor')
        .order_by('-created_at')
    )

    # Filter by permission: only show notifications from apps user can access
    # Automatically detects roles, team members, employees via user_can_see_app_notifications
    allowed_sources = [
        src for src in SOURCE_APP_PERMISSIONS
        if user_can_see_app_notifications(user, src, request)
    ]
    if allowed_sources:
        qs = qs.filter(source_app__in=allowed_sources)
    else:
        qs = qs.filter(source_app='system')  # System notifications only when no app access

    limit = min(int(request.GET.get('limit', 20)), 50)
    offset = int(request.GET.get('offset', 0))
    unread_count = qs.filter(is_read=False).count()
    notifications = list(qs[offset:offset + limit])

    def serialize(n):
        actor_name = None
        actor_avatar = None
        actor_display = None
        if n.actor:
            actor_name = n.actor.get_full_name() or n.actor.email or str(n.actor)
            actor_display = actor_name
            if hasattr(n.actor, 'profile_picture') and n.actor.profile_picture:
                try:
                    actor_avatar = n.actor.profile_picture.url
                except (ValueError, AttributeError):
                    pass
        date_display = DateFormat(n.created_at).format('j M Y') if n.created_at else ''
        time_display = DateFormat(n.created_at).format('g:i A') if n.created_at else ''
        created_display = DateFormat(n.created_at).format('j M Y, g:i A') if n.created_at else ''
        return {
            'id': n.id,
            'source_app': n.source_app,
            'source_app_display': n.get_source_app_display(),
            'title': n.title,
            'message': n.message,
            'actor_name': actor_name,
            'actor_display': actor_display,
            'actor_avatar': actor_avatar,
            'action_url': n.action_url,
            'is_read': n.is_read,
            'timestamp': n.created_at.isoformat() if n.created_at else None,
            'created_display': created_display,
            'date_display': date_display,
            'time_display': time_display,
        }

    resp = Response({
        'notifications': [serialize(n) for n in notifications],
        'unread_count': unread_count,
    })
    resp['Cache-Control'] = NO_CACHE_HEADERS['Cache-Control']
    resp['Pragma'] = NO_CACHE_HEADERS['Pragma']
    resp['Expires'] = NO_CACHE_HEADERS['Expires']
    return resp


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def notification_badge_api(request):
    """
    Lightweight endpoint returning only unread_count for accurate real-time badge.
    Uses same permission filtering as full list. Poll this frequently for badge accuracy.
    """
    user = request.user
    account = get_account_for_user(user)
    if not account:
        logger.warning(
            "notification_badge_api: no account for user id=%s; returning unread_count=0",
            getattr(user, 'id', None),
        )
        resp = Response({'unread_count': 0})
        for k, v in NO_CACHE_HEADERS.items():
            resp[k] = v
        return resp

    qs = Notification.objects.filter(user=user, account=account)
    allowed_sources = [
        src for src in SOURCE_APP_PERMISSIONS
        if user_can_see_app_notifications(user, src, request)
    ]
    if allowed_sources:
        qs = qs.filter(source_app__in=allowed_sources)
    else:
        qs = qs.filter(source_app='system')

    resp = Response({'unread_count': qs.filter(is_read=False).count()})
    resp['Cache-Control'] = NO_CACHE_HEADERS['Cache-Control']
    resp['Pragma'] = NO_CACHE_HEADERS['Pragma']
    resp['Expires'] = NO_CACHE_HEADERS['Expires']
    return resp


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def notification_mark_read_api(request, pk):
    """Mark a single notification as read."""
    user = request.user
    account = get_account_for_user(user)
    if not account:
        return Response({'detail': 'No account'}, status=400)
    updated = Notification.objects.filter(
        pk=pk, user=user, account=account,
    ).update(is_read=True)
    return Response({'ok': updated > 0})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def notification_mark_all_read_api(request):
    """Mark all notifications as read for the current user."""
    user = request.user
    account = get_account_for_user(user)
    if not account:
        return Response({'detail': 'No account'}, status=400)
    updated = Notification.objects.filter(user=user, account=account, is_read=False).update(is_read=True)
    return Response({'ok': True, 'updated': updated})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def notification_clear_all_api(request):
    """Delete all notifications for the current user."""
    user = request.user
    account = get_account_for_user(user)
    if not account:
        return Response({'detail': 'No account'}, status=400)
    deleted, _ = Notification.objects.filter(user=user, account=account).delete()
    return Response({'ok': True, 'deleted': deleted})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def notification_delete_api(request, pk):
    """Delete a single notification."""
    user = request.user
    account = get_account_for_user(user)
    if not account:
        return Response({'detail': 'No account'}, status=400)
    deleted, _ = Notification.objects.filter(pk=pk, user=user, account=account).delete()
    return Response({'ok': deleted > 0})
