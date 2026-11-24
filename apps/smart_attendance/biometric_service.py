import logging
from typing import Dict

from django.utils import timezone

from .attendance_processor import update_daily_attendance_for_employee
from .duplicate_detector import is_duplicate_attendance
from .models import AttendanceLog, BiometricDevice, Employee, RawBiometricLog
from .utils import normalize_timestamp, compute_queue_hash

logger = logging.getLogger("smart_attendance.sync")


def _extract_uid(payload: Dict) -> str:
    """Extract user identifier from payload using all known aliases."""
    for key in ("uid", "biometric_uid", "user_id", "PIN", "pin", "UserID", "employee_id"):
        val = payload.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


def _get_or_create_employee(device: BiometricDevice, uid: str) -> tuple:
    """
    Smart employee matching: tries multiple ways to find/create employee.
    Returns (employee, created) tuple.
    """
    employee = (
        Employee.objects.filter(tenant=device.tenant, biometric_uid=uid).first()
        or Employee.objects.filter(tenant=device.tenant, employee_id=uid).first()
    )
    
    if employee:
        return employee, False
    
    # Extract name from payload if available (some devices send name)
    first_name = payload.get("first_name") or payload.get("name") or payload.get("employee_name") or "Unknown"
    last_name = payload.get("last_name") or ""
    email = payload.get("email") or ""
    phone = payload.get("phone") or ""
    
    # Try to extract name parts if full name provided
    if " " in first_name and not last_name:
        parts = first_name.split(" ", 1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else ""
    
    # Auto-create employee with biometric_uid
    employee = Employee.objects.create(
        tenant=device.tenant,
        employee_id=uid,
        biometric_uid=uid,
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
        is_active=True,
    )
    
    logger.info(
        "Auto-created employee from biometric data: tenant_id=%s uid=%s name='%s %s'",
        device.tenant_id, uid, first_name, last_name
    )
    
    return employee, True


def process_raw_payload(device: BiometricDevice, payload: Dict) -> None:
    """
    Convert a validated queue payload into RawBiometricLog + AttendanceLog entries.
    Accepts flexible field names; preserves full raw_payload for audit.
    Auto-creates employee if not found (smart feature).
    """
    ts = normalize_timestamp(payload["timestamp"])
    uid = _extract_uid(payload) or str(payload.get("uid", ""))
    verify_mode = str(payload.get("verify_mode") or payload.get("verify") or "")
    punch_type = str(payload.get("punch_type") or payload.get("punch") or payload.get("type") or "")
    work_code = str(payload.get("work_code") or payload.get("workcode") or "")

    # Smart employee matching - auto-creates if not found
    employee, created = _get_or_create_employee(device, uid)

    queue_hash = compute_queue_hash(uid, ts, device.id)

    # Always create RawBiometricLog for full audit trail – no records skipped
    RawBiometricLog.objects.create(
        device=device,
        biometric_uid=uid,
        timestamp=ts,
        verify_mode=verify_mode,
        punch_type=punch_type,
        raw_payload=payload,
        queue_hash=queue_hash,
    )

    if is_duplicate_attendance(employee.id, device.id, ts):
        return

    AttendanceLog.objects.create(
        employee=employee,
        device=device,
        punch_time=ts,
        punch_type=punch_type,
        verify_mode=verify_mode,
        work_code=work_code,
        is_duplicate=False,
    )

    # Update per-day aggregate
    update_daily_attendance_for_employee(employee, ts.date())
    
    # Log punch type for monitoring
    punch_display = punch_type or "Clock"
    logger.info(
        "Attendance recorded: employee_id=%s name='%s %s' type='%s' time=%s device=%s",
        employee.id, employee.first_name, employee.last_name, punch_display, ts, device.device_name
    )

