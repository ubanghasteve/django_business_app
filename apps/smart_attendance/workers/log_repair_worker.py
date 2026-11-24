"""
Log repair worker – attempts repair of corrupted logs.
"""
import logging
from ..models import CorruptedLog
from ..corrupted_log_repair import attempt_repair

logger = logging.getLogger("smart_attendance.repair")


def run_log_repair(batch_size: int = 100) -> int:
    """
    Attempt repair of pending corrupted logs. Returns count repaired.
    """
    repaired = 0
    pending = (
        CorruptedLog.objects.filter(repair_status=CorruptedLog.REPAIR_STATUS_PENDING)
        .order_by("created_at")[:batch_size]
    )
    for log in pending:
        try:
            success, _ = attempt_repair(log)
            if success:
                repaired += 1
        except Exception as exc:
            logger.exception("Repair failed for CorruptedLog id=%s: %s", log.id, exc)
    return repaired
