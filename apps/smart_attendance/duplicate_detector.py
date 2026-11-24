import logging
from typing import Optional

from .models import AttendanceLog, RawBiometricLog, SyncQueue
from .utils import compute_queue_hash, normalize_timestamp

logger = logging.getLogger("smart_attendance.sync")


def generate_hash_from_payload(device_id: int, payload: dict) -> str:
    """
    Helper to compute the duplicate hash from a queue payload.
    Supports uid, biometric_uid, user_id, PIN, etc.
    """
    employee_id = str(
        payload.get("uid")
        or payload.get("biometric_uid")
        or payload.get("user_id")
        or payload.get("PIN")
        or payload.get("pin")
        or ""
    )
    timestamp = normalize_timestamp(payload.get("timestamp"))
    return compute_queue_hash(employee_id, timestamp, device_id)


def is_duplicate_queue_item(device_id: int, payload: dict) -> bool:
    """
    Check if a payload is already present in SyncQueue or RawBiometricLog.
    """
    queue_hash = generate_hash_from_payload(device_id, payload)
    exists_in_queue = SyncQueue.objects.filter(queue_hash=queue_hash).exists()
    if exists_in_queue:
        logger.info("Duplicate queue payload detected (queue) hash=%s", queue_hash)
        return True
    exists_in_raw = RawBiometricLog.objects.filter(queue_hash=queue_hash).exists()
    if exists_in_raw:
        logger.info("Duplicate queue payload detected (raw) hash=%s", queue_hash)
        return True
    return False


def is_duplicate_attendance(employee_id: int, device_id: Optional[int], timestamp) -> bool:
    """
    Duplicate rule: employee + timestamp + device.
    """
    dt = normalize_timestamp(timestamp)
    qs = AttendanceLog.objects.filter(employee_id=employee_id, punch_time=dt)
    if device_id:
        qs = qs.filter(device_id=device_id)
    exists = qs.exists()
    if exists:
        logger.info(
            "Duplicate attendance detected employee_id=%s device_id=%s ts=%s",
            employee_id,
            device_id,
            dt,
        )
    return exists

