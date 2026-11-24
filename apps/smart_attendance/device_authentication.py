import logging
from typing import Optional

from django.utils import timezone

from .models import BiometricDevice

logger = logging.getLogger("smart_attendance.device")


class DeviceAuthenticationError(Exception):
    pass


def authenticate_device(device_serial: str, device_secret: str) -> BiometricDevice:
    """
    Authenticate a biometric device using serial + shared secret.
    """
    try:
        device = BiometricDevice.objects.get(device_serial=device_serial)
    except BiometricDevice.DoesNotExist:
        logger.warning(
            "Biometric device authentication failed: unknown serial=%s",
            device_serial,
        )
        raise DeviceAuthenticationError("Unknown device.")

    secret_compare = (device_secret or "").strip()
    if not secret_compare or (device.device_secret or "").strip() != secret_compare:
        logger.warning(
            "Biometric device authentication failed: invalid secret serial=%s",
            device_serial,
        )
        raise DeviceAuthenticationError("Invalid credentials.")

    # Mark device as seen / online
    device.last_seen = timezone.now()
    device.status = BiometricDevice.STATUS_ONLINE
    device.save(update_fields=["last_seen", "status"])

    logger.info("Biometric device authenticated serial=%s id=%s", device_serial, device.id)
    return device

