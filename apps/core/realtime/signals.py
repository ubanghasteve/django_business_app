"""
Phase 1 — Authoritative data events.
Attach post_save and post_delete to all models that affect dashboards/counters.
Emit ONLY after transaction commit (transaction.on_commit).
"""
import logging
from django.db import transaction
from django.dispatch import receiver
from django.db.models.signals import post_save, post_delete

logger = logging.getLogger(__name__)

# Map (app_label, model_name) -> app_name for emitter
_MODEL_APP_MAP = {
    ("invoices", "Invoice"): "invoice",
    ("invoices", "InvoiceTemplate"): "invoice",
    ("invoices", "InvoiceItem"): "invoice",
    ("receipts", "Receipt"): "receipt",
    ("quotations", "Quotation"): "quotation",
    ("quotations", "QuotationTemplate"): "quotation",
    ("waybills", "Waybill"): "waybill",
    ("waybills", "WaybillTemplate"): "waybill",
    ("job_orders", "Product"): "job_order",
    ("inventory", "Inventory"): "inventory",
    ("inventory", "InventoryProduct"): "inventory",
    ("inventory", "InventoryCategory"): "inventory",
    ("clients", "Client"): "client",
}


def _schedule_emit(instance, app_name):
    from .aggregation import get_account_id_from_instance
    from .emitter import emit_realtime_update, invalidate_dashboard_cache_for_user
    account_id = get_account_id_from_instance(instance)
    if not account_id:
        return
    def _do_emit():
        emit_realtime_update(account_id, app_name=app_name)
        for attr in ("created_by_id", "user_id"):
            if hasattr(instance, attr) and getattr(instance, attr):
                invalidate_dashboard_cache_for_user(getattr(instance, attr))
    transaction.on_commit(_do_emit)


def _on_save(sender, instance, created, **kwargs):
    app_name = _MODEL_APP_MAP.get((sender._meta.app_label, sender.__name__))
    if app_name:
        _schedule_emit(instance, app_name)


def _on_delete(sender, instance, **kwargs):
    app_name = _MODEL_APP_MAP.get((sender._meta.app_label, sender.__name__))
    if app_name:
        _schedule_emit(instance, app_name)


def connect_realtime_signals():
    """Connect post_save/post_delete to each model. Call from RealtimeConfig.ready()."""
    from django.apps import apps
    for (app_label, model_name) in _MODEL_APP_MAP:
        try:
            model = apps.get_model(app_label, model_name)
            post_save.connect(_on_save, sender=model)
            post_delete.connect(_on_delete, sender=model)
        except LookupError:
            pass
        except Exception as e:
            logger.debug("Realtime signal connect %s.%s: %s", app_label, model_name, e)
