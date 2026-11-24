"""
ZKTeco device pull service.

Connects to ZKTeco biometric devices via the ZK protocol (pyzk), pulls
attendance/audit logs, and enqueues them into the Smart Attendance sync pipeline.
"""
import logging
from datetime import datetime
from typing import List, Optional

from django.utils import timezone

from .models import BiometricDevice, DeviceSyncHistory
from .queue_manager import enqueue_biometric_payload
from .utils import normalize_timestamp

logger = logging.getLogger("smart_attendance.device")


# ZKTeco status codes (from pyzk / ZK protocol)
ZK_STATUS_CHECKOUT = 0
ZK_STATUS_CHECKIN = 1
ZK_STATUS_BREAKOUT = 2
ZK_STATUS_BREAKIN = 3

STATUS_TO_PUNCH_TYPE = {
    ZK_STATUS_CHECKIN: "checkin",
    ZK_STATUS_CHECKOUT: "checkout",
    ZK_STATUS_BREAKIN: "breakin",
    ZK_STATUS_BREAKOUT: "breakout",
}


def _attendance_to_payload(att, device: BiometricDevice) -> dict:
    """
    Convert pyzk Attendance object to our biometric payload format.
    """
    ts = att.timestamp
    if ts and timezone.is_naive(ts):
        ts = timezone.make_aware(ts, timezone.get_current_timezone())
    ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if ts else ""

    punch_type = STATUS_TO_PUNCH_TYPE.get(att.status, "checkin")

    return {
        "device_serial": device.device_serial,
        "uid": str(att.user_id or att.uid or ""),
        "timestamp": ts_str,
        "verify_mode": "fingerprint",
        "punch_type": punch_type,
    }


def pull_from_zk_device(device: BiometricDevice) -> int:
    """
    Connect to a ZKTeco device, pull new attendance logs since last sync,
    enqueue them, and update DeviceSyncHistory.

    Returns number of logs enqueued.
    """
    try:
        from zk import ZK
    except ImportError:
        logger.error("pyzk not installed. Run: pip install pyzk")
        return 0

    conn = None
    enqueued = 0
    last_ts = None

    try:
        zk = ZK(
            device.device_ip,
            port=device.device_port or 4370,
            timeout=5,
        )
        conn = zk.connect()
        if not conn:
            logger.warning("Could not connect to ZKTeco device id=%s ip=%s", device.id, device.device_ip)
            return 0

        conn.disable_device()
        attendances = conn.get_attendance()
        conn.enable_device()
    except Exception as exc:
        logger.warning(
            "ZKTeco pull failed for device id=%s ip=%s: %s",
            device.id,
            device.device_ip,
            exc,
        )
        return 0
    finally:
        if conn:
            try:
                conn.disconnect()
            except Exception:
                pass

    history, _ = DeviceSyncHistory.objects.get_or_create(device=device)
    last_sync = history.last_sync_time

    for att in attendances or []:
        if not att.timestamp:
            continue
        try:
            ts = normalize_timestamp(att.timestamp)
        except (ValueError, TypeError):
            continue
        if last_sync and ts <= last_sync:
            continue

        payload = _attendance_to_payload(att, device)
        result = enqueue_biometric_payload(device, payload)
        if result:
            enqueued += 1
        if last_ts is None or ts > last_ts:
            last_ts = ts

    if enqueued and last_ts:
        history.last_sync_time = last_ts
        history.logs_synced = (history.logs_synced or 0) + enqueued
        history.status = "ok"
        history.save(update_fields=["last_sync_time", "logs_synced", "status"])
        logger.info(
            "Pulled %s logs from ZKTeco device id=%s ip=%s",
            enqueued,
            device.id,
            device.device_ip,
        )

    return enqueued


def pull_from_all_zk_devices() -> int:
    """
    Pull attendance from all registered BiometricDevices.
    Returns total logs enqueued across all devices.
    """
    devices = BiometricDevice.objects.filter(
        device_ip__isnull=False,
    ).exclude(device_ip="")
    total = 0
    for device in devices:
        try:
            total += pull_from_zk_device(device)
        except Exception as exc:
            logger.exception("Error pulling from device id=%s: %s", device.id, exc)
    return total
