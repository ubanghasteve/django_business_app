import logging

from django.db import transaction

from .biometric_service import process_raw_payload
from .corrupted_log_repair import attempt_repair
from .models import CorruptedLog, SyncQueue

logger = logging.getLogger("smart_attendance.sync")


def _validate_payload(payload: dict) -> None:
    """Validate payload; uid from any alias (uid, biometric_uid, user_id, PIN, etc.)."""
    uid = (
        payload.get("uid")
        or payload.get("biometric_uid")
        or payload.get("user_id")
        or payload.get("PIN")
        or payload.get("pin")
        or payload.get("UserID")
    )
    if not uid or not str(uid).strip():
        raise ValueError("User identifier required (uid, biometric_uid, user_id, PIN, etc.)")
    if not payload.get("timestamp"):
        raise ValueError("timestamp is required")


@transaction.atomic
def process_queue_item(queue_id: int) -> None:
    """
    High-speed sync engine pipeline:
    - Load queue item and lock it
    - Validate payload
    - Detect corrupted logs
    - Store raw log + attendance
    """
    try:
        item = (
            SyncQueue.objects.select_for_update()
            .select_related("device")
            .get(pk=queue_id)
        )
    except SyncQueue.DoesNotExist:
        return

    if item.status not in (SyncQueue.STATUS_PENDING, SyncQueue.STATUS_FAILED):
        return

    item.status = SyncQueue.STATUS_PROCESSING
    item.save(update_fields=["status"])

    device = item.device
    payload = item.payload or {}

    try:
        _validate_payload(payload)
    except Exception as exc:
        # Store as corrupted and mark queue as failed
        CorruptedLog.objects.create(
            device=device,
            raw_payload=payload,
            error_type=str(exc),
            repair_status=CorruptedLog.REPAIR_STATUS_PENDING,
        )
        item.status = SyncQueue.STATUS_FAILED
        item.retry_count = item.retry_count + 1
        item.save(update_fields=["status", "retry_count"])
        logger.warning(
            "Corrupted biometric payload queued as CorruptedLog id=%s queue_id=%s",
            item.id,
            queue_id,
        )
        return

    try:
        process_raw_payload(device, payload)
    except Exception as exc:
        logger.exception("Queue processing failed queue_id=%s: %s", queue_id, exc)
        item.status = SyncQueue.STATUS_PENDING
        item.retry_count = item.retry_count + 1
        item.save(update_fields=["status", "retry_count"])
        return

    item.status = SyncQueue.STATUS_COMPLETED
    item.save(update_fields=["status"])

