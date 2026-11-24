import logging

from django.db import transaction
from django.utils import timezone

from .models import SyncQueue
from .sync_engine import process_queue_item

logger = logging.getLogger("smart_attendance.sync")


def process_pending_queue(batch_size: int = 1000):
    """
    Fallback worker loop for processing pending queue items in-process.
    Celery workers will normally handle this, but this helper allows
    manual triggering (e.g., management command).
    """
    now = timezone.now()
    with transaction.atomic():
        items = (
            SyncQueue.objects.select_for_update(skip_locked=True)
            .filter(status=SyncQueue.STATUS_PENDING)
            .order_by("created_at")[:batch_size]
        )
        ids = [i.id for i in items]
    for queue_id in ids:
        try:
            process_queue_item(queue_id)
        except Exception:  # pragma: no cover - logged
            logger.exception("Failed to process queue item id=%s", queue_id)

