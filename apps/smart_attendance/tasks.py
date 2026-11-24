from celery import shared_task

from django.utils import timezone

from apps.core.models import Account

from .corrupted_log_repair import attempt_repair
from .device_discovery import discover_devices_for_tenant
from .models import CorruptedLog, SyncQueue
from .sync_engine import process_queue_item


@shared_task(name="apps.smart_attendance.tasks.run_device_discovery")
def run_device_discovery():
    """
    Periodic task: scan network and auto-register devices for all tenants.
    """
    for account in Account.objects.all():
        discover_devices_for_tenant(account)


@shared_task(name="apps.smart_attendance.tasks.process_sync_queue_item")
def process_sync_queue_item(queue_id: int):
    """
    Process a single queue item.
    """
    process_queue_item(queue_id)


@shared_task(name="apps.smart_attendance.tasks.repair_corrupted_logs")
def repair_corrupted_logs(batch_size: int = 100):
    """
    Background repair of corrupted logs.
    """
    pending = (
        CorruptedLog.objects.filter(
            repair_status=CorruptedLog.REPAIR_STATUS_PENDING,
        )
        .order_by("created_at")[:batch_size]
    )
    for log in pending:
        attempt_repair(log)


@shared_task(name="apps.smart_attendance.tasks.process_pending_queue_batch")
def process_pending_queue_batch(batch_size: int = 1000):
    """
    High-throughput batch processor; Celery can run many of these in parallel.
    """
    ids = list(
        SyncQueue.objects.filter(status=SyncQueue.STATUS_PENDING)
        .order_by("created_at")
        .values_list("id", flat=True)[:batch_size]
    )
    for queue_id in ids:
        process_queue_item(queue_id)

