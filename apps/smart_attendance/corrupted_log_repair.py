import logging
from typing import Optional, Tuple

from django.db import transaction
from django.utils import timezone

from .models import CorruptedLog, Employee, RawBiometricLog
from .utils import normalize_timestamp, compute_queue_hash

logger = logging.getLogger("smart_attendance.repair")


def _infer_employee(tenant, biometric_uid: str) -> Optional[Employee]:
    """
    Try to find an employee from biometric UID, employee_id, or fallbacks.
    """
    if not biometric_uid:
        return None
    return (
        Employee.objects.filter(tenant=tenant, biometric_uid=biometric_uid).first()
        or Employee.objects.filter(tenant=tenant, employee_id=biometric_uid).first()
    )


def _infer_timestamp(payload: dict):
    """
    Reconstruct timestamp when missing using best-effort heuristics.
    """
    ts = payload.get("timestamp") or payload.get("time") or payload.get("punch_time")
    if ts:
        return normalize_timestamp(ts)
    # Fallback to now; in real deployments, integrate with device sequence or audit trail.
    return timezone.now()


@transaction.atomic
def attempt_repair(corrupted_log: CorruptedLog) -> Tuple[bool, Optional[RawBiometricLog]]:
    """
    Try to repair a single corrupted log.

    Returns (success, raw_log or None).
    """
    payload = corrupted_log.raw_payload or {}
    device = corrupted_log.device
    tenant = device.tenant

    biometric_uid = payload.get("uid") or payload.get("biometric_uid")
    employee = _infer_employee(tenant, biometric_uid or "")
    if not employee:
        corrupted_log.repair_attempts += 1
        corrupted_log.repair_status = CorruptedLog.REPAIR_STATUS_UNRECOVERABLE
        corrupted_log.save(update_fields=["repair_attempts", "repair_status"])
        logger.warning(
            "Corrupted log unrecoverable (no employee) id=%s device=%s",
            corrupted_log.id,
            device.id,
        )
        return False, None

    ts = _infer_timestamp(payload)
    verify_mode = payload.get("verify_mode", "")
    punch_type = payload.get("punch_type", "")

    queue_hash = compute_queue_hash(str(employee.id), ts, device.id)

    raw_log = RawBiometricLog.objects.create(
        device=device,
        biometric_uid=employee.biometric_uid or biometric_uid or "",
        timestamp=ts,
        verify_mode=verify_mode,
        punch_type=punch_type,
        raw_payload=payload,
        queue_hash=queue_hash,
    )

    corrupted_log.repair_attempts += 1
    corrupted_log.repair_status = CorruptedLog.REPAIR_STATUS_REPAIRED
    corrupted_log.save(update_fields=["repair_attempts", "repair_status"])

    logger.info(
        "Corrupted log repaired id=%s -> raw_log=%s",
        corrupted_log.id,
        raw_log.id,
    )
    return True, raw_log

