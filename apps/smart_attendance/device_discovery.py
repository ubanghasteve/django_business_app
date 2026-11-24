import ipaddress
import logging
import socket
from typing import Iterable, List

from django.utils import timezone

from apps.core.models import Account

from .models import BiometricDevice

logger = logging.getLogger("smart_attendance.device")


DISCOVERY_PORTS = [4370, 8080, 80]
# Default: 192.168.0.1–192.168.0.255 for fast discovery (use 192.168.0.0/16 for full scan)
DISCOVERY_NETWORK = "192.168.0.0/24"


def _scan_host(ip: str, ports: Iterable[int]) -> List[int]:
    """
    Attempt to connect to the given IP on known biometric ports.
    Returns list of open ports.
    """
    open_ports: List[int] = []
    for port in ports:
        try:
            with socket.create_connection((ip, port), timeout=0.3):
                open_ports.append(port)
        except OSError:
            continue
    return open_ports


def discover_devices_for_tenant(tenant: Account) -> int:
    """
    Scan 192.168.x.x ranges and auto-register responding devices for a tenant.

    Returns number of devices discovered or updated.
    """
    discovered = 0
    network = ipaddress.ip_network(DISCOVERY_NETWORK)
    logger.info("Starting biometric device discovery for tenant_id=%s", tenant.id)

    for ip in network.hosts():
        ip_str = str(ip)
        open_ports = _scan_host(ip_str, DISCOVERY_PORTS)
        if not open_ports:
            continue
        for port in open_ports:
            device, created = BiometricDevice.objects.get_or_create(
                tenant=tenant,
                device_ip=ip_str,
                device_port=port,
                defaults={
                    "device_name": f"Biometric {ip_str}:{port}",
                    "device_serial": f"AUTO-{ip_str.replace('.', '-')}-{port}",
                    "device_model": "Auto-Discovered",
                    "firmware_version": "",
                    "device_secret": "",
                    "location": "",
                    "status": BiometricDevice.STATUS_ONLINE,
                    "last_seen": timezone.now(),
                },
            )
            if not created:
                device.status = BiometricDevice.STATUS_ONLINE
                device.last_seen = timezone.now()
                device.save(update_fields=["status", "last_seen"])
            discovered += 1
            logger.info(
                "Discovered biometric device tenant_id=%s ip=%s port=%s id=%s created=%s",
                tenant.id,
                ip_str,
                port,
                device.id,
                created,
            )
    logger.info(
        "Completed biometric device discovery for tenant_id=%s discovered=%s",
        tenant.id,
        discovered,
    )
    return discovered

