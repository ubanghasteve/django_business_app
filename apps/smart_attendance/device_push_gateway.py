import logging
from typing import Dict

from django.utils import timezone

from .device_authentication import authenticate_device, DeviceAuthenticationError
from .queue_manager import enqueue_biometric_payload

logger = logging.getLogger("smart_attendance.sync")


def _update_device_status(device):
    """Update device status to online when receiving push data."""
    if device.status != device.STATUS_ONLINE:
        device.status = device.STATUS_ONLINE
        device.last_seen = timezone.now()
        device.save(update_fields=["status", "last_seen"])
        logger.info("Device marked online: serial=%s", device.device_serial)


def handle_biometric_push(payload: Dict, secret: str):
    """
    Core handler for biometric push API.

    Steps:
    - Authenticate device
    - Validate payload shape (basic)
    - Update device status to online
    - Enqueue for async processing
    """
    device_serial = payload.get("device_serial")
    if not device_serial:
        raise ValueError("device_serial is required")

    try:
        device = authenticate_device(device_serial, secret)
    except DeviceAuthenticationError as exc:
        logger.warning("Biometric push auth failed serial=%s", device_serial)
        raise

    # Update device status to online when receiving push
    _update_device_status(device)

    # Basic payload validation; uid can be uid, biometric_uid, or user_id (ZKTeco compatibility)
    uid = payload.get("uid") or payload.get("biometric_uid") or payload.get("user_id")
    if not uid or not str(uid).strip():
        raise ValueError("uid, biometric_uid, or user_id is required")
    if "timestamp" not in payload:
        raise ValueError("timestamp is required")
    # Normalize uid for downstream processing
    payload["uid"] = str(uid).strip()

    enqueue_biometric_payload(device, payload)

