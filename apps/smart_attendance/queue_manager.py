import logging
from typing import Optional

from django.db import transaction

from .duplicate_detector import is_duplicate_queue_item
from .models import BiometricDevice, SyncQueue
from .utils import compute_queue_hash, normalize_timestamp

logger = logging.getLogger("smart_attendance.sync")


@transaction.atomic
def enqueue_biometric_payload(device: BiometricDevice, payload: dict) -> Optional[SyncQueue]:
    """
    Enqueue a raw biometric payload for async processing.
    """
    if is_duplicate_queue_item(device.id, payload):
        logger.info(
            "Skipping enqueue for duplicate payload device_id=%s uid=%s ts=%s",
            device.id,
            payload.get("uid"),
            payload.get("timestamp"),
        )
        return None

    ts = normalize_timestamp(payload["timestamp"])
    employee_id = str(
        payload.get("uid")
        or payload.get("biometric_uid")
        or payload.get("user_id")
        or payload.get("PIN")
        or payload.get("pin")
        or ""
    )
    queue_hash = compute_queue_hash(employee_id, ts, device.id)

    queue_item = SyncQueue.objects.create(
        device=device,
        payload=payload,
        status=SyncQueue.STATUS_PENDING,
        retry_count=0,
        queue_hash=queue_hash,
    )

    logger.info(
        "Enqueued biometric payload queue_id=%s device_id=%s hash=%s",
        queue_item.id,
        device.id,
        queue_hash,
    )

    # Trigger async processing (Celery); if not available, process inline for real-time updates
    try:
        from .tasks import process_sync_queue_item
        process_sync_queue_item.delay(queue_item.id)
    except Exception:
        # Fallback: process immediately so DB updates in real-time without Celery
        try:
            from .sync_engine import process_queue_item
            process_queue_item(queue_item.id)
        except Exception as exc:
            logger.warning("Inline queue processing failed queue_id=%s: %s", queue_item.id, exc)

    return queue_item

