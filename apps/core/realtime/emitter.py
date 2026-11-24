"""
Phase 2 — Real-time transport.
Emit events to Django Channels (WebSocket) scoped by account.
NEVER broadcast globally. All aggregates are computed server-side (aggregation.py).
"""
import logging
from django.db import transaction

logger = logging.getLogger(__name__)


def emit_realtime_update(account_id, app_name=None):
    """
    After a model change, recalculate aggregates for this account and send to
    the account's WebSocket group. Only users in that account (with permission)
    receive the update.
    """
    if not account_id:
        return
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        from .aggregation import aggregate_dashboard
    except ImportError:
        return
    try:
        payload = aggregate_dashboard(account_id)
    except Exception as e:
        logger.warning("Realtime aggregation failed: %s", e)
        return
    group_name = f"realtime_account_{account_id}"
    message = {
        'type': 'realtime.metrics',
        'app': app_name,
        'metrics': payload,
    }
    try:
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(group_name, message)
    except Exception as e:
        logger.debug("Realtime emit failed (channel layer may be disabled): %s", e)


def invalidate_dashboard_cache_for_user(user_id):
    """Invalidate dashboard stats cache so next page load is fresh (Phase 7 fallback)."""
    try:
        from django.core.cache import cache
        cache.delete(f'dashboard_stats_{user_id}')
    except Exception:
        pass
