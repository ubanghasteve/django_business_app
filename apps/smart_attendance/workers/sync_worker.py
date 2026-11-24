"""
Sync worker – processes pending biometric queue items continuously.
"""
from ..workers import process_pending_queue

__all__ = ["process_pending_queue"]


def run_sync_worker(batch_size: int = 1000) -> int:
    """
    Process one batch of pending queue items. Returns count processed.
    """
    from ..models import SyncQueue
    before = SyncQueue.objects.filter(status=SyncQueue.STATUS_PENDING).count()
    process_pending_queue(batch_size=batch_size)
    after = SyncQueue.objects.filter(status=SyncQueue.STATUS_PENDING).count()
    return before - after
