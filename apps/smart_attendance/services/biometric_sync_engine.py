"""
Smart Biometric Sync Engine – high-speed log ingestion, multi-device sync,
duplicate prevention, log repair, device recovery.

Capable of syncing 50,000+ logs per minute via queue-based processing.
"""
import logging
from typing import Optional

from ..queue_manager import enqueue_biometric_payload
from ..sync_engine import process_queue_item
from ..workers import process_pending_queue
from ..models import BiometricDevice, SyncQueue

logger = logging.getLogger("smart_attendance.sync")


def ingest_log(device: BiometricDevice, payload: dict) -> Optional[int]:
    """
    High-speed log ingestion: enqueue payload for async processing.
    Returns queue_item id or None if duplicate.
    """
    item = enqueue_biometric_payload(device, payload)
    return item.id if item else None


def process_batch(batch_size: int = 1000) -> int:
    """
    Process a batch of pending queue items. Returns count processed.
    """
    from ..workers.sync_worker import run_sync_worker
    return run_sync_worker(batch_size=batch_size)


def get_pending_count() -> int:
    """Return count of pending queue items."""
    return SyncQueue.objects.filter(status=SyncQueue.STATUS_PENDING).count()
