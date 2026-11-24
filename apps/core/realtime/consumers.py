"""
Phase 2 — WebSocket consumer.
Scope by Company/Account ID. Authenticate via session (AuthMiddlewareStack).
Phase 7: If WebSocket disconnects, app continues normally (no hard dependency).
"""
import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

logger = logging.getLogger(__name__)


class RealtimeConsumer(AsyncWebsocketConsumer):
    """
    Consumers connect to /ws/realtime/.
    They are added to group realtime_account_{account_id} after auth.
    Only authenticated users with same account_id receive pushes.
    """

    async def connect(self):
        self.account_id = None
        self.group_name = None
        try:
            # scope["user"] set by AuthMiddlewareStack (session-based)
            user = self.scope.get("user")
            if not user or not getattr(user, "is_authenticated", True):
                await self.close(code=4403)
                return
            account_id = await self.get_account_id(user)
            if not account_id:
                await self.close(code=4403)
                return
            self.account_id = account_id
            self.group_name = f"realtime_account_{account_id}"
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            await self.accept()
            await self.send_initial_metrics(account_id)
        except Exception as e:
            logger.debug("Realtime connect failed: %s", e)
            await self.close(code=4500)

    async def disconnect(self, close_code):
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        if text_data:
            try:
                data = json.loads(text_data)
                if data.get("type") == "ping":
                    await self.send(text_data=json.dumps({"type": "pong"}))
            except Exception:
                pass

    async def realtime_metrics(self, event):
        """Handle group_send from emitter. Phase 6: filter by user permission before sending."""
        try:
            metrics = event.get("metrics", {})
            app = event.get("app")
            user = self.scope.get("user")
            if user and metrics:
                metrics = await self._filter_metrics_by_permission(user, metrics, app)
            if not metrics:
                return
            await self.send(text_data=json.dumps({
                "type": "metrics",
                "app": app,
                "metrics": metrics,
            }))
        except Exception as e:
            logger.debug("Realtime send failed: %s", e)

    @database_sync_to_async
    def _filter_metrics_by_permission(self, user, metrics, single_app):
        """Phase 6: only include app sections the user has permission to view."""
        if not user:
            return metrics
        app_permissions = {
            "core": "core.view_companyprofile",
            "invoice": "invoices.view_invoice",
            "quotation": "quotations.view_quotation",
            "waybill": "waybills.view_waybill",
            "receipt": "receipts.view_receipt",
            "job_order": "job_orders.view_product",
            "inventory": "inventory.view_inventory",
            "client": "clients.view_client",
            "templates": "invoices.view_invoicetemplate",
        }
        out = {}
        for key, value in metrics.items():
            perm = app_permissions.get(key)
            if perm and not user.has_perm(perm):
                continue
            out[key] = value
        return out

    @database_sync_to_async
    def get_account_id(self, user):
        return getattr(user, "account_id", None)

    @database_sync_to_async
    def fetch_initial_metrics(self, account_id, user=None):
        from .aggregation import aggregate_dashboard
        return aggregate_dashboard(account_id, user=user)

    async def send_initial_metrics(self, account_id):
        try:
            user = self.scope.get("user")
            metrics = await self.fetch_initial_metrics(account_id, user=user)
            if user and metrics:
                metrics = await self._filter_metrics_by_permission(user, metrics, None)
            if metrics:
                await self.send(text_data=json.dumps({
                    "type": "metrics",
                    "app": None,
                    "metrics": metrics,
                }))
        except Exception as e:
            logger.debug("Initial metrics send failed: %s", e)
