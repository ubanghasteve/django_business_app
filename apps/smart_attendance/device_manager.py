import logging
from typing import Iterable

from django.utils import timezone

from apps.core.ownership import get_account_for_user

from .device_discovery import discover_devices_for_tenant
from .models import BiometricDevice, DeviceSyncHistory

logger = logging.getLogger("smart_attendance.device")


def list_devices_for_user(user, request=None):
    """
    Return queryset of devices for the current tenant.
    """
    account = get_account_for_user(user)
    if not account:
        return BiometricDevice.objects.none()
    return BiometricDevice.objects.filter(tenant=account).order_by("device_name")


def trigger_device_discovery_for_user(user, request=None) -> int:
    """
    Run auto-discovery for the current user's tenant.
    """
    account = get_account_for_user(user)
    if not account:
        return 0
    return discover_devices_for_tenant(account)


def mark_device_offline(device: BiometricDevice):
    device.status = BiometricDevice.STATUS_OFFLINE
    device.save(update_fields=["status"])
    logger.info("Marked device offline id=%s serial=%s", device.id, device.device_serial)


def record_successful_sync(device: BiometricDevice, last_timestamp, logs_count: int):
    """
    Update DeviceSyncHistory after a successful batch sync.
    """
    history, _ = DeviceSyncHistory.objects.get_or_create(device=device)
    history.last_sync_time = last_timestamp
    history.logs_synced = (history.logs_synced or 0) + int(logs_count)
    history.status = "ok"
    history.save(update_fields=["last_sync_time", "logs_synced", "status"])


def recover_offline_device(device: BiometricDevice, logs: Iterable[dict]):
    """
    Offline device recovery hook.

    When a device reconnects and provides historical logs, feed them into the
    queue engine, skipping any logs that are older than the last_sync_time.
    """
    from .queue_manager import enqueue_biometric_payload
    from .utils import normalize_timestamp

    history, _ = DeviceSyncHistory.objects.get_or_create(device=device)
    last_sync = history.last_sync_time
    accepted = 0
    last_ts = last_sync

    for payload in logs:
        ts_raw = payload.get("timestamp")
        if not ts_raw:
            continue
        try:
            ts = normalize_timestamp(ts_raw)
        except (ValueError, TypeError):
            continue
        if last_sync and ts <= last_sync:
            continue
        enqueue_biometric_payload(device, payload)
        accepted += 1
        if last_ts is None or ts > last_ts:
            last_ts = ts

    if accepted and last_ts:
        record_successful_sync(device, last_ts, accepted)
        logger.info(
            "Recovered %s offline logs for device_id=%s since=%s",
            accepted,
            device.id,
            history.last_sync_time,
        )

