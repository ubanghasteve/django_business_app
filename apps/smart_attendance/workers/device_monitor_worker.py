"""
Device monitor worker – pings devices and updates status.
"""
import logging
from django.utils import timezone

from ..models import BiometricDevice
from ..services.zk_device_service import ping_device

logger = logging.getLogger("smart_attendance.device")


def run_device_monitor() -> dict:
    """
    Ping all devices and update online/offline status.
    Returns {"checked": N, "online": N, "offline": N}.
    """
    devices = BiometricDevice.objects.filter(is_active=True).exclude(device_ip="")
    checked = 0
    online = 0
    offline = 0
    for device in devices:
        try:
            reachable = ping_device(str(device.device_ip), device.device_port or 4370, timeout=3)
            checked += 1
            if reachable:
                device.status = BiometricDevice.STATUS_ONLINE
                device.last_seen = timezone.now()
                device.save(update_fields=["status", "last_seen"])
                online += 1
            else:
                device.status = BiometricDevice.STATUS_OFFLINE
                device.save(update_fields=["status"])
                offline += 1
        except Exception as exc:
            logger.warning("Device monitor failed for device id=%s: %s", device.id, exc)
            device.status = BiometricDevice.STATUS_OFFLINE
            device.save(update_fields=["status"])
            offline += 1
    return {"checked": checked, "online": online, "offline": offline}
