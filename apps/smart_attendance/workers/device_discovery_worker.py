"""
Device discovery worker – scans network and auto-registers biometric devices.
"""
from apps.core.models import Account
from ..device_discovery import discover_devices_for_tenant


def run_device_discovery() -> int:
    """
    Run device discovery for all tenants. Returns total devices discovered.
    """
    total = 0
    for account in Account.objects.all():
        total += discover_devices_for_tenant(account)
    return total
